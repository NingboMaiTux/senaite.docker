# -*- coding: utf-8 -*-
"""阶段 6a：「方案状态」动作页 —— 暂停 / 恢复 / 终止。

为什么需要它（而不是让列表页的按钮直接打工作流流转）：

1. **原因必填**。需求要求状态变更留痕、原因必填（第 3 轮第 7 条），
   而工作流流转本身没有"填原因"的界面 —— ``doActionFor`` 只是把 ``comment``
   写进 review_history。所以要有这一页收原因，再由
   ``plan_status.change_plan_status`` 把原因传给流转（进审计快照的 comments）。
2. **终止前要提示**。需求原文："终止的时候如果已经有样品生成，样品没有完成则
   提示，是否继续终止"（第 1 轮第 3 条）。这一页把"未完成的样品"逐条列出来，
   让人看清楚再决定。
3. **提示要说清楚是哪一种冻结**。工作流自己只会说 "Transition not allowed"，
   而分成"方案已暂停"和"方案已终止"两句，用户才知道下一步该找谁。

三个动作都走同一页，靠 ``?transition=`` 区分；列表页/方案页上的按钮
先经过 ``workflow_action_pause_plan`` 之类的适配器转到这一页（同「复制计划」
「撤销登样」的套路）。

完成后的落点：**方案所在容器**（即方案列表 ``200_stability_plans``）——
那里有状态列，用户能立刻看到结果。刻意不做 ``back`` 参数：
"从哪儿来就回哪儿"要靠校验 referer/URL 才安全，为了一个跳转引入
开放重定向的口子不值得。
"""

from bika.lims import api
from bika.lims.api.security import check_permission
from bika.lims.browser.workflow import RequestContextAware
from bika.lims.interfaces import IWorkflowActionUIDsAdapter
from plone import api as ploneapi
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.core import logger
from zope.interface import implements

from maitux.stability import audit
from maitux.stability import plan_status
from maitux.stability.i18n import translate_stability
from maitux.stability.permissions import ManagePlanStatus
from maitux.stability.permissions import permission_name
from maitux.stability.title import localized_task_title


# 结果码 -> 文案（msgid）。服务端只给码，界面按语言取文案。
STATUS_MESSAGES = {
    plan_status.TRANSITION_NOT_ALLOWED: u"The stability plan cannot be "
                                        u"changed to the requested state "
                                        u"from its current state.",
    plan_status.REASON_REQUIRED: u"A reason is required to change the status "
                                 u"of a stability plan.",
    plan_status.BLOCK_PLAN_PAUSED: u"This stability plan is paused. "
                                   u"All operations on it are frozen.",
    plan_status.BLOCK_PLAN_TERMINATED: u"This stability plan is terminated.",
}

# 流转 -> 完成后的提示文案（msgid）
SUCCESS_MESSAGES = {
    plan_status.TRANSITION_PAUSE: u"The stability plan has been paused.",
    plan_status.TRANSITION_RESUME: u"The stability plan has been resumed.",
    plan_status.TRANSITION_TERMINATE: u"The stability plan has been terminated.",
}

# 流转 -> 页面标题（msgid）
TITLES = {
    plan_status.TRANSITION_PAUSE: u"Pause Stability Plan",
    plan_status.TRANSITION_RESUME: u"Resume Stability Plan",
    plan_status.TRANSITION_TERMINATE: u"Terminate Stability Plan",
}

# 流转 -> 提交按钮文案（msgid）
BUTTONS = {
    plan_status.TRANSITION_PAUSE: u"Pause",
    plan_status.TRANSITION_RESUME: u"Resume",
    plan_status.TRANSITION_TERMINATE: u"Terminate",
}


def us(value):
    """安全转 unicode。"""
    return api.safe_unicode(value) if value is not None else u""


