# -*- coding: utf-8 -*-
"""字段定义校验

校验必须在**写入路径**上，不能只靠界面控制显隐——模板管渲染，构造请求可以
绕过它（与 maitux.reviewerassignment 里那条同源的教训）。
"""
import re

from maitux.dynamicfields import _
from maitux.dynamicfields import config
from maitux.dynamicfields import storage

_NAME_RE = re.compile(config.FIELD_NAME_PATTERN)
_OPTION_RE = re.compile(config.OPTION_KEY_PATTERN)


def validate_record(record, portal=None, existing_id=None,
                    skip_uniqueness=False):
    """返回问题列表；空列表 = 通过

    :param existing_id: 编辑时传本条 id，避免跟自己冲突
    :param skip_uniqueness: 导入时用——同批次内的先后顺序不该判为冲突
    """
    problems = []

    portal_type = record.get("portal_type")
    if not portal_type:
        problems.append(_(u"v_need_type", default=u"Pick a target object type"))
    elif portal_type in config.EXCLUDED_TYPES:
        problems.append(_(u"v_type_excluded", default=u"Object type ${type} is explicitly excluded",
                        mapping={"type": portal_type}))
    elif portal_type not in config.ALLOWED_TYPES:
        problems.append(_(u"v_type_unsupported", default=u"Object type ${type} is not in the supported list",
                        mapping={"type": portal_type}))

    name = record.get("name") or ""
    if not name:
        problems.append(_(u"v_need_name", default=u"Field name is required"))
    elif not _NAME_RE.match(name):
        problems.append(_(
            u"v_bad_name",
            default=u"Field name must start with an ASCII letter and contain "
                    u"only letters, digits and underscores, 2-50 chars: "
                    u"${name}",
            mapping={"name": name}))
    elif name in config.RESERVED_NAMES:
        problems.append(_(u"v_reserved", default=u"${name} is a reserved name",
                        mapping={"name": name}))

    field_type = record.get("type")
    if field_type not in config.FIELD_TYPE_IDS:
        problems.append(_(u"v_bad_field_type", default=u"Invalid field type: ${type}",
                        mapping={"type": field_type}))

    if not _has_any_label(record):
        problems.append(_(u"v_need_label", default=u"Fill in a label in at least one language"))

    problems.extend(_validate_type_specific(record, field_type))

    if portal_type and name and not skip_uniqueness:
        problems.extend(
            _validate_uniqueness(portal_type, name, portal, existing_id))

    if portal_type and existing_id is None and not skip_uniqueness:
        problems.extend(_validate_quota(portal_type, portal))

    return problems


# --------------------------------------------------------------------------

def _text(value):
    """任何东西 -> unicode。

    ★ 兜底用。Py2 下 ``u"%s" % <utf-8 bytes>`` 会隐式 ASCII 解码然后抛
    UnicodeDecodeError —— 保存中文标签炸掉就是这条。正经的修法是在
    view.py 的写入边界归一，这里再挡一层，防止别的调用方（导入 JSON、
    脚本写入）绕过边界。
    """
    if value is None:
        return u""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return value.decode("utf-8", "ignore")
    try:
        return u"%s" % value
    except Exception:
        return u""


def _has_any_label(record):
    labels = record.get("labels") or {}
    for value in labels.values():
        if _text(value).strip():
            return True
    return False


