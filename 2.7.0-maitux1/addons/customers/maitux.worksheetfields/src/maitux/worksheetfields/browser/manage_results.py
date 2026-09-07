# -*- coding: utf-8 -*-
"""maitux.worksheetfields —— Worksheet 结果录入页（manage_results）覆盖视图

在 maitux.instrument_acquisition 的 ManageResultsView（其继承
reviewerassignment → senaite.core）基础上：

- 模板隐藏原『仪器』单选下拉与『仪器采集/进入采集』入口；
- 页头新增两个「弹层搜索式」引用选择器（仅作记录，不自动分配到每个分析）：
  1. 仪器（新字段 `instruments`，多值 UID 引用，类型 Instrument）
  2. 库存批次（新字段 `stock_batches`，多值 UID 引用，类型 StockBatch，
     来自 maitux.stock 模块）
- 点击页头按钮弹出搜索弹层 → 勾选/搜索/全选 → 点「确定」一次性保存
  （整页 POST 刷新；状态消息经 MessageFactory 支持中英双语）。
"""

import json

import six
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from bika.lims import api
from senaite.core.catalog import SETUP_CATALOG

from maitux.instrument_acquisition.browser.worksheet.manage_results import (
    ManageResultsView as InstrumentAcquisitionManageResultsView,
)

from maitux.worksheetfields import worksheetfieldsMessageFactory as _
from maitux.worksheetfields.behaviors.worksheet import (
    get_worksheet_instruments,
    set_worksheet_instruments,
    get_worksheet_stock_batches,
    set_worksheet_stock_batches,
)
from maitux.worksheetfields.config import (
    INSTRUMENT_PORTAL_TYPE,
    STOCK_BATCH_PORTAL_TYPE,
)


