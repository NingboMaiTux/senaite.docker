# -*- coding: utf-8 -*-
import collections

from bika.lims import api
from bika.lims.utils import get_link
from senaite.app.listing import ListingView
from senaite.core.api import dtime
from decimal import Decimal

from maitux.stock.i18n import translate_stock
from maitux.stock.expiryreminder import get_batch_reminder
from maitux.stock.expiryreminder import reminder_badge_html
from maitux.stock.browser.stockbatchactions import ACTION_CONSUME
from maitux.stock.browser.stockbatchactions import ACTION_DESTROY
from maitux.stock.browser.stockbatchactions import ACTION_PRINT
from maitux.stock.browser.stockbatchactions import ACTION_RETURN
from maitux.stock.browser.stockbatchactions import ACTION_REVIEW_USAGE
from maitux.stock.browser.stockbatchactions import ACTION_SPLIT
from maitux.stock.browser.stockbatchactions import ACTION_STOCKTAKE
from maitux.stock.browser.stockbatchactions import get_allowed_action_ids_for_batches
from maitux.stock.browser.stockbatchactions import get_transition_items_for_action_ids
from maitux.stock.browser.stockbatchactions import get_transition_items_for_batch
from maitux.stock.stockbatchexpiry import REVIEW_STATE_EXPIRED
from maitux.stock.stockbatchexpiry import is_due_for_expiry
from maitux.stock.usageapproval import check_approver
from maitux.stock.usageapproval import find_pending_requests
from maitux.stock.usageapproval import find_pending_requests_for_batch


def is_batch_visible_in_tab(batch, review_state_id, now=None):
    """判断批次在当前页签下是否应该显示。"""
    # 中文注释：Active 页签除了看工作流状态外，还要额外隐藏“已到期但尚未同步为 expired”的批次。
    if review_state_id == "default" and is_due_for_expiry(batch, now=now):
        return False
    return True


def should_show_select_for_batch(review_state_id, status):
    """判断当前批次在页签中是否显示复选框。"""
    # 中文注释：All 页签只负责汇总展示，是否允许执行具体操作交给后端动作校验，
    # 前端不再对某些状态单独隐藏复选框，避免同页签下出现“有的能选、有的不能选”的不一致表现。
    return True


