# -*- coding: utf-8 -*-
from bika.lims import api
from plone import api as ploneapi
from plone.namedfile.file import NamedBlobFile
from senaite.core import logger
from senaite.core.browser.dexterity.add import DefaultAddForm
from senaite.core.browser.dexterity.add import DefaultAddView

from maitux.stability import timepoints
from maitux.stability.i18n import translate_stability
from maitux.stability.plandetails import new_detail_row
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

        # 「样品自动化」三项从方案模板继承：
        #   * auto_create_samples —— 模板上的开关就是"这个品种要不要自动登样"，
        #     方案上是一个可覆盖的开关（见 automation.is_plan_enabled）；
        #   * client —— **登样时样品登记到哪个客户名下**（需求确认：维护在方案上，
        #     登样时自动带过去）。模板上给默认值，省得每个方案手选一次；
        #   * contact —— 自动建样时用的联系人，方案可再改。
        # ⚠️ 必须在这里带过来：方案级字段的 schema 默认值是 False/空，
        #    不带就等于"模板上勾了也没用"。
        set_default("auto_create_samples",
                    bool(getattr(template, "auto_create_samples", False)))
        client = _first(getattr(template, "client", None))
        if client:
            set_default("client", [client])
        contact = _first(getattr(template, "contact", None))
        if contact:
            set_default("contact", [contact])

        # 模板不再维护 Timepoints 子对象：计划明细由用户在创建计划时直接录入。
        # 明细的**初始值**由 _seed_initial_row() 统一预置（一行 0 点，可删），
        # 这里不再 set_default("plan_details", []) —— 否则会把预置行覆盖回空。
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

        # 「样品自动化」跟着被复制的方案走（复制常用于"同设计、新批次"，
        # 自动登样口径通常也一致；用户可在表单上改）。
        set_default("auto_create_samples",
                    bool(getattr(source, "auto_create_samples", False)))
        client = _first(getattr(source, "client", None))
        if client:
            set_default("client", [client])
        contact = _first(getattr(source, "contact", None))
        if contact:
            set_default("contact", [contact])

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
            # 复制场景以被复制方案为准，不再套用模板默认值，也**不预置 0 点行**：
            # 复制要忠实复制源方案的明细（源方案缺 0 点会在方案页/看板给出提示）。
            changed = self._apply_copy_defaults()
        else:
            changed = self._apply_template_defaults()
            changed.extend(self._seed_initial_row())
        try:
            super(StabilityPlanAddForm, self).updateWidgets()
        finally:
            for field, default in changed:
                field.default = default

    def _seed_initial_row(self):
        """给新建表单的 ``plan_details`` 设一个默认值：**一行 0 点**（B 方案，2026-09-30）。

        ⚠️ **本版本的 DataGrid 不渲染字段默认值**（2026-09-30 实测）：
        设了默认值之后渲染出来的新建表单里 ``plan_details.count=0``、
        一个真实行都没有，只有 ``TT`` 原型行 —— 明细行是**前端 JS** 填进去的
        （见 ``viewlets/templates/stabilityplantemplate_form.pt`` 的
        ``populatePlanDetails``）。

        所以"新建方案预置一行 0 点"真正生效的是两条路：

        1. **前端**：``applyPlanInitialRowDefault()`` 在"既不复制、也不按模板建"的
           普通新建表单上插一行 0 点（用户可见、可删）；
        2. **服务端**：``create()`` 里在"提交里压根没有 datagrid"时兜底补一行
           （脚本 / 关了 JS 的客户端也拿得到基线点）。

        这个默认值仍然保留一份：它是"别的渲染路径（换 DataGrid 实现、或将来
        senaite 支持默认行）"的兜底，写上不会有副作用。
        """
        field = self.fields.get("plan_details")
        if field is None:
            return []
        try:
            current = field.field.default
        except Exception:
            return []
        if current:
            # 已经被别处填过（历史数据/将来若模板又开始维护时间点）就不动它
            return []
        field.field.default = [new_detail_row()]
        return [(field.field, current)]

    def _grid_was_submitted(self):
        """提交里有没有 ``form.widgets.plan_details`` 的字段（= 页面上确实渲染了明细表格）。

        用来区分两种"明细为空"：
        * **页面渲染过、用户把行删光了** -> 尊重用户（不再补 0 点行）；
        * **压根没有明细字段**（脚本直接 POST / 表单没渲染出来）-> 兜底补一行 0 点。
        """
        try:
            for key in self.request.form.keys():
                if str(key).startswith("form.widgets.plan_details"):
                    return True
        except Exception:
            return False
        return False

    def _notify_initial_row_fallback(self):
        try:
            ploneapi.portal.show_message(
                message=translate_stability(
                    u"A zero point row (Timepoint (Months) = 0) was added to the "
                    u"new plan: it can be deleted or changed later."),
                request=self.request, type="info")
        except Exception:
            pass

    def _get_template_from_value(self, value):
        template_uid = _extract_uid(value)
        if not api.is_uid(template_uid):
            return None
        try:
            return api.get_object(template_uid)
        except Exception:
            return None

    def _clean_plan_details(self, data):
        """清洗提交上来的明细行 —— z3c.form 的 NO_VALUE 哨兵绝不能写库。

        ★ 与编辑页同款的写库风险（见 `timepoints.is_sentinel` 的注释）：
          DataGrid 的**整行**没提交上来时，`MultiWidget.extract` 会把
          `z3c.form.interfaces.NO_VALUE` 哨兵塞进值列表当占位；哨兵不可 pickle，
          写进 ZODB 会让事务在 commit 时抛 PicklingError（**整个新建全丢、
          页面 500**）。新建页没有"库里那一份明细"可退回，所以只能丢掉读不出来
          的行，并**明确告诉用户**（不能悄悄吞掉：那会变成"我填的行没了"）。
        """
        if "plan_details" not in data:
            return data
        raw = data.get("plan_details")
        if not isinstance(raw, (list, tuple)):
            logger.warning(
                "Unreadable plan_details submitted while adding a stability "
                "plan: %r -> use an empty list", raw)
            data = dict(data)
            data["plan_details"] = []
            self._notify_unreadable_details()
            return data
        rows, dropped = timepoints.clean_extracted_rows(raw)
        if not dropped and rows is raw:
            return data
        if dropped:
            logger.warning(
                "Dropped %s unreadable timepoint row(s) while adding a "
                "stability plan", dropped)
            self._notify_unreadable_details()
        data = dict(data)
        data["plan_details"] = rows
        return data

    def _notify_unreadable_details(self):
        try:
            ploneapi.portal.show_message(
                message=translate_stability(
                    u"Some timepoint rows could not be read and were dropped. "
                    u"Please reload the page and fill them in again."),
                request=self.request, type="error")
        except Exception:
            pass

    def create(self, data):
        data = self._clean_plan_details(data)
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
        elif not data.get("plan_details") and not self._grid_was_submitted():
            # 非复制（新建 / 按模板新建）：提交里**压根没有 datagrid** 时兜底补一行 0 点。
            #
            # ★ 2026-09-30（B 方案）：0 点（基线点）不强制，但"新建的方案应该有基线点"。
            #   注意这里的判据是"datagrid 有没有出现在提交里"：
            #     * 页面渲染过、用户把行删光了 -> **尊重用户**，不补（`plan_details.count=0` 也在提交里）；
            #     * 脚本 / 关掉 JS 的客户端直接 POST -> 补一行，免得建出没有基线点的空方案。
            data["plan_details"] = [new_detail_row()]
            self._notify_initial_row_fallback()

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
        self._seed_automation_switch(object, source, template)
        super(StabilityPlanAddForm, self).add(object)
        try:
            object.reindexObject()
        except Exception:
            pass

    def _seed_automation_switch(self, object, source, template):
        """方案级「自动登样」开关：字段被权限 omit 时按来源补上。

        为什么需要这一步：``auto_create_samples`` 挂了字段级写权限
        （``ManageSampleAutomation``）。**权限不足的用户看不到这个字段**，
        于是提交数据里根本没有它 → 表单的 ``applyChanges`` 不会写它 →
        对象上读到的就是 schema 默认值 ``False`` ——
        结果是"模板上勾了自动登样，登记员建的方案却是关的"。

        这里按"字段是否真的在表单里"来区分两种情况：

        * 字段在表单里 → 用户看得见也能改，**以提交值为准**（不覆盖）；
        * 字段不在表单里（被 omit）→ 无法表达，按**被复制方案 → 方案模板**带入。
        """
        try:
            if "auto_create_samples" in self.fields:
                return
        except Exception:
            return

        wanted = False
        if source is not None:
            wanted = bool(getattr(source, "auto_create_samples", False))
        elif template is not None:
            wanted = bool(getattr(template, "auto_create_samples", False))
        if not wanted:
            return
        try:
            object.auto_create_samples = True
        except Exception:
            pass


class StabilityPlanAddView(DefaultAddView):
    form = StabilityPlanAddForm
