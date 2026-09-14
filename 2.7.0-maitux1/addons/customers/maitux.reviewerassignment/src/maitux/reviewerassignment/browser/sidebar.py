# -*- coding: utf-8 -*-
"""侧边栏导航 JSON 的覆盖视图

senaite.core 的 ``SidebarNavigationAPI`` 对每个条目标题统一调用
``translate(title, domain="senaite.core")``：

    # senaite.core/browser/viewlets/sidebar.py
    "title": translate(node.get("Title", ""), to_utf8=False)

而 ``senaite.core.i18n.translate`` 只在拿到 ``Message`` 时才用消息自带的
domain，否则 domain 固定回落到 ``"senaite.core"``：

    domain = getattr(msgid, "domain", "senaite.core")

本 addon 的 msgid 不在 ``senaite.core`` 的目录里，查不到就会把 msgid 原样
显示到界面上（实测侧边栏出现 ``folder_title_review_worksheets``）。

所以这里只做一件事：给本 addon 根目录的条目换上 ``Message``，让父类的
translate 用上本 addon 的翻译域。其余导航逻辑完全复用父类。

注意：**不能**靠把 Message 存进对象 Title 来解决 —— Dexterity 存 title 时会把
Message 拍平成纯字符串（实测存进去再读出来是 str 的 msgid），domain 一并丢失。
"""

from senaite.core.browser.viewlets.sidebar import (
    SidebarNavigationAPI as BaseSidebarNavigationAPI,
)

from maitux.reviewerassignment.config import ROOT_DESCRIPTION_MSG
from maitux.reviewerassignment.config import ROOT_TITLE_MSG
from maitux.reviewerassignment.config import ROOT_TYPE


class SidebarNavigationAPI(BaseSidebarNavigationAPI):
    """让本 addon 根目录的标题走本 addon 的翻译域"""

    def _create_item_from_brain(self, brain, depth):
        item = super(SidebarNavigationAPI, self)._create_item_from_brain(
            brain, depth)
        if item is None:
            return None
        if item.get("portal_type") == ROOT_TYPE:
            # 必须是 Message：父类的 translate 靠它拿到 domain
            item["Title"] = ROOT_TITLE_MSG
            item["Description"] = ROOT_DESCRIPTION_MSG
        return item
