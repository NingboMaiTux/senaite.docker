# -*- coding: utf-8 -*-
"""领用申请单的列表（审批队列）与详情页。"""
import collections

from bika.lims import api
from bika.lims.utils import get_link
from senaite.app.listing import ListingView
from senaite.core.api import dtime
from zope.publisher.browser import BrowserView

from maitux.stock.i18n import translate_stock
from maitux.stock.config import CONSUME_COUNTERSIGN_ROLES
from maitux.stock.usageapproval import check_approver
from maitux.stock.usageapproval import get_request_applicant
from maitux.stock.usageapproval import has_approval_role
from maitux.stock.usageapproval import is_applicant
from maitux.stock.usageapproval import to_decimal
from maitux.stock.usageapproval import validate_lines


def format_datetime(value):
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


def get_requested_total(usage_request):
    """申请总量（仅用于列表展示；不同单位时不求和，避免误导）。"""
    total = 0
    units = set()
    for line in getattr(usage_request, "lines", None) or []:
        total += to_decimal(line.get("requested_quantity"))
        units.add(api.safe_unicode(line.get("unit_title") or ""))
    if len(units) > 1:
        return u"-"
    unit = units.pop() if units else u""
    return u"{} {}".format(total.normalize(), unit).strip()


# 中文注释：状态标题也走"英文 msgid + 运行时翻译"。
# 工作流 definition.xml 里的状态标题是英文（Pending Review / Approved / ...），
# 这里按当前语言翻译；取不到工作流标题时按状态 id 兜底到同样的英文 msgid。
REVIEW_STATE_FALLBACK = {
    "draft": u"Draft",
    "submitted": u"Pending Review",
    "approved": u"Approved",
    "rejected": u"Rejected",
    "cancelled": u"Cancelled",
}


def review_state_title(usage_request):
    """返回申请单状态的（已翻译）标题。"""
    state = api.safe_unicode(api.get_review_status(usage_request) or u"")
    if not state:
        return u""
    title = u""
    workflow_tool = api.get_tool("portal_workflow")
    portal_type = getattr(usage_request, "portal_type", None)
    if workflow_tool is not None and portal_type:
        for getter_name in ("getTitleForStateOnType", "getTitleForState"):
            getter = getattr(workflow_tool, getter_name, None)
            if not callable(getter):
                continue
            try:
                if getter_name == "getTitleForStateOnType":
                    title = getter(state, portal_type)
                else:
                    title = getter(state)
            except Exception:
                continue
            if title:
                break
    if not title:
        title = REVIEW_STATE_FALLBACK.get(state, state)
    return translate_stock(api.safe_unicode(title))


