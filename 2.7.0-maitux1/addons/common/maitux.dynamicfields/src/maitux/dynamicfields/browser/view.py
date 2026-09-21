# -*- coding: utf-8 -*-
"""动态字段管理配置页

两个 tab：

- ``objects``  按对象浏览：左栏类型清单，右栏按来源切三段
  （本包添加 / 其它 add-on / 原生），只有第一段渲染得出删除按钮
- ``all``      全部自定义字段：跨对象的扁平表 + 统计 + 脏配置告警

权限一律 ``cmf.ManagePortal``（Plone 原生权限）。刻意不用 senaite.core 的
自定义权限——本包靠 autoinclude 加载，顺序不保证排在 senaite.core 之后，
引用它的权限就会撞上 R1 那颗雷（ComponentLookupError）。
"""
import json

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from maitux.dynamicfields import _
from maitux.dynamicfields import assignable
from maitux.dynamicfields import atextender
from maitux.dynamicfields import config
from maitux.dynamicfields import dxschema
from maitux.dynamicfields import i18n
from maitux.dynamicfields import indexing
from maitux.dynamicfields import introspect
from maitux.dynamicfields import storage
from maitux.dynamicfields import validation

try:
    from bika.lims import api
except ImportError:  # pragma: no cover
    api = None

try:
    from senaite.core import logger
except ImportError:  # pragma: no cover
    import logging
    logger = logging.getLogger("maitux.dynamicfields")


def safe_unicode(value):
    """任何东西 -> unicode。Py2 下 bytes 和 unicode 混用是最常见的崩因。

    优先用 bika.lims.api.safe_unicode（仓库既有的安全函数），拿不到时自己兜底。
    """
    if value is None:
        return u""
    if api is not None:
        try:
            return api.safe_unicode(value)
        except Exception:
            pass
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return value.decode("utf-8", "ignore")
    try:
        return u"%s" % value
    except Exception:
        return u""


#: 显示位置徽章。单字，按语言取——每请求渲染，不是缓存的 schema
#: 单引号常量——拼 JS 字符串时要把它从文案里剔掉
QUOTE_CHAR = chr(39)

POSITION_SLOTS = (
    ("show_edit", u"编", u"E"),
    ("show_view", u"查", u"V"),
    ("show_list", u"列", u"L"),
    ("show_report", u"报", u"R"),
)