class ManageResultsView(InstrumentAcquisitionManageResultsView):
    """Worksheet 结果录入页（多选仪器/库存批次版）"""

    template = ViewPageTemplateFile("templates/manage_results.pt")

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------

    def __call__(self):
        form = self.request.form
        if self.request.method == "POST" and (
                "worksheet_instruments" in form
                or "worksheet_stock_batches" in form):
            self.handle_save_worksheet_resources(form)
        return super(ManageResultsView, self).__call__()

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------

    def handle_save_worksheet_resources(self, form):
        """处理多选仪器/库存批次表单提交"""
        if not self.is_assignment_allowed():
            message = _(
                u"save_worksheet_resources_not_allowed",
                default=u"Worksheet instruments and stock batches can only "
                        u"be edited while the worksheet is open.",
            )
            self.add_status_message(message, "warning")
            return

        changed = False
        instruments_saved = False
        batches_saved = False
        if "worksheet_instruments" in form:
            uids = self.filter_uids(form.get("worksheet_instruments"),
                                    INSTRUMENT_PORTAL_TYPE)
            try:
                set_worksheet_instruments(self.context, uids)
                changed = True
                instruments_saved = True
            except Exception:
                self.log_exception()

        if "worksheet_stock_batches" in form:
            uids = self.filter_uids(form.get("worksheet_stock_batches"),
                                    STOCK_BATCH_PORTAL_TYPE)
            try:
                set_worksheet_stock_batches(self.context, uids)
                changed = True
                batches_saved = True
            except Exception:
                self.log_exception()

        if changed:
            self.context.reindexObject()
            if instruments_saved and batches_saved:
                message = _(
                    u"worksheet_resources_saved",
                    default=u"Worksheet instruments and stock batches saved.",
                )
            elif instruments_saved:
                message = _(
                    u"worksheet_instruments_saved",
                    default=u"Worksheet instruments saved.",
                )
            else:
                message = _(
                    u"worksheet_stock_batches_saved",
                    default=u"Worksheet stock batches saved.",
                )
            self.add_status_message(message, "info")

    def filter_uids(self, value, portal_type):
        """过滤出指定 portal_type 的合法 UID 列表（去重）

        兼容两种提交形态：多值表单列表，或前端以逗号拼接的字符串。
        """
        if isinstance(value, six.string_types):
            values = api.safe_unicode(value).split(u",")
        else:
            values = api.to_list(value) if value else []
        uids = []
        for item in values:
            uid = api.safe_unicode(item).strip() if item else u""
            if not uid or uid in uids:
                continue
            obj = api.get_object_by_uid(uid, None)
            if obj is None:
                continue
            if api.get_portal_type(obj) != portal_type:
                continue
            uids.append(uid)
        return uids

    # ------------------------------------------------------------------
    # 下拉选项
    # ------------------------------------------------------------------

    def get_instrument_options(self):
        """所有激活仪器 (uid, title)；含已选中但已停用的仪器"""
        items = []
        brains = api.search({
            "portal_type": INSTRUMENT_PORTAL_TYPE,
            "is_active": True,
            "sort_on": "sortable_title",
            "sort_order": "ascending",
        }, catalog=SETUP_CATALOG)
        for brain in brains:
            items.append((brain.UID, api.safe_unicode(brain.Title)))
        return self.ensure_selected_in_options(
            items, self.get_selected_instrument_uids())

    def get_stock_batch_options(self):
        """全部 StockBatch（含已过期/销毁）(uid, label)

        label 优先显示批次号（batch_id），并附物料（Stock）标题便于区分。
        """
        items = []
        brains = api.search({
            "portal_type": STOCK_BATCH_PORTAL_TYPE,
            "sort_on": "sortable_title",
            "sort_order": "ascending",
        })
        for brain in brains:
            obj = api.get_object_by_uid(brain.UID, None)
            if obj is None:
                continue
            items.append((brain.UID, self.get_batch_label(obj)))
        return self.ensure_selected_in_options(
            items, self.get_selected_stock_batch_uids())

    def ensure_selected_in_options(self, items, selected_uids):
        """确保已选项即使不在常规查询结果中也出现在下拉中"""
        known = [item[0] for item in items]
        for uid in selected_uids:
            if uid in known:
                continue
            obj = api.get_object_by_uid(uid, None)
            if obj is None:
                continue
            title = api.safe_unicode(api.get_title(obj) or api.get_id(obj))
            items.append((uid, title))
        return items

    # ------------------------------------------------------------------
    # 已选项
    # ------------------------------------------------------------------

    def get_selected_instrument_uids(self):
        """当前已选仪器 UID 列表"""
        try:
            return get_worksheet_instruments(self.context)
        except Exception:
            return []

    def get_selected_stock_batch_uids(self):
        """当前已选库存批次 UID 列表"""
        try:
            return get_worksheet_stock_batches(self.context)
        except Exception:
            return []

    def _selected_instrument_titles(self):
        """当前已选仪器标题列表"""
        titles = []
        for uid in self.get_selected_instrument_uids():
            obj = api.get_object_by_uid(uid, None)
            if obj is None:
                continue
            title = api.safe_unicode(api.get_title(obj) or api.get_id(obj))
            titles.append(title)
        return titles

    def get_selected_instrument_titles(self):
        """已选仪器标题（只读展示，逗号分隔）"""
        return u", ".join(self._selected_instrument_titles())

    def _selected_stock_batch_labels(self):
        """当前已选库存批次标签列表"""
        labels = []
        for uid in self.get_selected_stock_batch_uids():
            obj = api.get_object_by_uid(uid, None)
            if obj is None:
                continue
            labels.append(self.get_batch_label(obj))
        return labels

    def get_selected_stock_batch_labels(self):
        """已选库存批次标签（只读展示，逗号分隔）"""
        return u", ".join(self._selected_stock_batch_labels())

    # ------------------------------------------------------------------
    # 弹层搜索选择器：选项/已选 JSON + 触发按钮摘要
    # ------------------------------------------------------------------

    # 弹层单次最多渲染的行数（其余靠关键字过滤）
    MAX_PICKER_SHOWN = 300

    def get_instruments_json(self):
        """仪器选项 JSON（供弹层渲染）: [{"uid": ..., "title": ...}, ...]"""
        items = [{"uid": api.safe_unicode(uid),
                  "title": api.safe_unicode(title)}
                 for uid, title in self.get_instrument_options()]
        return json.dumps(items)

    def get_stock_batches_json(self):
        """库存批次选项 JSON（含全部状态，供弹层渲染）"""
        items = [{"uid": api.safe_unicode(uid),
                  "title": api.safe_unicode(label)}
                 for uid, label in self.get_stock_batch_options()]
        return json.dumps(items)

    def get_selected_instrument_uids_json(self):
        """当前已选仪器 UID JSON（弹层预勾选）"""
        return json.dumps(
            [api.safe_unicode(uid)
             for uid in self.get_selected_instrument_uids()])

    def get_selected_stock_batch_uids_json(self):
        """当前已选库存批次 UID JSON（弹层预勾选）"""
        return json.dumps(
            [api.safe_unicode(uid)
             for uid in self.get_selected_stock_batch_uids()])

    def get_instruments_hint(self):
        """仪器弹层“结果过多”提示（JSON 字符串，供 JS 直接使用）"""
        total = len(self.get_instrument_options())
        return json.dumps(self.picker_hint(total))

    def get_stock_batches_hint(self):
        """批次弹层“结果过多”提示（JSON 字符串，供 JS 直接使用）"""
        total = len(self.get_stock_batch_options())
        return json.dumps(self.picker_hint(total))

    def picker_hint(self, total):
        """超过单次渲染上限时返回提示文本，否则空串"""
        if total <= self.MAX_PICKER_SHOWN:
            return u""
        return self.translate_message(_(
            u"wsf_more_results_hint",
            default=u"Showing the first ${shown} of ${total} results. "
                    u"Type to filter.",
            mapping={
                "shown": self.MAX_PICKER_SHOWN,
                "total": total,
            },
        ))

    def get_instruments_summary(self):
        """仪器触发按钮摘要文本（可翻译）"""
        return self.summary_text(
            self.get_selected_instrument_uids(),
            self._selected_instrument_titles(),
            u"Select instruments",
            u"wsf_instruments_count_summary",
            u"${count} instruments selected")

    def get_stock_batches_summary(self):
        """库存批次触发按钮摘要文本（可翻译）"""
        return self.summary_text(
            self.get_selected_stock_batch_uids(),
            self._selected_stock_batch_labels(),
            u"Select stock batches",
            u"wsf_stock_batches_count_summary",
            u"${count} stock batches selected")

    def summary_text(self, uids, titles, empty_msgid, count_msgid,
                     count_default):
        """按钮摘要：未选 -> 提示文案；<=2 项 -> 直接列名称；多 -> N 项已选

        全部可翻译；返回 unicode。
        """
        if not uids:
            return self.translate_message(_(empty_msgid))
        if len(uids) <= 2:
            return u", ".join(titles)
        return self.translate_message(_(
            count_msgid,
            default=count_default,
            mapping={"count": len(uids)},
        ))

    def translate_message(self, msg):
        """把 i18n 消息翻译为当前请求语言的 unicode 文本

        直接用 zope.i18n.translate：能识别 Message 自带的 domain / mapping /
        default（不能先经 api.safe_unicode，那会丢 domain/mapping）。
        """
        from zope.i18n import translate as ztranslate
        translated = ztranslate(msg, context=self.request)
        return api.safe_unicode(translated)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def get_batch_label(self, obj):
        """批次显示文本：批次号 - 物料名（缺失时降级）"""
        batch_id = getattr(obj, "batch_id", "") or u""
        batch_id = api.safe_unicode(batch_id)
        title = api.safe_unicode(api.get_title(obj) or u"")
        label = batch_id or title
        stock_title = self.get_batch_stock_title(obj)
        if label and stock_title:
            return u"%s - %s" % (label, stock_title)
        return label or stock_title or api.get_uid(obj)

    def get_batch_stock_title(self, obj):
        """批次关联的物料（Stock）标题"""
        raw = getattr(obj, "stock", "") or u""
        uid = raw
        if isinstance(raw, (list, tuple)):
            uid = raw[0] if raw else u""
        if isinstance(uid, (list, tuple)):
            uid = uid[0] if uid else u""
        stock = api.get_object_by_uid(uid, None) if uid else None
        if stock is None:
            return u""
        return api.safe_unicode(api.get_title(stock) or u"")

    def log_exception(self):
        """记录异常但不中断渲染"""
        from senaite.core import logger
        logger.exception(
            "maitux.worksheetfields: failed to save worksheet resources "
            "for %s", api.get_path(self.context))
