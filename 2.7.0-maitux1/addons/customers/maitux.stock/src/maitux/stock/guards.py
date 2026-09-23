# -*- coding: utf-8 -*-
"""领用申请单的工作流守卫。

DCWorkflow 的 guard-expression 写成 ``python:here.guard_handler("<transition>")``，
``bika.lims.workflow.guard_handler`` 会遍历所有 IGuardAdapter，只要有任何一个返回
False 就阻止迁移（见 ``bika/lims/workflow/__init__.py:341``）。

**这里是"审核人不能是申请人"的硬底线**：按钮可见性只是体验，
即使有人手工拼 URL 也必须过不去。
"""
from bika.lims import api
from senaite.core import logger

from maitux.stock.config import USAGE_REQUEST_SIGNED_TRANSITIONS
from maitux.stock.usageapproval import check_approver
from maitux.stock.usageapproval import is_applicant
from maitux.stock.usageapproval import validate_lines


# 只有申请人本人可以执行的迁移
APPLICANT_TRANSITIONS = (u"submit", u"retract", u"cancel")
# 只能由「非申请人 + 具备审批角色」执行的迁移
APPROVER_TRANSITIONS = (u"approve", u"reject")


def _signature_context_tools():
    """延迟导入 esignature 的签名上下文工具（未安装时返回 None）。"""
    try:
        from maitux.esignature.services.context import (
            is_transition_execution_request,
        )
        from maitux.esignature.services.context import (
            is_verified_signature_context_valid,
        )
    except ImportError:
        return None, None
    return is_transition_execution_request, is_verified_signature_context_valid


class StockUsageRequestGuard(object):
    """领用申请单的守卫规则。"""

    def __init__(self, context):
        self.context = context

    def current_user_id(self):
        user = api.get_current_user()
        return user.getId() if user else u""

    def guard(self, transition):
        transition = api.safe_unicode(transition or "")
        if transition in APPLICANT_TRANSITIONS:
            return self.guard_applicant(transition)
        if transition in APPROVER_TRANSITIONS:
            return self.guard_approver(transition)
        return True

    def guard_signature(self, transition):
        """fail-closed：该签名却没签名的执行请求一律拦下。

        为什么要这一层：电子签名是靠 esignature 的"规则表"驱动的。万一规则行
        被人从控制面板里删掉，标准工作流入口就会**直接执行**迁移——也就是说
        会在没有任何签名的情况下把申请批出去。这里做兜底，宁可硬失败也不放行。

        只在"确实是在执行迁移"的请求上判定：否则连按钮可见性都会受影响。
        """
        if transition not in USAGE_REQUEST_SIGNED_TRANSITIONS:
            return True
        is_execution, is_valid = _signature_context_tools()
        if is_execution is None:
            return True
        if not is_execution(transition):
            return True
        user_id = self.current_user_id()
        if user_id and is_valid(self.context, transition, user_id):
            return True
        # 正常流程下这里会被命中一次：用户点动作时请求还没有签名上下文，
        # 电子签名模块随后会把他引到签名页。所以用 info 级别，避免误报为异常。
        logger.info(
            "Signature required for '%s' on StockUsageRequest '%s' and not yet "
            "verified; the electronic signature prompt is expected to take over. "
            "If the prompt never appears, check the signature rule table "
            "(maitux.esignature).",
            transition, getattr(self.context, "request_id", ""))
        return False

    def guard_applicant(self, transition):
        """发起 / 撤回 / 取消 都只能是申请人本人。"""
        if not is_applicant(self.context, self.current_user_id()):
            return False
        return self.guard_signature(transition)

    def guard_approver(self, transition):
        """审核 / 驳回：非申请人 + 具备审批角色 + 明细仍可扣减。"""
        if check_approver(self.context, self.current_user_id()):
            return False
        if transition == u"approve":
            # 明细已不可扣减（过期/余量不足）时，连"审核通过"都不该点得动。
            # 更具体的原因由 IBeforeTransitionEvent 给出。
            if validate_lines(list(getattr(self.context, "lines", None) or [])):
                return False
        return self.guard_signature(transition)