class DynamicFieldsView(BrowserView):
    """配置页"""

    template = ViewPageTemplateFile("templates/dynamicfields.pt")

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.messages = []
        self.errors = []

    def __call__(self):
        if self.request.method == "POST":
            self.handle_post()
        return self.template()

    # ------------------------------------------------------------------
    # 请求处理
    # ------------------------------------------------------------------

    def handle_post(self):
        form = self.request.form
        action = form.get("action") or ""
        handler = {
            "save_field": self.action_save_field,
            "delete_field": self.action_delete_field,
            "reindex_field": self.action_reindex_field,
            "import_config": self.action_import,
            "drop_broken": self.action_drop_broken,
        }.get(action)
        if handler is None:
            return
        try:
            handler(form)
        except Exception as exc:
            logger.exception("maitux.dynamicfields: action %s failed", action)
            self.errors.append(_(
                u"action_failed", default=u"Action failed: ${error}",
                mapping={"error": u"%s" % exc}))
        finally:
            # 配置一变，两边的 schema 缓存都清掉，不等下一次 rev 比较
            dxschema.invalidate()
            atextender.invalidate()

    def action_save_field(self, form):
        field_id = form.get("field_id") or ""
        existing = storage.get_record(field_id) if field_id else None

        if existing is not None:
            record = dict(existing)
        else:
            record = storage.defaults(
                safe_unicode(form.get("portal_type")),
                safe_unicode(form.get("name")).strip(),
                safe_unicode(form.get("type")))

        # 目标对象、字段名、字段类型创建后不可改——编辑时一律忽略表单里的值
        if existing is None:
            record["portal_type"] = safe_unicode(form.get("portal_type"))
            record["name"] = safe_unicode(form.get("name")).strip()
            record["type"] = safe_unicode(form.get("type"))

        record.update(self._read_common(form))
        record.update(self._read_type_specific(form, record.get("type")))

        problems = validation.validate_record(
            record, existing_id=record.get("id") if existing else None)
        if problems:
            self.errors.extend(problems)
            return

        storage.save_record(record)
        self.messages.append(_(
            u"field_saved",
            default=u"Field ${name} saved; effective immediately, no restart "
                    u"needed",
            mapping={"name": record.get("name")}))

        for message in indexing.ensure_index(record):
            self.messages.append(message)

    def action_delete_field(self, form):
        field_id = form.get("field_id") or ""
        record = storage.get_record(field_id)
        if record is None:
            self.errors.append(_(
                u"delete_missing",
                default=u"The field to delete does not exist"))
            return
        # 先摘索引再删定义：顺序反了就会在目录里留下无人维护的死索引
        for message in indexing.drop_index(record):
            self.messages.append(message)
        storage.delete_record(field_id)
        self.messages.append(_(
            u"field_deleted",
            default=u"Field ${name} deleted. Values already stored on the "
                    u"objects are kept but no longer shown.",
            mapping={"name": record.get("name")}))

    def action_reindex_field(self, form):
        record = storage.get_record(form.get("field_id") or "")
        if record is None:
            self.errors.append(_(u"field_missing", default=u"Field not found"))
            return
        for message in indexing.reindex(record):
            self.messages.append(message)

    def action_import(self, form):
        payload = form.get("payload") or ""
        upload = form.get("upload")
        if upload is not None and hasattr(upload, "read"):
            try:
                data = upload.read()
                if data:
                    payload = data
            except Exception:
                pass
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", "ignore")
        if not payload.strip():
            self.errors.append(_(u"import_empty", default=u"Nothing to import"))
            return
        mode = form.get("mode") or "merge"
        added, updated, skipped, errors = storage.import_json(payload, mode)
        self.messages.append(_(
            u"import_done",
            default=u"Import finished: ${added} added, ${updated} replaced, "
                    u"${skipped} skipped",
            mapping={"added": added, "updated": updated,
                     "skipped": skipped}))
        self.errors.extend(errors)

    def action_drop_broken(self, form):
        field_id = form.get("field_id") or ""
        record = storage.delete_record(field_id)
        if record is None:
            self.errors.append(_(
                u"record_missing",
                default=u"That configuration record does not exist"))
        else:
            self.messages.append(_(
                u"broken_dropped",
                default=u"Broken configuration ${type}.${name} deleted",
                mapping={"type": record.get("portal_type"),
                         "name": record.get("name")}))

    # ------------------------------------------------------------------

    def _read_common(self, form):
        languages = self.languages()
        return {
            "labels": self._read_lang_map(form, "label", languages),
            "descriptions": self._read_lang_map(form, "desc", languages),
            "required": self._flag(form, "required"),
            "readonly": self._flag(form, "readonly"),
            "default": safe_unicode(form.get("default")).strip(),
            "states": self._read_list(form, "states"),
            "show_edit": self._flag(form, "show_edit"),
            "show_view": self._flag(form, "show_view"),
            "show_list": self._flag(form, "show_list"),
            "list_default": self._flag(form, "list_default"),
            # 二期：报告模板尚未接入本包配置，界面上置灰，这里也钉死
            "show_report": False,
            "fieldset": (safe_unicode(form.get("fieldset")).strip()
                         or u"default"),
            "order": self._int(form.get("order"), 0),
            "index": self._flag(form, "index"),
            "metadata": self._flag(form, "metadata"),
        }

    def _read_type_specific(self, form, field_type):
        data = {"multi": self._flag(form, "multi")}

        if field_type in config.TYPES_WITH_OPTIONS:
            data["options"] = self._read_options(form)
        if field_type == config.TYPE_REFERENCE:
            data["allowed_types"] = self._read_list(form, "allowed_types")
            data["include_inactive"] = self._flag(form, "include_inactive")
        if field_type in config.TYPES_NUMERIC:
            data["min"] = self._number(form.get("min"))
            data["max"] = self._number(form.get("max"))
            data["precision"] = self._int(form.get("precision"), 2)
        if field_type in (config.TYPE_TEXT, config.TYPE_TEXTAREA):
            data["maxlen"] = self._number(form.get("maxlen"))
            data["regex"] = safe_unicode(form.get("regex")).strip()
            data["regex_msg"] = self._read_lang_map(
                form, "regex_msg", self.languages())
        return data

    def _read_options(self, form):
        keys = self._as_list(form.get("option_key"))
        options = []
        for index, key in enumerate(keys):
            key = safe_unicode(key).strip()
            if not key:
                continue
            labels = {}
            for language in self.languages():
                values = self._as_list(
                    form.get("option_label_%s" % _slug(language)))
                if index < len(values):
                    text = safe_unicode(values[index]).strip()
                    if text:
                        labels[language] = text
            options.append({"key": key, "labels": labels})
        return options

    def _read_lang_map(self, form, prefix, languages):
        """读多语言文案。

        ★ 必须 safe_unicode。Py2 下 request 给回来的中文是 utf-8 **bytes**，
        原样存进记录后，validation 里 ``u"%s" % value`` 会隐式 ASCII 解码，
        保存中文标签直接 UnicodeDecodeError（0xe6 就是「测」的首字节）。
        """
        mapping = {}
        for language in languages:
            value = safe_unicode(
                form.get("%s_%s" % (prefix, _slug(language)))).strip()
            if value:
                mapping[language] = value
        return mapping

    def _read_list(self, form, name):
        return [safe_unicode(v).strip()
                for v in self._as_list(form.get(name))
                if safe_unicode(v).strip()]

    @staticmethod
    def _as_list(value):
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return list(value)
        return [value]

    @staticmethod
    def _flag(form, name):
        value = form.get(name)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        return u"%s" % value in (u"1", u"on", u"true", u"True", u"yes")

    @staticmethod
    def _int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _number(value):
        if value in (None, "", u""):
            return None
        try:
            text = u"%s" % value
            return int(text) if u"." not in text else float(text)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # 模板取数
    # ------------------------------------------------------------------

    def tab(self):
        return self.request.get("tab") or "objects"

    def languages(self):
        """站点实际启用的语言——输入框按它动态生成，不写死中 / 英"""
        return i18n.get_site_languages()

    def language_slugs(self):
        return [{"code": lang, "slug": _slug(lang), "label": _lang_label(lang)}
                for lang in self.languages()]

    def current_language(self):
        return i18n.get_request_language(self.request) \
            or i18n.get_default_language()

    def type_groups(self):
        return introspect.list_type_groups(query=self.search_query(),
                                           language=self.current_language())

    def search_query(self):
        """左栏「搜索对象」的关键字"""
        return safe_unicode(self.request.get("q")).strip()

    def field_query(self):
        """右栏「筛选字段」的关键字"""
        return safe_unicode(self.request.get("fq")).strip()

    def link_suffix(self):
        """点类型时把搜索关键字带上，否则一点就丢了筛选

        ★ Py2 陷阱：request 里的中文是 **byte string**，直接对它调
        ``.encode("utf-8")`` 会先用 ASCII 隐式解码再编码，立刻
        ``UnicodeDecodeError: 'ascii' codec can't decode byte 0xe6``。
        所以先用 safe_unicode() 归一成 unicode，再 encode 给 quote。
        （规则 R13：Py2 转字符串一律走安全函数。）
        """
        query = self.search_query()
        if not query:
            return u""
        try:
            from urllib import quote
        except ImportError:  # pragma: no cover - Py3
            from urllib.parse import quote
        try:
            return u"&q=%s" % quote(query.encode("utf-8"))
        except Exception:
            # 编码失败也不许把整页搞挂，大不了链接上不带关键字
            return u""

    def selected_type(self):
        requested = self.request.get("portal_type")
        available = [item["portal_type"] for item in introspect.list_types()]
        if requested in available:
            return requested
        return available[0] if available else None

    def selected_info(self):
        portal_type = self.selected_type()
        if not portal_type:
            return None
        mechanism = introspect.get_mechanism(portal_type)
        replacement = config.DEPRECATED_TYPES.get(portal_type)
        return {
            "portal_type": portal_type,
            "title": introspect.get_type_title(portal_type,
                                               self.current_language()),
            "mechanism": mechanism,
            "deprecated": bool(replacement),
            "replaced_by": replacement or u"",
            "mechanism_note": (
                _(u"mech_at",
                  default=u"Archetypes - extended via schemaextender")
                if mechanism == introspect.MECH_AT
                else _(u"mech_dx",
                       default=u"Dexterity - extended via behavior")),
            "states": introspect.get_workflow_states(portal_type),
        }

    def field_sections(self):
        """右栏三段。本包那段取自配置库（有全部元数据），另两段取自内省"""
        portal_type = self.selected_type()
        if not portal_type:
            return {"own": [], "addon": [], "native": []}
        grouped = introspect.group_fields(portal_type)
        query = self.field_query()
        own = [self.describe_record(r)
               for r in storage.get_records_for_type(portal_type)]
        if query:
            own = [f for f in own
                   if introspect._matches(query, f["name"], f["label"])]
            grouped["addon"] = [
                f for f in grouped["addon"]
                if introspect._matches(query, f["name"], f["label"])]
            grouped["native"] = [
                f for f in grouped["native"]
                if introspect._matches(query, f["name"], f["label"])]
        return {
            "own": own,
            "addon": grouped["addon"],
            "native": grouped["native"],
        }

    def describe_record(self, record):
        """一条记录 -> 界面需要的展示模型"""
        language = self.current_language()
        status = indexing.index_status(record)
        return {
            "id": record.get("id"),
            "name": record.get("name"),
            "portal_type": record.get("portal_type"),
            "type": record.get("type"),
            "type_title": _field_type_title(record.get("type"), language),
            "label": i18n.pick_text(record.get("labels") or {}, language,
                                    fallback=record.get("name") or u""),
            "label_en": (record.get("labels") or {}).get("en", u""),
            "positions": [
                {"key": key,
                 "text": (en if _is_en(language) else zh),
                 "on": bool(record.get(key))}
                for key, zh, en in POSITION_SLOTS],
            "indexed": status["indexed"],
            "index_label": (_(u"idx_yes", default=u"yes")
                            if status["indexed"] else u"—"),
            "required": bool(record.get("required")),
            "creator": record.get("creator") or u"",
            "created": (record.get("created") or u"")[:10],
            "raw": record,
        }

    # ------------------------------------------------------------------
    # 全局总览
    # ------------------------------------------------------------------

    def all_field_groups(self):
        groups = {}
        for record in storage.get_all_records():
            groups.setdefault(record.get("portal_type"), []).append(record)
        result = []
        for portal_type in sorted(groups.keys()):
            mechanism = introspect.get_mechanism(portal_type)
            result.append({
                "portal_type": portal_type,
                "title": introspect.get_type_title(
                    portal_type, self.current_language()),
                "mechanism": mechanism or u"?",
                "broken": mechanism is None,
                "count": len(groups[portal_type]),
                "rows": [self.describe_record(r) for r in groups[portal_type]],
            })
        return result

    def stats(self):
        records = storage.get_all_records()
        types = set([r.get("portal_type") for r in records])
        at_count = dx_count = 0
        for portal_type in types:
            mechanism = introspect.get_mechanism(portal_type)
            if mechanism == introspect.MECH_AT:
                at_count += 1
            elif mechanism == introspect.MECH_DX:
                dx_count += 1
        indexed = len([r for r in records
                       if indexing.index_status(r)["indexed"]])
        return {
            "total": len(records),
            "types": len(types),
            "at": at_count,
            "dx": dx_count,
            "indexed": indexed,
            "broken": len(self.broken_records()),
            "max_per_type": config.MAX_FIELDS_PER_TYPE,
            "max_total": config.MAX_FIELDS_TOTAL,
        }

    def broken_records(self):
        """脏配置：指向的类型在当前站点不存在

        NFR-1 要求这类记录被**跳过而不是抛异常**，站点照常启动——但必须有人
        看得见，否则就成了"悄悄丢字段"。
        """
        broken = []
        for record in storage.get_all_records():
            portal_type = record.get("portal_type")
            if not introspect.type_exists(portal_type):
                broken.append({
                    "id": record.get("id"),
                    "name": record.get("name"),
                    "portal_type": portal_type,
                    "reason": _(
                        u"broken_reason",
                        default=u"Object type ${type} does not exist on "
                                u"this site",
                        mapping={"type": portal_type}),
                })
        return broken

    def shadow_warning(self):
        """本包的 IBehaviorAssignable 是否被别的 add-on 旁路掉了

        INNOCARE.labid 那种 ``@adapter(ILaboratory)`` 比本包的
        ``@adapter(IDexterityContent)`` 更具体，zope 会挑它——本包在该类型上
        整个失效。不实测就会静默丢字段。
        """
        portal_type = self.selected_type()
        if not portal_type:
            return None
        if introspect.get_mechanism(portal_type) != introspect.MECH_DX:
            return None
        if not storage.count_for_type(portal_type):
            return None
        instance = introspect._find_instance(portal_type)
        if instance is None:
            return None
        active = assignable.is_assignable_active(instance)
        if active is False:
            return _(
                u"shadow_warning",
                default=u"Another add-on registered a more specific "
                        u"IBehaviorAssignable for ${type}; dynamic fields "
                        u"will not take effect on it.",
                mapping={"type": portal_type})
        return None

    # ------------------------------------------------------------------
    # 表单选项
    # ------------------------------------------------------------------

    def deprecated_warning(self):
        """已废弃类型的告警文案（模板用）"""
        info = self.selected_info()
        if not info or not info.get("deprecated"):
            return u""
        return _(
            u"deprecated_detail",
            default=u"${type} has been replaced by ${new} (an AT to DX "
                    u"migration leftover); both are still registered on this "
                    u"site. Fields added here will not appear on the one that "
                    u"is actually in use.",
            mapping={"type": info["portal_type"], "new": info["replaced_by"]})

    def delete_confirm_text(self):
        """删除确认框的文案。

        要塞进 JS 的字符串字面量里，所以把单引号和换行都换掉，
        否则生成的 onsubmit 会是坏的 JS。
        """
        text = self.translate(_(
            u"delete_confirm",
            default=u"The field will no longer be shown. Values already "
                    u"stored on the objects are kept. Delete it?"))
        return text.replace(QUOTE_CHAR, u" ").replace(u"\n", u" ")

    def translate(self, message):
        """把 Message 翻成当前请求语言的 unicode"""
        try:
            from zope.i18n import translate as ztranslate
            return safe_unicode(ztranslate(message, context=self.request))
        except Exception:
            return safe_unicode(message)

    def field_types(self):
        language = self.current_language()
        is_zh = language.startswith(u"zh")
        return [{"id": t[0], "title": t[1] if is_zh else t[2]}
                for t in config.FIELD_TYPES]

    def reference_type_options(self):
        """引用字段能指向的类型。

        用 list_reference_targets() 而不是 list_types()：能被加字段的类型
        和引用能指向的类型是两件事。共用一份清单的话，Project /
        HazardCategory / StorageCondition 这些别的 addon 提供的类型选不到。
        """
        return [{"id": item["portal_type"],
                 "title": u"%s (%s)" % (item["title"], item["portal_type"])}
                for item in introspect.list_reference_targets(
                    self.current_language())]

    def types_with_options(self):
        return list(config.TYPES_WITH_OPTIONS)

    def export_url(self):
        return "%s/@@dynamic-fields-export" % self.portal_url()

    def portal_url(self):
        if api is None:
            return ""
        try:
            return api.get_url(api.get_portal())
        except Exception:
            return ""

    def base_url(self):
        return "%s/@@dynamic-fields" % self.portal_url()

    def json_dumps(self, value):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return "null"


