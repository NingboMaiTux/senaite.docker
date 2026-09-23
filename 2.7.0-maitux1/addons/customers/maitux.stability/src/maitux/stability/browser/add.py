# -*- coding: utf-8 -*-
from bika.lims import api
from plone import api as ploneapi
from plone.namedfile.file import NamedBlobFile
from senaite.core.browser.dexterity.add import DefaultAddForm
from senaite.core.browser.dexterity.add import DefaultAddView

from maitux.stability.i18n import translate_stability
from maitux.stability.plan_copy import build_copied_title
from maitux.stability.plan_copy import build_copy_rows
from maitux.stability.plan_copy import get_copy_source
from maitux.stability.plan_copy import get_plan_template_uid
from maitux.stability.plan_copy import get_start_time_value


def _first(value):
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _as_unicode(value):
    return api.safe_unicode(value or u"")


def _extract_uid(value):
    value = _first(value)
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("uid") or value.get("UID") or value.get("value") or ""
    if isinstance(value, basestring):
        return value.strip()
    return ""


class StabilityPlanAddForm(DefaultAddForm):
    def __init__(self, context, request):
        super(StabilityPlanAddForm, self).__init__(context, request)

    def updateFields(self):
        super(StabilityPlanAddForm, self).updateFields()
        if "article" not in self.fields:
            return

        article_field = self.fields["article"].field
        article_field.required = False

        source = self._get_copy_source()
        if source is not None:
            # 复制场景：不重新上传附件时，沿用被复制方案的附件。
            article = getattr(source, "article", None)
            filename = getattr(article, "filename", None)
            if filename:
                article_field.description = translate_stability(
                    u"Article of the copied plan: {0}. "
                    u"Leave this field empty to keep this file."
                ).format(api.safe_unicode(filename))
            else:
                article_field.description = translate_stability(
                    u"No article was found in the copied plan. "
                    u"You can upload a file here if needed.")
            return

        template = self._get_template()
        if template is None:
            return
        article = getattr(template, "article", None)
        filename = getattr(article, "filename", None)
        if filename:
            # 创建计划时允许用户看到附件字段；若不重新上传，则沿用模板中的附件。
            article_field.description = translate_stability(
                u"Current template article: {0}. "
                u"Leave this field empty to keep the template file."
            ).format(api.safe_unicode(filename))
        else:
            article_field.description = translate_stability(
                u"No template article was found. "
                u"You can upload a file here if needed.")

    def _get_template(self):
        template_uid = (
            self.request.get("template_uid") or
            self.request.form.get("template_uid") or
            self.request.form.get("form.widgets.plan_template")
        )
        template_uid = _extract_uid(template_uid)
        if not api.is_uid(template_uid):
            return None
        try:
            return api.get_object(template_uid)
        except Exception:
            return None

    def _apply_template_defaults(self):
        template = self._get_template()
        if template is None:
            return []

        changed = []

        def set_default(name, value):
            field = self.fields.get(name)
            if field is None:
                return
            changed.append((field.field, field.field.default))
            field.field.default = value

        set_default("title", _as_unicode(api.get_title(template)))
        set_default("description", _as_unicode(getattr(template, "description", u"") or u""))
        set_default("plan_template", [api.get_uid(template)])

        for name in ("sample_quantity", "reserve_quantity"):
            set_default(name, getattr(template, name, 0) or 0)

        unit = _first(getattr(template, "unit", None))
        if unit:
            set_default("unit", [unit])

        # 模板不再维护 Timepoints 子对象，计划明细由用户在创建计划时直接添加。
        set_default("plan_details", [])
        return changed

    def _get_copy_source(self):
        """返回被复制的方案（列表页「复制计划」跳转时带 copy_from_uid）。"""
        try:
            return get_copy_source(self.request)
        except Exception:
            return None

    def _apply_copy_defaults(self):
        """按被复制方案预填表单字段（前端 JS 拿不到时的服务端兜底）。"""
        source = self._get_copy_source()
        if source is None:
            return []

        changed = []

        def set_default(name, value):
            field = self.fields.get(name)
            if field is None:
                return
            changed.append((field.field, field.field.default))
            field.field.default = value

        set_default("title", build_copied_title(source))
        set_default(
            "description",
            _as_unicode(getattr(source, "description", u"") or u""),
        )

        template_uid = get_plan_template_uid(source)
        if api.is_uid(template_uid):
            set_default("plan_template", [template_uid])

        start_time = get_start_time_value(source)
        if start_time is not None:
            # T0 先沿用被复制方案（本地时间），用户可改成新研究的开始时间。
            set_default("start_time", start_time)

        for name in ("sample_quantity", "reserve_quantity"):
            set_default(name, getattr(source, name, 0) or 0)

        unit = _first(getattr(source, "unit", None))
        if unit:
            set_default("unit", [unit])

        # 表单里预填的是可直接落库的明细行（不含前端展示辅助字段）。
        set_default("plan_details", build_copy_rows(source))
        return changed

    def _copy_article(self, source):
        """复制附件：新建文件对象，避免直接复用原对象上的 Blob 引用。"""
        if source is None:
            return None
        article = getattr(source, "article", None)
        if not article:
            return None
        try:
            data = article.data
        except Exception:
            data = None
        if not data:
            return None
        return NamedBlobFile(
            data=data,
            filename=getattr(article, "filename", None),
            contentType=getattr(article, "contentType", ""),
        )

    def _get_article_from(self, obj):
        """取附件的优先级：被复制方案 > 方案模板。"""
        if obj is None:
            return None
        return self._copy_article(obj)

    def _has_article(self, obj):
        if obj is None:
            return False
        article = getattr(obj, "article", None)
        if not article:
            return False
        try:
            return bool(article.data)
        except Exception:
            return True

    def _notify_details_fallback(self, count):
        """明细由后端兜底补上时给出提示，避免用户以为前端预填生效了。"""
        try:
            ploneapi.portal.show_message(
                message=translate_stability(
                    u"Plan details were copied from the selected plan: {0} row(s)."
                ).format(count),
                request=self.request,
                type="info",
            )
        except Exception:
            pass

    def updateWidgets(self):
        if self._get_copy_source() is not None:
            # 复制场景以被复制方案为准，不再套用模板默认值。
            changed = self._apply_copy_defaults()
        else:
            changed = self._apply_template_defaults()
        try:
            super(StabilityPlanAddForm, self).updateWidgets()
        finally:
            for field, default in changed:
                field.default = default

    def _get_template_from_value(self, value):
        template_uid = _extract_uid(value)
        if not api.is_uid(template_uid):
            return None
        try:
            return api.get_object(template_uid)
        except Exception:
            return None

    def create(self, data):
        source = self._get_copy_source()
        template = self._get_template_from_value(data.get("plan_template")) or self._get_template()
        if source is not None:
            # 复制场景：提交值缺失时用被复制方案补齐，避免前端预填失效导致字段丢失。
            data.setdefault("title", build_copied_title(source))
            data.setdefault(
                "description",
                _as_unicode(getattr(source, "description", u"") or u""),
            )
            if not data.get("plan_template"):
                template_uid = get_plan_template_uid(source)
                if api.is_uid(template_uid):
                    data["plan_template"] = [template_uid]
                    template = self._get_template_from_value(template_uid) or template
            for name in ("sample_quantity", "reserve_quantity"):
                data.setdefault(name, getattr(source, name, 0) or 0)
            unit = _first(getattr(source, "unit", None))
            if unit:
                data.setdefault("unit", [unit])

            if not data.get("plan_details"):
                # 前端没能把明细预填进表单时，这里兜底补上复制出来的明细，
                # 否则会静默生成一个没有任何时间点的空方案。
                rows = build_copy_rows(source)
                if rows:
                    data["plan_details"] = rows
                    self._notify_details_fallback(len(rows))

        if template is not None:
            # 创建时再次兜底带入模板字段，避免文件控件默认值在表单提交时丢失。
            data.setdefault("title", _as_unicode(api.get_title(template)))
            data.setdefault("description", _as_unicode(getattr(template, "description", u"") or u""))
            data.setdefault("plan_template", [api.get_uid(template)])
            for name in ("sample_quantity", "reserve_quantity"):
                data.setdefault(name, getattr(template, name, 0) or 0)
            unit = _first(getattr(template, "unit", None))
            if unit:
                data.setdefault("unit", [unit])
        if not data.get("article"):
            article = self._get_article_from(source) or self._get_article_from(template)
            if article is not None:
                data["article"] = article
        return super(StabilityPlanAddForm, self).create(data)

    def add(self, object):
        source = self._get_copy_source()
        template = self._get_template_from_value(getattr(object, "plan_template", None)) or self._get_template()
        if not self._has_article(object):
            article = self._get_article_from(source) or self._get_article_from(template)
            if article is not None:
                # 在对象真正加入容器前兜底回写附件，避免文件字段在 create(data) 阶段丢失。
                object.article = article
        super(StabilityPlanAddForm, self).add(object)
        try:
            object.reindexObject()
        except Exception:
            pass


class StabilityPlanAddView(DefaultAddView):
    form = StabilityPlanAddForm
