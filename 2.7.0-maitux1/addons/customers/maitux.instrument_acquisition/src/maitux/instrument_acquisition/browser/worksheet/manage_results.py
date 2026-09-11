# -*- coding: utf-8 -*-
"""仪器采集版 Worksheet 结果录入页（manage_results 覆盖）

在第一阶段覆盖 `manage_results`：
- 继承 maitux.reviewerassignment 的 ManageResultsView，保留审核人扩展
- 注入"仪器采集"入口（URL、会话状态、仪器可用状态、是否显示按钮）
- 提供第一阶段只读关键字集合，由模板渲染为只读
"""

import json

from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from maitux.reviewerassignment.browser.manage_results import (
    ManageResultsView as ReviewerManageResultsView,
)

from maitux.instrument_acquisition.services.session_store import (
    collect_readonly_keywords,
)
from maitux.instrument_acquisition.services.session_store import (
    get_active_session,
)

ACQUISITION_VIEW_NAME = "worksheet_instrument_acquisition"


class ManageResultsView(ReviewerManageResultsView):
    """在审核人分配基础上增加仪器采集入口与只读控制"""

    template = ViewPageTemplateFile("templates/manage_results.pt")

    def get_acquisition_url(self):
        """返回采集页面 URL"""
        return "{}/@@{}".format(
            self.context.absolute_url(), ACQUISITION_VIEW_NAME)

    def is_instrument_available(self):
        """当前 Worksheet 是否已分配仪器"""
        try:
            return self.context.getInstrument() is not None
        except Exception:
            return False

    def show_acquisition_entry(self):
        """是否显示仪器采集入口（已选仪器且允许编辑时显示）"""
        try:
            return self.is_instrument_available() and self.is_assignment_allowed()
        except Exception:
            return False

    def get_active_session_info(self):
        """返回当前活动会话摘要，无会话返回 None"""
        try:
            session = get_active_session(self.context)
        except Exception:
            return None
        if not session:
            return None
        return {
            "session_id": session.get("session_id", ""),
            "status": session.get("status", ""),
            "instrument_title": session.get("instrument_title", ""),
        }

    def get_readonly_keywords(self):
        """返回本 Worksheet 需要只读保护的关键字列表

        = 各分析行上被标成采集目标（`acquisition_role`/`acquisition_group`）
        的 keyword 并集。★ 原先返回写死的 `("T_name", "T_weight")`。
        """
        try:
            return collect_readonly_keywords(self.context)
        except Exception:
            return []

    def get_readonly_keywords_json(self):
        """返回只读关键字的 JSON 数组（供模板内 JS 使用）"""
        return json.dumps(self.get_readonly_keywords())