class DynamicFieldsExportView(BrowserView):
    """导出全部字段定义为 JSON 文件

    不走 GenericSetup，所以这是唯一的配置搬运方式（开发环境配好 -> 导到生产）
    """

    def __call__(self):
        payload = storage.export_json()
        response = self.request.response
        response.setHeader("Content-Type", "application/json; charset=utf-8")
        response.setHeader(
            "Content-Disposition",
            "attachment; filename=maitux-dynamicfields.json")
        if isinstance(payload, type(u"")):
            payload = payload.encode("utf-8")
        return payload


# --------------------------------------------------------------------------

def _slug(language):
    """``zh-cn`` -> ``zh_cn``，用作表单字段名的一部分（必须是 ASCII）"""
    return (language or u"").replace(u"-", u"_").replace(u".", u"_")


def _is_en(language):
    return not (u"%s" % (language or u"")).lower().startswith(u"zh")


def _lang_label(language):
    """语言自己的名字，不翻译——中文那一栏永远叫「中文」"""
    return {
        u"zh-cn": u"中文",
        u"zh": u"中文",
        u"en": u"English",
    }.get(language, language)


def _field_type_title(field_type, language):
    is_zh = (language or u"").startswith(u"zh")
    for item in config.FIELD_TYPES:
        if item[0] == field_type:
            return item[1] if is_zh else item[2]
    return field_type or u""
