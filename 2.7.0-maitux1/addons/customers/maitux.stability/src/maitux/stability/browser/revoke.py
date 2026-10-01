# -*- coding: utf-8 -*-
"""阶段 4：「撤销登样」页面。

为什么必须有它（开发计划 §8.1）：选了 A 方案（登样成功 → 行置「进行中」）之后，
行就**受删除保护**，而 `detail_status` 在表单里是隐藏字段 —— 于是"误登的样"
在界面上没有任何退路（只能进 ZMI 改数据）。这个页面就是那条退路。

口径：

* **单个行级动作**（一次一行，避免批量点错）；
* 撤销**必须填原因**（GMP：撤销要能解释），服务端也校验（不只靠前端 required）；
* 「已完成」的行**不允许撤销**（完成是最终结果）；
* **不删样品对象** —— 只解除"方案明细行 ↔ 样品"的关联；页面明确提示
  "样品仍在，如需作废请到样品页处理"，并给出样品链接；
* 权限：与自动登样同一个管理权限（`ManageSampleAutomation`）。
"""

from bika.lims import api
from bika.lims.api.security import check_permission
from plone import api as ploneapi
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from maitux.stability import automation
from maitux.stability import plan_status
from maitux.stability import sampleautomation as sa
from maitux.stability import samplegeneration as sg
from maitux.stability.browser.rowids import parse_row_id
from maitux.stability.browser.rowids import selected_row_ids
from maitux.stability.browser.rowids import submitted_detail_uids
from maitux.stability.i18n import translate_stability
from maitux.stability.permissions import ManageSampleAutomation
from maitux.stability.permissions import permission_name
from maitux.stability.timepoints import get_row_uid
from maitux.stability.timepoints import normalize_months
from maitux.stability.timepoints import normalize_status
from maitux.stability.title import localized_task_title

# 结果码 -> 文案（msgid；服务端只给码，界面按语言取文案）
REVOKE_MESSAGES = {
    sa.REVOKE_OK: u"Sample registration revoked for {plan} / {task}.",
    sa.REVOKE_UNKNOWN_ROW: u"The selected timepoint no longer exists.",
    sa.REVOKE_ROW_CHANGED: u"The plan details changed since this page was opened. "
                           u"Please open the page again.",
    sa.REVOKE_NOTHING_TO_REVOKE: u"This timepoint has no sample registered, "
                                 u"so there is nothing to revoke.",
    sa.REVOKE_COMPLETED: u"This timepoint is completed: its sample registration "
                         u"cannot be revoked any more.",
    sa.REVOKE_REASON_REQUIRED: u"A reason is required to revoke a sample "
                               u"registration.",
    # 阶段 6a：方案被暂停 / 终止 -> 撤销也被拒（与登样 / 关联 / 放置同一道门）。
    # ★ 文案与 browser/zeropoint.LINK_MESSAGES / browser/edit.py 的 _BLOCK_MESSAGES
    #   逐字一致：同一个事实不能在四个页面上有四种说法。
    #   （2026-09-30 补：此前这两条缺失，写库被拒时页面只能把原因**码**
    #    `plan_terminated` 直接显示出来。）
    plan_status.BLOCK_PLAN_PAUSED: u"This stability plan is paused. "
                                   u"All operations on it are frozen.",
    plan_status.BLOCK_PLAN_TERMINATED: u"This stability plan is terminated.",
    sg.RESULT_ERROR: u"Revoking the sample registration failed.",
}

STATUS_TITLES = {
    "pending_placement": u"Pending Placement",
    "placed": u"Placed",
    "active": u"In Progress",
    "completed": u"Completed",
}


def us(value):
    return api.safe_unicode(value) if value is not None else u""