def _validate_type_specific(record, field_type):
    problems = []

    if field_type in config.TYPES_WITH_OPTIONS:
        options = record.get("options") or []
        if not options:
            problems.append(_(u"v_need_option", default=u"A choice field needs at least one option"))
        seen = set()
        for option in options:
            key = (option or {}).get("key") or ""
            if not key:
                problems.append(_(u"v_option_key_empty", default=u"Option key must not be empty"))
                continue
            if not _OPTION_RE.match(key):
                # 设计红线：一旦把中文存进对象，这份数据永远翻译不了，
                # 索引、导出、统计也全部锁死在中文上
                problems.append(_(
                    u"v_option_ascii",
                    default=u"Option keys must be ASCII (letters, digits, "
                            u"underscore, hyphen): ${key} - localized text "
                            u"belongs in the labels",
                    mapping={"key": key}))
                continue
            if key in seen:
                problems.append(_(u"v_option_dup", default=u"Duplicate option key: ${key}",
                        mapping={"key": key}))
            seen.add(key)
            if not _option_has_label(option):
                problems.append(_(u"v_option_label", default=u"Option ${key} needs a label in at least one language",
                        mapping={"key": key}))

        # 默认值必须是上面某个选项的 key。界面上是单选钮选不错，
        # 但导入 JSON、脚本写入这些路径绕过界面，得在这儿挡一次。
        default = record.get("default")
        if default:
            keys = [(o or {}).get("key") for o in options]
            if default not in keys:
                problems.append(_(
                    u"v_default_not_option",
                    default=u"The default value ${value} is not one of the "
                            u"option keys",
                    mapping={"value": default}))

    if field_type == config.TYPE_REFERENCE:
        allowed = record.get("allowed_types") or []
        if not allowed:
            problems.append(_(u"v_ref_types", default=u"A reference field needs allowed object types"))

    if field_type in config.TYPES_NUMERIC:
        minimum = record.get("min")
        maximum = record.get("max")
        if minimum is not None and maximum is not None:
            try:
                if float(minimum) > float(maximum):
                    problems.append(_(u"v_min_max", default=u"Minimum must not be greater than maximum"))
            except (TypeError, ValueError):
                problems.append(_(u"v_min_max_num", default=u"Minimum and maximum must be numbers"))

    regex = record.get("regex")
    if regex:
        try:
            re.compile(regex)
        except Exception as exc:
            problems.append(_(u"v_bad_regex", default=u"Invalid validation regex: ${error}",
                        mapping={"error": u"%s" % exc}))
        if not _regex_msg_ok(record):
            problems.append(_(u"v_regex_msg", default=u"A validation regex requires a failure message"))

    if record.get("show_list") and not record.get("metadata"):
        problems.append(_(
            u"v_needs_metadata",
            default=u"Showing a field as a listing column also requires the "
                    u"metadata column - without it the listing cannot read "
                    u"the value"))

    return problems


def _option_has_label(option):
    labels = (option or {}).get("labels") or {}
    for value in labels.values():
        if _text(value).strip():
            return True
    return False


def _regex_msg_ok(record):
    messages = record.get("regex_msg") or {}
    for value in messages.values():
        if _text(value).strip():
            return True
    return False


def _validate_uniqueness(portal_type, name, portal, existing_id):
    """与原生字段、其它 add-on 字段、本包已有字段都不得重名"""
    problems = []

    for record in storage.get_records_for_type(portal_type, portal):
        if record.get("name") == name and record.get("id") != existing_id:
            problems.append(_(u"v_dup_own", default=u"This object already has a custom field named ${name}",
                        mapping={"name": name}))
            break

    # 原生字段 / 其它 add-on 的字段
    try:
        from maitux.dynamicfields import introspect
        foreign = introspect.get_foreign_field_names(portal_type)
    except Exception:
        foreign = set()
    if name in foreign:
        problems.append(_(
            u"v_dup_foreign",
            default=u"${type} already has a field with this name (native or "
                    u"from another add-on); pick a different one",
            mapping={"type": portal_type}))

    return problems


def _validate_quota(portal_type, portal):
    problems = []
    if storage.count_for_type(portal_type, portal) >= config.MAX_FIELDS_PER_TYPE:
        problems.append(_(
            u"v_quota_type",
            default=u"At most ${max} custom fields per object; limit reached",
            mapping={"max": config.MAX_FIELDS_PER_TYPE}))
    if storage.count_all(portal) >= config.MAX_FIELDS_TOTAL:
        problems.append(_(
            u"v_quota_total",
            default=u"At most ${max} custom fields site wide; limit reached",
            mapping={"max": config.MAX_FIELDS_TOTAL}))
    return problems
