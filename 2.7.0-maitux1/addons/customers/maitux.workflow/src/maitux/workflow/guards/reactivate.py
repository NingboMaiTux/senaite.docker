# -*- coding: utf-8 -*-
"""Reactivate 的工作流守卫

只管一件事：**父样品已经死掉的分析项，不给 Reactivate 按钮。**

「死掉」指样品处于 cancelled / rejected / invalid / dispatched 之一。激活这类
样品下的分析项会造出一个 core 自己收拾不了的组合 —— 分析项活着、样品还躺着，
而样品侧的恢复路径（reinstate / restore）又各有各的前提。

本适配器是 ``for="*"`` 的**进程级**注册，四个站点都会调到它，包括从没装过本包
的三个。所以 ``guard()`` 第一句必须先做站点级收口 —— 详见 siteinstall 模块。
"""

from bika.lims import api
# ★ IRequestAnalysis 在 bika.lims.interfaces.analysis 里，不在 bika.lims.interfaces
# 顶层。写错会以 ImportError 的形式在 ZCML 加载期炸掉，**整站起不来**。
from bika.lims.interfaces.analysis import IRequestAnalysis

from maitux.workflow.siteinstall import is_installed_in_current_site

# 本包唯一需要守卫的 transition。其余一律放行，绝不插手原生流程。
GUARDED_TRANSITION = "reactivate"

# 父样品处于这些状态时不给激活。它们的共同点是样品本身已经退出正常流程，
# 单独把某条分析项拉活起来只会制造状态矛盾。
DEAD_SAMPLE_STATES = (
    "cancelled",
    "rejected",
    "invalid",
    "dispatched",
)


class ReactivateGuardAdapter(object):
    """分析项 Reactivate 的守卫。除此之外一律放行。"""

    def __init__(self, context):
        self.context = context

    def guard(self, transition):
        # ★ 站点级收口。本适配器在所有站点参与每一次 guard 求值，只有装了本包的
        # 站点才该受这条规则约束 —— 未安装一律放行，绝不影响别人的原生流程。
        if not is_installed_in_current_site():
            return True

        if transition != GUARDED_TRANSITION:
            return True

        # 只管常规分析项。样品自己的 reactivate、参比分析等一律不插手。
        if not IRequestAnalysis.providedBy(self.context):
            return True

        return self.guard_reactivate()

    def guard_reactivate(self):
        """父样品还活着才允许激活分析项。"""
        sample = self.context.getRequest()
        if sample is None:
            # 取不到父样品时放行：这不是本守卫该下结论的情况，
            # 让后续逻辑去报错，好过在这里静默地把按钮吃掉。
            return True

        return api.get_review_status(sample) not in DEAD_SAMPLE_STATES