class RevokeSampleView(BrowserView):
    """``@@revoke_sample``：撤销某一行的登样（行级动作 + 必填原因）。"""

    template = ViewPageTemplateFile("templates/revoke_sample.pt")

    row_ids = []
    target = None
    problem = u""
    revoked = None

    def __call__(self):
        if not self.can_manage():
            ploneapi.portal.show_message(
                message=translate_stability(
                    u"You do not have permission to revoke sample "
                    u"registrations."),
                request=self.request, type="error")
            return self.request.response.redirect(self.get_back_url())

        form = getattr(self.request, "form", {}) or {}
        self.row_ids = selected_row_ids(self.request)
        self.submitted_uids = submitted_detail_uids(self.request)
        self.target = self.get_target()

        if form.get("button_cancel"):
            return self.request.response.redirect(self.get_back_url())

        if form.get("button_revoke"):
            handled = self.handle_revoke()
            if handled is not None:
                return handled

        return self.template()

    # ------------------------------------------------------------------ helpers
    def can_manage(self):
        # 权限名先解析成 Zope 真正认的 title 形式，理由见 permissions.py 模块注释
        if check_permission(permission_name(ManageSampleAutomation), self.context):
            return True
        try:
            user = ploneapi.user.get_current()
            return "Manager" in set(user.getRolesInContext(self.context))
        except Exception:
            return False

    def get_back_url(self):
        return "{0}/@@task_board".format(api.get_url(self.context))

    def row_id(self):
        return self.row_ids[0] if self.row_ids else u""

    def get_target(self):
        """把选中的那一行整理成页面要显示的信息（不写库）。"""
        if not self.row_ids:
            self.problem = translate_stability(
                u"No plan details selected.")
            return None
        if len(self.row_ids) > 1:
            # 一次一行：避免一次点错撤掉一批（要批量得先明确需求）
            self.problem = translate_stability(
                u"Please select exactly one timepoint to revoke.")
            return None

        row_id = self.row_ids[0]
        plan_uid, seq = parse_row_id(row_id)
        if plan_uid is None:
            self.problem = translate_stability(
                u"The selected timepoint no longer exists.")
            return None
        plan = api.get_object_by_uid(plan_uid, None)
        if plan is None or api.get_portal_type(plan) != "StabilityPlan":
            self.problem = translate_stability(
                u"The selected timepoint no longer exists.")
            return None
        # ★ 2026-09-30（用户报的"终止了还能操作"）：页面也要按方案状态先拦一道。
        #   服务端 `revoke_sample_from_row` 本来就会拒，但页面此前照样给提交按钮，
        #   用户填完原因点提交才被弹回来。判据与写库路径同一处
        #   （samplegeneration.plan_block_reason -> automation.can_modify_plan）。
        blocked = sg.plan_block_reason(plan)
        if blocked:
            self.problem = translate_stability(
                REVOKE_MESSAGES.get(blocked, blocked))
            return None
        details = list(getattr(plan, "plan_details", None) or [])
        if seq > len(details) or not isinstance(details[seq - 1], dict):
            self.problem = translate_stability(
                u"The selected timepoint no longer exists.")
            return None
        row = details[seq - 1]

        months = normalize_months(row.get("timepoint_days", 0))
        status = normalize_status(row.get("detail_status"))
        sample_uid = self.first_uid(row.get("analysis_request"))
        sample = api.get_object_by_uid(sample_uid, None) if sample_uid else None

        expected = self.submitted_uids.get(row_id, u"")
        stored = get_row_uid(row)
        return {
            "row_id": row_id,
            "plan": plan,
            "plan_uid": plan_uid,
            "plan_title": api.get_title(plan) or api.get_id(plan) or u"",
            "plan_url": api.get_url(plan),
            "seq": seq,
            "detail_uid": stored,
            "expected_uid": expected,
            "task_title": localized_task_title(seq, months),
            "months": months,
            "status": status,
            "status_title": translate_stability(STATUS_TITLES.get(status, status)),
            "sample_uid": sample_uid,
            "sample_id": api.get_id(sample) or u"" if sample is not None else u"",
            "sample_url": api.get_url(sample) if sample is not None else u"",
            "revoked_at": us(row.get(sa.REVOKED_AT_FIELD)),
            "revoked_by": us(row.get(sa.REVOKED_BY_FIELD)),
            "revoke_reason": us(row.get(sa.REVOKE_REASON_FIELD)),
        }

    @staticmethod
    def first_uid(value):
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        return api.safe_unicode(value or u"").strip()

    def can_revoke(self):
        """页面上要不要给提交按钮（服务端仍会再判一遍）。"""
        if self.target is None:
            return False
        if not self.target.get("sample_uid"):
            return False
        return self.target.get("status") != "completed"

    def default_reason(self):
        form = getattr(self.request, "form", {}) or {}
        return us(form.get("reason")).strip()

    def revoke_message(self, result):
        msgid = REVOKE_MESSAGES.get(result.get("reason"))
        if not msgid:
            return us(result.get("reason") or u"")
        target = self.target or {}
        text = translate_stability(msgid)
        try:
            return text.format(
                plan=target.get("plan_title") or u"",
                task=target.get("task_title") or u"",
                sample=result.get("sample_id") or u"",
                status=target.get("status_title") or u"")
        except Exception:
            return text

    # ------------------------------------------------------------------ action
    def handle_revoke(self):
        if self.target is None:
            ploneapi.portal.show_message(
                message=self.problem or translate_stability(
                    u"The selected timepoint no longer exists."),
                request=self.request, type="error")
            return None

        form = getattr(self.request, "form", {}) or {}
        reason = us(form.get("reason")).strip()
        # 前端也有 required，但服务端必须自己判（页面可以绕过）
        if sa.reason_is_blank(reason):
            self.problem = translate_stability(
                REVOKE_MESSAGES[sa.REVOKE_REASON_REQUIRED])
            ploneapi.portal.show_message(
                message=self.problem, request=self.request, type="error")
            return None

        result = sg.revoke_sample_from_row(
            self.target["plan"], self.target["seq"], reason,
            revoked_by=sg.current_user_id(),
            expected_uid=self.target.get("expected_uid") or None)
        self.revoked = result

        ploneapi.portal.show_message(
            message=self.revoke_message(result), request=self.request,
            type="info" if result.get("ok") else "error")

        if result.get("ok"):
            return self.request.response.redirect(self.get_back_url())
        # 失败：留在本页说明原因（并刷新目标信息）
        self.target = self.get_target()
        return None