class PlanStatusView(BrowserView):
    """``@@plan_status``：把方案流转到另一个状态（原因必填、留痕、审计）。"""

    template = ViewPageTemplateFile("templates/plan_status.pt")

    transition = u""
    reason = u""
    problem = u""
    result = None
    samples = []
    sample_states = {}

    def __call__(self):
        form = getattr(self.request, "form", {}) or {}

        # 权限门（ZCML 里只能写 zope2.View，真正的门在这里 —— 见 browser/configure.zcml）
        if not self.can_manage():
            ploneapi.portal.show_message(
                message=translate_stability(
                    u"You do not have permission to change the status of a "
                    u"stability plan."),
                request=self.request, type="error")
            return self.request.response.redirect(self.get_back_url())

        self.transition = self.resolve_transition(form)
        self.reason = us(form.get("reason")).strip()
        self.samples = plan_status.get_plan_samples(self.context)

        if form.get("button_cancel"):
            return self.request.response.redirect(self.get_back_url())

        if form.get("button_apply"):
            handled = self.handle_apply()
            if handled is not None:
                return handled

        return self.template()

    # ------------------------------------------------------------- 页面数据
    def can_manage(self):
        """能不能改这个方案的状态。

        权限名先解析成 Zope 真正认的 title 形式 —— 直接把 ZCML 的 id 常量喂给
        ``check_permission`` 会对**非 Manager 用户一律返回 False**
        （Zope 对 Manager 角色硬编码放行，所以只用 admin 测发现不了）。
        详见 maitux.stability.permissions 的模块注释与阶段 5 实施说明 §2.4。
        """
        if check_permission(permission_name(ManagePlanStatus), self.context):
            return True
        try:
            user = ploneapi.user.get_current()
            return "Manager" in set(user.getRolesInContext(self.context))
        except Exception:
            return False

    def resolve_transition(self, form):
        """从查询串/表单里取流转 id，认不出就置空（页面会显示"不支持的动作"）。"""
        value = us(form.get("transition")).strip()
        if value in plan_status.TRANSITIONS:
            return value
        return u""

    def plan_title(self):
        return api.get_title(self.context) or api.get_id(self.context) or u""

    def plan_url(self):
        return api.get_url(self.context)

    def get_back_url(self):
        """动作完成 / 取消后回到方案所在容器（方案列表，那里有状态列）。"""
        try:
            container = api.get_parent(self.context)
            if container is not None:
                return api.get_url(container)
        except Exception:
            logger.exception(
                "Failed to resolve the container of %r", self.context)
        return self.plan_url()

    def current_state(self):
        return plan_status.get_plan_state(self.context)

    def current_state_title(self):
        return translate_stability(
            plan_status.state_title(self.current_state()))

    def target_state_title(self):
        state = plan_status.target_state(self.transition)
        return translate_stability(plan_status.state_title(state)) if state \
            else u""

    def page_title(self):
        return translate_stability(TITLES.get(self.transition, u""))

    def submit_label(self):
        return translate_stability(BUTTONS.get(self.transition, u""))

    def is_terminate(self):
        return self.transition == plan_status.TRANSITION_TERMINATE

    def can_apply(self):
        """页面上要不要给提交按钮（服务端仍会再判一遍）。

        判据与 :meth:`handle_apply` 完全一致：状态机允许 + 原因填了。
        原因未填时按钮**不禁用** —— 让人点了看到"请填写原因"比一个灰按钮
        更容易理解（而且禁用按钮在"先填原因"的场景里等于没有提示）。
        """
        if not self.transition:
            return False
        ok, _reason = plan_status.can_transition(
            self.current_state(), self.transition)
        return ok

    def block_message(self):
        """不能执行时的说明（状态机层面的原因，与原因是否填了无关）。"""
        if not self.transition:
            return translate_stability(u"Unsupported action.")
        ok, reason = plan_status.can_transition(
            self.current_state(), self.transition)
        if ok:
            # 状态允许，但当前是「已暂停 / 已终止」时也要把话说清楚：
            # 例如方案已暂停时点「暂停」是没意义的，页面要解释为什么。
            return u""
        if reason == plan_status.TRANSITION_NOT_ALLOWED:
            return translate_stability(
                u"The stability plan cannot be changed to the requested state "
                u"from its current state.")
        return translate_stability(STATUS_MESSAGES.get(reason, reason))

    def status_changed_at(self):
        """上一次状态变更的时间（留痕字段，可能为空）。"""
        return us(getattr(self.context,
                          plan_status.STATUS_CHANGED_AT_FIELD, u""))

    def status_changed_by(self):
        """上一次状态变更的操作人。"""
        return us(getattr(self.context,
                          plan_status.STATUS_CHANGED_BY_FIELD, u""))

    def status_changed_reason(self):
        """上一次状态变更的原因。"""
        return us(getattr(self.context, plan_status.STATUS_REASON_FIELD, u""))

    def state_notice(self):
        """当前状态的提示条文案（暂停/终止时页面顶部给出）。"""
        state = self.current_state()
        if state == plan_status.STATE_PAUSED:
            return translate_stability(
                u"This plan is paused. All operations on its timepoints are "
                u"frozen until it is resumed.")
        if state == plan_status.STATE_TERMINATED:
            return translate_stability(u"This plan is terminated.")
        return u""

    def unfinished_samples(self):
        """未完成的样品（终止页要把它们逐条列出来）。"""
        return [item for item in self.samples if not item.get("finished")]

    def sample_task_title(self, item):
        return localized_task_title(item.get("row_seq"),
                                    item.get("timepoint_months", 0))

    def sample_state_title(self, state):
        """样品状态 -> 当前语言的标题。

        走平台的工作流标题（``portal_workflow.getTitleForStateOnType``），
        不自己维护一张状态标题表 —— senaite 的样品状态有 13 个，
        自建表迟早与平台漂移。
        """
        state = us(state).strip()
        if not state:
            return translate_stability(u"Unknown")
        try:
            wf_tool = api.get_tool("portal_workflow")
            title = wf_tool.getTitleForStateOnType(state, "AnalysisRequest")
            if title:
                return api.safe_unicode(title)
        except Exception:
            logger.exception("Failed to resolve the sample state title for %r",
                             state)
        return state

    # ---------------------------------------------------------------- 动作
    def handle_apply(self):
        """执行流转；成功则跳走，失败留在本页说明原因。"""
        if not self.transition:
            self.problem = translate_stability(u"Unsupported action.")
            ploneapi.portal.show_message(
                message=self.problem, request=self.request, type="error")
            return None

        # 服务端再判一遍原因（前端 required 可以被绕过）
        if plan_status.reason_is_blank(self.reason):
            self.problem = translate_stability(
                STATUS_MESSAGES[plan_status.REASON_REQUIRED])
            ploneapi.portal.show_message(
                message=self.problem, request=self.request, type="error")
            return None

        ok, payload = plan_status.change_plan_status(
            self.context, self.transition, self.reason,
            actor=_current_user_id())
        self.result = payload

        if ok:
            message = SUCCESS_MESSAGES.get(self.transition) \
                or u"The stability plan status has been changed."
            ploneapi.portal.show_message(
                message=translate_stability(message),
                request=self.request, type="info")
            # 恢复后提示（见需求确认稿第 9 节第 1 条）：暂停期间过期的时间点
            # 恢复后**全部过期**，而新增的点仍按 T0 + N 月算 —— T0 是唯一的出口。
            #
            # ★ 文案刻意只说"请检查 T0 与已过期的时间点"，**不写**"不会再次自动登样"：
            #   6a 还没有"过期"这条规则（那是 6b），当前实现下恢复后的下一次
            #   到期扫描**会补生成**暂停期间到期的点。写一句当前不成立的话，
            #   比不提示更糟（用户会据此判断方案安全）。6b 落地后再收紧这句。
            if self.transition == plan_status.TRANSITION_RESUME:
                ploneapi.portal.show_message(
                    message=translate_stability(
                        u"Resumed. Please check the timepoints that expired "
                        u"during the pause and the Start Time (T0) before the "
                        u"next automatic scan runs."),
                    request=self.request, type="warning")
            return self.request.response.redirect(self.get_back_url())

        # 失败：留在本页（原因已经填着，用户改一下就能重试）
        error = payload.get("error") or plan_status.TRANSITION_NOT_ALLOWED
        msgid = STATUS_MESSAGES.get(error)
        self.problem = translate_stability(msgid) if msgid else us(error)
        ploneapi.portal.show_message(
            message=self.problem, request=self.request, type="error")
        # 状态可能已经被别人改过了 —— 重新读一遍，免得页面还在显示旧状态
        self.samples = plan_status.get_plan_samples(self.context)
        return None


