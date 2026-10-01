# -*- coding: utf-8 -*-
"""方案页上的「方案状态」面板（阶段 6a）。

放在方案页（``IAboveContentBody``，与「本方案没有 0 点」提示条同一位置）的原因：

1. **需求 A3**：状态变更要有可读的留痕 —— 让业务人员去啃平台审计页
   （一页页翻 JSON diff）不现实，这里直接把"谁、什么时候、从什么状态改到什么状态、
   为什么"列出来；
2. **动作入口**：列表页的三个按钮是"列表级"的（拿不到选中行的状态），
   而这里拿得到**这一份方案**的状态，所以能只显示**当前可用**的动作
   （进行中 -> 暂停/终止；已暂停 -> 恢复/终止；已终止 -> 没有）。

只读展示 + 跳转链接，不在这里写库 —— 真正的状态变更在 ``@@plan_status``
（原因必填、留痕、审计都在那边，见 browser/planstatus.py）。
"""

from bika.lims import api
from bika.lims.api.security import check_permission
from plone.app.layout.viewlets import ViewletBase
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.core import logger

from maitux.stability import audit
from maitux.stability import plan_status
from maitux.stability.browser.planstatus import plan_actions
from maitux.stability.i18n import translate_stability
from maitux.stability.permissions import ManagePlanStatus
from maitux.stability.permissions import permission_name


class StabilityPlanStatusViewlet(ViewletBase):
    index = ViewPageTemplateFile("templates/stabilityplan_status.pt")

    def available(self):
        """只对稳定性方案出现（``for`` 已经限定，这里再判一次更保险）。"""
        try:
            return api.get_portal_type(self.context) == "StabilityPlan"
        except Exception:
            return False

    # ------------------------------------------------------------- 状态与留痕
    def plan_state(self):
        return plan_status.get_plan_state(self.context)

    def state_title(self):
        return translate_stability(
            plan_status.state_title(self.plan_state()))

    def state_class(self):
        """状态徽标的样式类（与 senaite 的状态色板同一命名）。"""
        return {
            plan_status.STATE_IN_PROGRESS: "badge badge-success",
            plan_status.STATE_PAUSED: "badge badge-warning",
            plan_status.STATE_TERMINATED: "badge badge-secondary",
        }.get(self.plan_state(), "badge badge-secondary")

    def state_notice(self):
        state = self.plan_state()
        if state == plan_status.STATE_PAUSED:
            return translate_stability(
                u"This plan is paused. All operations on its timepoints are "
                u"frozen until it is resumed.")
        if state == plan_status.STATE_TERMINATED:
            return translate_stability(u"This plan is terminated.")
        return u""

    def status_changed_at(self):
        return api.safe_unicode(
            getattr(self.context, plan_status.STATUS_CHANGED_AT_FIELD, u""))

    def status_changed_by(self):
        return api.safe_unicode(
            getattr(self.context, plan_status.STATUS_CHANGED_BY_FIELD, u""))

    def status_changed_reason(self):
        return api.safe_unicode(
            getattr(self.context, plan_status.STATUS_REASON_FIELD, u""))

    def has_trace(self):
        return bool(self.status_changed_at() or self.status_changed_by()
                    or self.status_changed_reason())

    # ------------------------------------------------------------------ 历史
    def history(self):
        """状态变更历史（**最新的在前**），附上译好的状态标题。

        读侧非常宽容（``audit.get_status_history`` 会跳过认不出的记录）：
        页面不能因为 annotation 里一条脏数据就打不开。
        """
        entries = []
        for item in audit.get_status_history(self.context):
            entries.append({
                "time": item.get("time") or u"",
                "actor": item.get("actor") or u"",
                "reason": item.get("reason") or u"",
                "from_title": translate_stability(
                    plan_status.state_title(item.get("state_before"))),
                "to_title": translate_stability(
                    plan_status.state_title(item.get("state_after"))),
            })
        return entries

    # ------------------------------------------------------------------ 动作
    def can_manage(self):
        """能不能改状态（决定要不要显示三个动作按钮）。

        与 ``PlanStatusView.can_manage`` 同一判据 —— 权限名必须先解析成
        Zope 真正认的 title 形式（见 permissions.py 的模块注释）。
        """
        try:
            if check_permission(permission_name(ManagePlanStatus), self.context):
                return True
        except Exception:
            logger.exception("Failed to check the plan status permission")
        return False

    def actions(self):
        """当前状态下可用的动作（进行中 -> 暂停/终止；已暂停 -> 恢复/终止）。"""
        return plan_actions(self.context)

    def plan_url(self):
        return api.get_url(self.context)

    def action_url(self, action):
        """动作按钮的目标：``@@plan_status?transition=...``（带原因表单的那一页）。"""
        return "{0}/@@plan_status?transition={1}".format(
            self.plan_url(), action.get("transition"))

    def render(self):
        try:
            if not self.available():
                return ""
            return self.index()
        except Exception:
            # 面板永远不能让方案页 500：它是"额外面板"，不是功能本身。
            logger.exception("Failed to render the stability plan status panel")
            return ""