class StockUsageRequestsView(ListingView):
    """领用申请单列表 —— 审批人的待办队列。"""

    def __init__(self, context, request):
        super(StockUsageRequestsView, self).__init__(context, request)

        # 中文注释：标题/列名/页签/按钮都必须是**英文 msgid + 运行时翻译**。
        # SENAITE 列表的这些文案是在 Python 里拼进 JSON 的，渲染阶段不会再翻译，
        # 所以硬编码任何一种语言都会让另一种语言显示错（见 maitux/stock/i18n.py）。
        self.title = translate_stock(u"Usage Requests")
        self.description = translate_stock(
            u"Tick one request, then approve or reject it.")
        self.catalog = "portal_catalog"
        self.show_search = True
        self.show_select_column = True
        self.contentFilter = {
            "portal_type": "StockUsageRequest",
            "sort_on": "created",
            "sort_order": "descending",
            "path": {
                "query": api.get_path(self.context),
                "depth": 1,
            },
        }
        self.context_actions = {}

        self.columns = collections.OrderedDict((
            ("request_id", {"title": translate_stock(u"Request No."),
                            "toggle": True}),
            ("applicant_fullname", {"title": translate_stock(u"Applicant"),
                                    "toggle": True}),
            ("request_date", {"title": translate_stock(u"Submitted On"),
                              "toggle": True}),
            ("requested_total", {"title": translate_stock(u"Requested"),
                                 "toggle": True}),
            ("state_title", {"title": translate_stock(u"Status"),
                             "toggle": True}),
            ("approver_fullname", {"title": translate_stock(u"Reviewer"),
                                   "toggle": True}),
            ("approve_date", {"title": translate_stock(u"Reviewed On"),
                              "toggle": True}),
        ))

        pending_transitions = [
            {"id": "approve", "title": translate_stock(u"Approve"),
             "css_class": "btn btn-success"},
            {"id": "reject", "title": translate_stock(u"Reject"),
             "css_class": "btn btn-danger"},
        ]
        applicant_transitions = [
            {"id": "retract", "title": translate_stock(u"Withdraw"),
             "css_class": "btn btn-outline-secondary"},
        ]

        self.review_states = [
            {
                # 中文注释：SENAITE 列表**强制要求**存在 id="default" 的页签，
                # 否则渲染时会报 "review_states does not contain id='default'" 并 500。
                # 这里就把默认页签做成"待审核"队列。
                "id": "default",
                "title": translate_stock(u"Pending Review"),
                "contentFilter": {"review_state": "submitted"},
                "transitions": pending_transitions + applicant_transitions,
                "columns": list(self.columns.keys()),
            }, {
                "id": "approved",
                "title": translate_stock(u"Approved"),
                "contentFilter": {"review_state": "approved"},
                "transitions": [],
                "columns": list(self.columns.keys()),
            }, {
                "id": "rejected",
                "title": translate_stock(u"Rejected"),
                "contentFilter": {"review_state": "rejected"},
                "transitions": [],
                "columns": list(self.columns.keys()),
            }, {
                "id": "all",
                "title": translate_stock(u"All"),
                "contentFilter": {},
                "transitions": [],
                "columns": list(self.columns.keys()),
            }
        ]

    def folderitem(self, obj, item, index):
        item = super(StockUsageRequestsView, self).folderitem(obj, item, index)
        obj = api.get_object(obj)

        item["request_id"] = api.safe_unicode(
            getattr(obj, "request_id", "") or api.get_title(obj))
        item["applicant_fullname"] = api.safe_unicode(
            getattr(obj, "applicant_fullname", "")
            or get_request_applicant(obj))
        item["request_date"] = format_datetime(getattr(obj, "request_date", None))
        item["requested_total"] = get_requested_total(obj)
        item["state_title"] = review_state_title(obj)
        item["approver_fullname"] = api.safe_unicode(
            getattr(obj, "approver_fullname", "") or "")
        item["approve_date"] = format_datetime(getattr(obj, "approve_date", None))
        item["replace"]["request_id"] = get_link(
            href=api.get_url(obj),
            value=item["request_id"] or api.get_title(obj),
            csrf=False,
        )
        return item