def _current_user_id():
    try:
        return us(api.get_current_user().getId())
    except Exception:
        return u""


class _PlanStatusActionAdapter(RequestContextAware):
    """列表页 / 方案页上的「暂停 / 恢复 / 终止」按钮 -> 跳到状态动作页。

    ★ 一次只允许选**一个**方案：状态是"一份方案一个状态"的动作，
      而"终止"是终态 —— 批量点错的代价不可逆，所以这里直接拦住多选。

    与「复制计划」按钮同一套路（``WorkflowActionCopyPlanAdapter``）：
    适配器只负责校验 + 跳转，真正的校验与写库在 PlanStatusView 里。
    """

    implements(IWorkflowActionUIDsAdapter)

    #: 子类指定（取值必须是 plan_status.TRANSITIONS 里的）
    transition = u""

    def __call__(self, action, uids):
        if not uids:
            return self.redirect(
                message=translate_stability(
                    u"Please select one stability plan first."),
                level="warning")
        if len(uids) > 1:
            return self.redirect(
                message=translate_stability(
                    u"Please select exactly one stability plan: the plan "
                    u"status is changed one plan at a time."),
                level="warning")

        plan = api.get_object_by_uid(uids[0], None)
        if plan is None or api.get_portal_type(plan) != "StabilityPlan":
            return self.redirect(
                message=translate_stability(
                    u"The selected stability plan could not be found."),
                level="error")

        url = "{0}/@@plan_status?transition={1}".format(
            api.get_url(plan), self.transition)
        return self.redirect(redirect_url=url)


