# -*- coding: utf-8 -*-
"""方案页/方案编辑页上的「本方案没有 0 点」提示条（B 方案，2026-09-30）。

为什么需要它：0 点（基线点）在代码里**不强制**，但"没有 0 点"的直接后果是
**没有基线样品** —— 阶段 3 的「关联已有样品」只对 0 点行开放，方案上又看不出来。
提示条把这件事摆在方案页上，而不是等用户在看板上点按钮才被拒。

只做提示，不阻断任何操作（保存方案、加行、删行都不受影响）。
"""

from bika.lims import api
from plone.app.layout.viewlets import ViewletBase
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.core import logger

from maitux.stability.timepoints import has_initial_row


class StabilityPlanZeroPointViewlet(ViewletBase):
    index = ViewPageTemplateFile("templates/stabilityplan_zeropoint_notice.pt")

    def plan_details(self):
        return getattr(self.context, "plan_details", None) or []

    def available(self):
        """只对"没有 0 点的稳定性方案"出现。

        判据走 ``timepoints.has_initial_row``（唯一实现：只有
        ``timepoint_days`` 明确等于 0 才算 0 点）。行数很多时也只是遍历一遍，
        方案是几十行量级，不做缓存。
        """
        try:
            if api.get_portal_type(self.context) != "StabilityPlan":
                return False
        except Exception:
            return False
        return not has_initial_row(self.plan_details())

    def render(self):
        try:
            if not self.available():
                return ""
            return self.index()
        except Exception:
            # 提示条永远不能让页面 500：它是"额外说明"，不是功能本身。
            logger.exception("Failed to render the zero point notice")
            return ""