class StockUsageRequestView(BrowserView):
    """申请单详情页：单据、明细、审批轨迹、可用动作。"""

    def get_request_id(self):
        return api.safe_unicode(
            getattr(self.context, "request_id", "") or api.get_title(self.context))

    def context_uid(self):
        return api.get_uid(self.context)

    def container_url(self):
        parent = getattr(self.context, "aq_parent", None)
        return api.get_url(parent) if parent is not None else api.get_url(api.get_portal())

    def state_title(self):
        """当前状态的展示名（取工作流定义里的 title，已做 i18n）。"""
        state = api.get_review_status(self.context)
        try:
            workflow = api.get_tool("portal_workflow")
            for definition in workflow.getWorkflowsFor(self.context) or []:
                state_obj = definition.states.get(state)
                if state_obj is not None and state_obj.title:
                    return api.safe_unicode(state_obj.title)
        except Exception:
            pass
        return api.safe_unicode(state or "")

    def applicant_display(self):
        fullname = api.safe_unicode(
            getattr(self.context, "applicant_fullname", "") or "")
        applicant = get_request_applicant(self.context)
        if fullname and applicant:
            return u"{} ({})".format(fullname, applicant)
        return fullname or applicant or u"-"

    def reviewer_display(self):
        fullname = api.safe_unicode(
            getattr(self.context, "approver_fullname", "") or "")
        approver = api.safe_unicode(getattr(self.context, "approver", "") or "")
        if fullname and approver:
            return u"{} ({})".format(fullname, approver)
        return fullname or approver or u"-"

    def purpose_display(self):
        return api.safe_unicode(getattr(self.context, "purpose", "") or u"")

    def rejection_reason(self):
        return api.safe_unicode(
            getattr(self.context, "approve_comment", "") or u"")

    def step_title(self, step):
        return {
            u"submit": u"Submit for Review",
            u"approve": u"Approve",
            u"reject": u"Reject",
        }.get(api.safe_unicode(step or ""), api.safe_unicode(step or ""))

    def get_lines(self):
        rows = []
        for line in getattr(self.context, "lines", None) or []:
            uid = api.safe_unicode(line.get("batch_uid") or "")
            batch = api.get_object_by_uid(uid, default=None) if uid else None
            rows.append({
                "batch_id": api.safe_unicode(line.get("batch_id") or ""),
                "stock_title": api.safe_unicode(line.get("stock_title") or ""),
                "unit_title": api.safe_unicode(line.get("unit_title") or ""),
                "quantity": api.safe_unicode(
                    to_decimal(line.get("requested_quantity"))),
                "remarks": api.safe_unicode(line.get("remarks") or ""),
                "batch_url": api.get_url(batch) if batch is not None else u"",
            })
        return rows

    def get_signature_trail(self):
        rows = []
        for row in getattr(self.context, "signature_log", None) or []:
            countersigner = api.safe_unicode(row.get("countersigner") or "")
            rows.append({
                "step": api.safe_unicode(row.get("step") or ""),
                "signer": api.safe_unicode(row.get("signer") or ""),
                "signer_fullname": api.safe_unicode(
                    api.get_user_fullname(row.get("signer")) or ""),
                "countersigner": countersigner,
                "countersigner_fullname": api.safe_unicode(
                    api.get_user_fullname(countersigner) or "") if countersigner
                else u"",
                "require_countersign": bool(row.get("require_countersign")),
                "meaning": api.safe_unicode(row.get("meaning") or ""),
                "reason": api.safe_unicode(row.get("reason") or ""),
                "signed_at": format_datetime(row.get("signed_at")),
            })
        return rows

    def get_request_date(self):
        return format_datetime(getattr(self.context, "request_date", None))

    def get_approve_date(self):
        return format_datetime(getattr(self.context, "approve_date", None))

    def current_user_id(self):
        user = api.get_current_user()
        return user.getId() if user else u""

    def review_state(self):
        return api.safe_unicode(api.get_review_status(self.context) or u"")

    def can_approve(self):
        """是否显示审核/驳回按钮。

        刻意**不用** ``api.get_transitions_for()``：它会去求值工作流的
        guard 表达式，而 ``guard_handler`` 是 skins 里的脚本，在非标准遍历的
        视图里可能取不到（本仓库 esignature 为此专门做了 ensure_workflow_skin）。
        取不到时会抛异常、列表为空，表现为"审核人看不到按钮"。

        这里直接用自己的业务规则判断；真正的安全底线仍然在工作流守卫
        （maitux.stock.guards）里，绕不过去。
        """
        if self.review_state() != "submitted":
            return False
        return not check_approver(self.context, self.current_user_id())

    def can_withdraw(self):
        return (self.review_state() == "submitted"
                and is_applicant(self.context, self.current_user_id()))

    def can_submit(self):
        """草稿 + 申请人本人：给一个"提交审核"的兜底入口。

        正常路径下申请单在领用页创建时就已经提交进入待审核，
        这里只用于"创建成功但提交失败、留成草稿"时的补救。
        发起领用不需要电子签名，所以这个按钮点了就直接提交。
        """
        if self.review_state() != "draft":
            return False
        return is_applicant(self.context, self.current_user_id())

    def approve_blockers(self):
        """审核前的前置提示：明细已不可扣减时给出明确原因。"""
        if not self.can_approve():
            return []
        return [
            u"{}: {}".format(label, message)
            for label, message in validate_lines(
                list(getattr(self.context, "lines", None) or []))
        ]

    def approval_roles_hint(self):
        return u"、".join(sorted(CONSUME_COUNTERSIGN_ROLES))