class WorkflowActionPausePlanAdapter(_PlanStatusActionAdapter):
    """列表页「暂停」按钮。"""
    transition = plan_status.TRANSITION_PAUSE


class WorkflowActionResumePlanAdapter(_PlanStatusActionAdapter):
    """列表页「恢复」按钮。"""
    transition = plan_status.TRANSITION_RESUME


class WorkflowActionTerminatePlanAdapter(_PlanStatusActionAdapter):
    """列表页「终止」按钮。"""
    transition = plan_status.TRANSITION_TERMINATE


def plan_actions(plan):
    """给某个方案算出"现在能点哪些动作"（列表页与方案页共用）。

    返回 ``[{"id", "title", "url", "help"}, ...]``；
    ``id`` 用 ``<transition>_plan`` 的形态，与 ZCML 里注册的
    ``workflow_action_<id>`` 适配器名一一对应。

    ★ 这里**刻意不判权限**：列表视图是在一个非最终用户的安全上下文里构造的
      （实测 ``check_permission`` 返回 False、用户 id 为 None），按权限决定
      要不要挂按钮会让功能静默消失。权限在点下去之后由 PlanStatusView 统一校验 ——
      与同页「复制计划」按钮的做法一致（见 browser/view.py 的 init_custom_transitions）。
    """
    state = plan_status.get_plan_state(plan)
    items = []
    for transition in plan_status.TRANSITIONS:
        if not plan_status.transition_available(state, transition):
            continue
        items.append({
            "id": u"%s_plan" % transition,
            "title": translate_stability(BUTTONS.get(transition, transition)),
            "url": "workflow_action?workflow_action_id=%s_plan" % transition,
            "help": translate_stability(TITLES.get(transition, u"")),
            "transition": transition,
        })
    return items
