# -*- coding: utf-8 -*-
"""plone.toolbar 管理器覆盖：右上角齿轮按钮行为

- 齿轮对所有登录用户可见（原实现仅对持有 ManageBika 的管理员可见）
- 链接按身份区分（管理员 = Manager / Site Administrator 角色，
  不能用 ManageBika 权限判定 —— 该权限授给了 LabClerk/LabManager，
  会把普通角色当管理员，使其绕过菜单过滤）：
    - 管理员 → ``@@lims-setup``（原 Setup 界面）
    - 非管理员 → ``@@maitux-setup``（新的按角色过滤的 Setup 界面）

仅覆盖必要方法（开发规则 R6：继承 + 只改必要方法），
模板与其余行为随 senaite.core 自动跟进。
"""

from bika.lims.api.security import get_roles
from senaite.core.browser.viewlets.toolbar import \
    ToolbarViewletManager as BaseToolbarViewletManager

from maitux.setupmenu.config import ADMIN_ROLES
from maitux.setupmenu.config import USER_SETUP_VIEW


class ToolbarViewletManager(BaseToolbarViewletManager):
    """齿轮按钮对所有登录用户可见，链接按管理员/非管理员区分"""

    def is_manager(self):
        """齿轮对登录用户可见（不再要求 ManageBika）"""
        return not self.portal_state.anonymous()

    def get_lims_setup_url(self):
        """齿轮链接：管理员 → @@lims-setup；非管理员 → @@maitux-setup"""
        portal = self.portal_state.portal()
        portal_url = portal.absolute_url()
        roles = get_roles() or []
        if set(ADMIN_ROLES) & set(roles):
            return "/".join([portal_url, "@@lims-setup"])
        return "/".join([portal_url, USER_SETUP_VIEW])