class StockBatchesView(ListingView):
    def __init__(self, context, request):
        super(StockBatchesView, self).__init__(context, request)

        self.title = translate_stock(u"Stock Batches")
        self.catalog = "portal_catalog"
        self.show_search = True
        self.contentFilter = {
            "portal_type": "StockBatch",
            "sort_on": "created",
            "sort_order": "descending",
            "path": {
                "query": api.get_path(self.context),
                "depth": 1,
            },
        }
        self.context_actions = {
            u"Add": {
                "url": "++add++StockBatch",
                "permission": "cmf.AddPortalContent",
                "icon": "senaite_theme/icon/plus",
            }
        }
        self.show_select_column = True

        self.columns = collections.OrderedDict((
            ("batch_id", {"title": u"Batch ID", "toggle": True}),
            ("stock", {"title": u"Stock", "toggle": True}),
            ("supplier", {"title": u"Supplier", "toggle": True}),
            ("current_amount", {"title": u"Current Amount", "toggle": True}),
            ("target_quantity", {"title": u"Target Quantity", "toggle": True}),
            ("unit", {"title": u"Unit", "toggle": True}),
            ("expiry_date", {"title": u"Expiry Date", "toggle": True}),
            ("created_by", {"title": u"Created By", "toggle": True, "index": "Creator"}),
            ("created_date", {"title": u"Created Date", "toggle": True, "index": "created"}),
            ("status", {"title": u"Status", "toggle": True}),
            ("pending_request", {"title": u"Pending Request", "toggle": True}),
        ))

        self.review_states = [
            {
                "id": "pending_review",
                "title": u"Pending Review",
                "contentFilter": {"review_state": "active"},
                "transitions": get_transition_items_for_action_ids([
                    ACTION_REVIEW_USAGE,
                ]),
                "columns": list(self.columns.keys()),
            }, {
                "id": "default",
                "title": u"Active",
                "contentFilter": {"review_state": "active"},
                "transitions": get_transition_items_for_action_ids([
                    ACTION_CONSUME,
                    ACTION_SPLIT,
                    ACTION_RETURN,
                    ACTION_STOCKTAKE,
                    ACTION_DESTROY,
                    ACTION_PRINT,
                ]),
                "columns": list(self.columns.keys()),
            }, {
                "id": "expired",
                "title": u"Expired",
                "contentFilter": {"review_state": REVIEW_STATE_EXPIRED},
                "transitions": get_transition_items_for_action_ids([
                    ACTION_DESTROY,
                    ACTION_PRINT,
                ]),
                "columns": list(self.columns.keys()),
            }, {
                "id": "destroyed",
                "title": u"Destroyed",
                "contentFilter": {"review_state": "destroyed"},
                "transitions": get_transition_items_for_action_ids([
                    ACTION_PRINT,
                ]),
                "columns": list(self.columns.keys()),
            }, {
                "id": "all",
                "title": u"All",
                "contentFilter": {},
                "transitions": [],
                "columns": list(self.columns.keys()),
            }
        ]

    # ------------------------------------------------------------------
    # 待审核领用申请（审核入口在批次这一侧）
    # ------------------------------------------------------------------
    def pending_requests_map(self):
        """{batch_uid: [StockUsageRequest, ...]}；整个请求内只查一次目录。"""
        cached = getattr(self, "_pending_map_cache", None)
        if cached is None:
            cached = find_pending_requests()
            self._pending_map_cache = cached
        return cached

    def pending_requests_for(self, batch):
        uid = api.safe_unicode(api.get_uid(batch) or "").strip()
        if not uid:
            return []
        return self.pending_requests_map().get(uid) or []

    def reviewable_request_for(self, batch):
        """当前用户可以审核的那条待审核申请（没有则 None）。

        "可以审核" = 非申请人 + 具备审批角色（同一套规则见 usageapproval.check_approver）。
        """
        user = api.get_current_user()
        user_id = user.getId() if user else u""
        requests = sorted(self.pending_requests_for(batch),
                          key=lambda item: api.get_creation_date(item) or 0)
        for request in requests:
            if not check_approver(request, user_id):
                return request
        return None

    def item_has_pending_request(self, item):
        obj = item.get("obj")
        if obj is None:
            return False
        batch = api.get_object(obj)
        return bool(self.pending_requests_for(batch))

    def get_review_action_items(self, batches):
        """有待本人审核的申请时给出"审核领用"按钮（仅单选）。

        电子签名一次只能签一个对象（esignature 的限制），所以限定单选，
        多选时不给这个按钮，避免点了之后被后端拒绝。
        """
        if len(batches) != 1:
            return []
        if self.reviewable_request_for(batches[0]) is None:
            return []
        return get_transition_items_for_action_ids([ACTION_REVIEW_USAGE])

    def get_allowed_transitions_for(self, uids):
        """返回当前勾选批次可显示的批量动作按钮。"""
        if not uids:
            return []

        batches = []
        for uid in uids:
            batch = api.get_object_by_uid(uid, default=None)
            if batch is None:
                continue
            batches.append(batch)
        if not batches:
            return []

        action_ids = get_allowed_action_ids_for_batches(batches)

        # 中文注释：新版 listing 会按当前页签的 transitions 继续做一次白名单过滤，
        # 这里提前对齐该规则，确保各页签按钮与 All 页签的动态交集结果一致。
        allowed_ids = [
            item.get("id") for item in self.review_state.get("transitions", [])
            if item.get("id")
        ]
        if allowed_ids:
            action_ids = [action_id for action_id in action_ids if action_id in allowed_ids]

        items = get_transition_items_for_action_ids(action_ids)

        # 中文注释：审核动作与批次状态无关（取决于有没有待审核的申请），
        # 所以单独追加、并排在最前面；同时去重以免在"待审核"页签里出现两个。
        review_items = self.get_review_action_items(batches)
        if review_items:
            review_ids = set(item.get("id") for item in review_items)
            items = review_items + [i for i in items if i.get("id") not in review_ids]
        return items

    def get_catalog_query(self, **kw):
        query = super(StockBatchesView, self).get_catalog_query(**kw)
        searchterm = kw.get("searchterm", "") or self.request.get("searchterm", "") or ""
        searchterm = api.safe_unicode(searchterm).strip()
        if searchterm:
            query["Title"] = searchterm
        return query

    def folderitems(self):
        items = super(StockBatchesView, self).folderitems()
        review_state_id = self.review_state.get("id", "")

        # 中文注释："待审核"页签只显示"有待审核领用申请"的批次。
        # 目录里没有对应索引（lines 是对象内 DataGrid），所以在这里做内存过滤。
        if review_state_id == "pending_review":
            return [item for item in items
                    if self.item_has_pending_request(item)]

        if review_state_id != "default":
            return items

        visible_items = []
        for item in items:
            batch = item.get("obj")
            if batch is None:
                visible_items.append(item)
                continue
            batch = api.get_object(batch)
            if not is_batch_visible_in_tab(batch, review_state_id):
                continue
            visible_items.append(item)
        return visible_items

    def _first_uid(self, value):
        if not value:
            return ""
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        value = api.safe_unicode(value)
        parts = value.splitlines()
        return parts[0] if parts else ""

    def _format_dt(self, value):
        if not value:
            return ""
        try:
            ansi = dtime.to_ansi(value, show_time=True)
            if not ansi:
                return ""
            return "{}-{}-{} {}:{}:{}".format(
                ansi[0:4], ansi[4:6], ansi[6:8],
                ansi[8:10], ansi[10:12], ansi[12:14],
            )
        except Exception:
            return ""

    def _format_amount(self, value):
        try:
            val = Decimal(value)
            # Ensure "0.00" is shown, not empty
            return "{:.2f}".format(val)
        except Exception:
            return "{}".format(value if value is not None else "0")

    def folderitem(self, obj, item, index):
        item = super(StockBatchesView, self).folderitem(obj, item, index)
        obj = api.get_object(obj)
        current_state_id = self.review_state.get("id", "")

        batch_id = getattr(obj, "batch_id", "") or ""
        item["batch_id"] = batch_id

        stock_uid = self._first_uid(getattr(obj, "stock", "") or "")
        stock = api.get_object_by_uid(stock_uid, default=None) if stock_uid else None
        item["stock"] = api.get_title(stock) if stock else ""

        supplier_uid = self._first_uid(getattr(obj, "supplier", "") or "")
        supplier = api.get_object_by_uid(supplier_uid, default=None) if supplier_uid else None
        item["supplier"] = api.get_title(supplier) if supplier else ""

        item["current_amount"] = self._format_amount(getattr(obj, "current_amount", None))
        item["target_quantity"] = self._format_amount(getattr(obj, "target_quantity", None))

        unit_uid = self._first_uid(getattr(obj, "unit", "") or "")
        unit = api.get_object_by_uid(unit_uid, default=None) if unit_uid else None
        item["unit"] = api.get_title(unit) if unit else ""

        expiry = getattr(obj, "expiry_date", None)
        item["expiry_date"] = self._format_dt(expiry) if expiry else ""

        # 中文注释：到期提醒着色 —— 已过期红色、到期前 N 天黄色（N 配置在 Stock 上）。
        # 行 CSS class 走 SENAITE 列表的 item["state_class"]（它会拼到 <tr class="...">），
        # 样式见 browser/static/expiry-reminder.css。
        reminder = get_batch_reminder(obj, stock=stock)
        if reminder.get("row_class"):
            state_class = api.safe_unicode(item.get("state_class") or u"").strip()
            item["state_class"] = u"{} {}".format(
                state_class, reminder["row_class"]).strip()
        badge = reminder_badge_html(reminder)
        if badge:
            item["after"]["expiry_date"] = badge

        item["status"] = api.get_review_status(obj) or ""
        item["transitions"] = get_transition_items_for_batch(obj)

        # 中文注释：待审核领用申请 —— 列表里显示申请单号（可点），
        # 并且当"本人有权审核"时在行内补一个"审核领用"按钮。
        pending = self.pending_requests_for(obj)
        if pending:
            request = pending[0]
            request_id = api.safe_unicode(
                getattr(request, "request_id", "") or api.get_title(request))
            item["pending_request"] = get_link(
                href=api.get_url(request),
                value=request_id,
                csrf=False,
            )
            if self.reviewable_request_for(obj) is not None:
                item["transitions"] = get_transition_items_for_action_ids(
                    [ACTION_REVIEW_USAGE]) + list(item["transitions"])
        else:
            item["pending_request"] = ""

        if not should_show_select_for_batch(current_state_id, item["status"]):
            item["disabled"] = True
            item["show_select"] = False

        created_by = getattr(obj, "created_by", "") or ""
        if not created_by:
            try:
                created_by = obj.Creator()
            except Exception:
                created_by = ""
        item["created_by"] = created_by

        created_dt = getattr(obj, "created_date", None)
        if not created_dt:
            try:
                created_dt = obj.created()
            except Exception:
                created_dt = None
        item["created_date"] = self._format_dt(created_dt) if created_dt else ""

        item["replace"]["batch_id"] = get_link(
            href=api.get_url(obj),
            value=batch_id or api.get_title(obj),
            csrf=False,
        )

        return item
