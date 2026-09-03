# -*- coding: utf-8 -*-
"""Setup 菜单管理界面（``@@maitux-setupmenu``）

表格列出全部菜单（核心 + addon），支持：

  - 全局过滤开关
  - 逐菜单启用/停用
  - 逐菜单分配允许角色（多选）

入口：Site Setup → Menu Management。
"""

from plone import api as ploneapi
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from bika.lims import api
from senaite.core import logger
from maitux.setupmenu.api import get_menu_allowed_roles
from maitux.setupmenu.api import get_menu_enabled
from maitux.setupmenu.api import is_filtering_enabled as is_filtering_enabled_setting
from maitux.setupmenu.api import set_filtering_enabled
from maitux.setupmenu.api import set_menu_config
from maitux.setupmenu.config import HIDDEN_ROLES
from maitux.setupmenu.menus import get_all_menu_items
from maitux.setupmenu.menus import get_item_title
from maitux.setupmenu.menus import get_menu_id

SAVE_BUTTON = "form.button.Save"

# 角色复选框字段名前缀（与模板 name="roles_<i>:list" 对应）
ROLES_FIELD_PREFIX = "roles_"


class SetupMenuManagementView(BrowserView):
    """Setup 菜单管理"""

    template = ViewPageTemplateFile("templates/menumanagement.pt")

    def __call__(self):
        form = self.request.form
        if SAVE_BUTTON in form:
            self.save(form)
            ploneapi.portal.show_message(
                message="Changes saved.",
                request=self.request,
                type="info")
        return self.template()

    @property
    def is_filtering_enabled(self):
        """全局过滤开关当前状态"""
        return is_filtering_enabled_setting()

    def roles(self):
        """可分配的角色列表（动态读取，新增角色/角色 addon 自动出现）"""
        portal = api.get_portal()
        pmemb = api.get_tool("portal_membership")
        roles = pmemb.getPortalRoles() if pmemb else []
        if not roles and hasattr(portal, "valid_roles"):
            roles = portal.valid_roles()
        return [role for role in roles if role not in HIDDEN_ROLES]

    def menus(self):
        """全部菜单条目 + 当前配置（用于表格渲染）"""
        out = []
        for item in get_all_menu_items():
            menu_id = get_menu_id(item)
            out.append({
                "menu_id": menu_id,
                "title": get_item_title(item),
                "url": self._get_url(item),
                "source": self._get_source(item),
                "icon": self._get_icon(item),
                "enabled": get_menu_enabled(menu_id),
                "allowed_roles": get_menu_allowed_roles(menu_id),
            })
        return out

    def save(self, form):
        """保存全局开关与逐菜单配置（表单字段按行索引关联）"""
        set_filtering_enabled(bool(form.get("filtering_enabled")))
        index = 0
        while True:
            menu_id = form.get("menu_id_%d" % index)
            if menu_id is None:
                break
            enabled = bool(form.get("enabled_%d" % index))
            roles = self._get_submitted_roles(form, index)
            logger.info(
                "maitux.setupmenu save: menu=%s enabled=%s roles=%s"
                % (menu_id, enabled, roles))
            set_menu_config(menu_id, enabled, roles)
            index += 1

    @staticmethod
    def _get_submitted_roles(form, index):
        """读取某一行提交的角色勾选

        ZPublisher 对表单 ``:list`` 标记的处理在不同版本/场景下有差异，
        这里按三种形态依次尝试，保证兼容：

          1. 带标记读取（标准写法）：form.get("roles_<i>:list")
          2. 标记已被剥离到同名 key：form.get("roles_<i>")
          3. 扫描 form keys（前缀匹配，覆盖其它标记变体）

        返回值一律是角色名列表；单值字符串作为一个整体角色名
        （绝不能把字符串拆成字符）。
        """
        values = form.get("%s%d:list" % (ROLES_FIELD_PREFIX, index))
        if values is None:
            values = form.get("%s%d" % (ROLES_FIELD_PREFIX, index))
        if values is None:
            prefix = "%s%d" % (ROLES_FIELD_PREFIX, index)
            collected = []
            for key in form.keys():
                if key == prefix or key.startswith(prefix + ":"):
                    value = form[key]
                    if isinstance(value, (list, tuple)):
                        collected.extend(value)
                    else:
                        collected.append(value)
            values = collected
        if values is None:
            return []
        if isinstance(values, (list, tuple)):
            return [value for value in values if value]
        # 单值（字符串）：整体作为一个角色名
        return [values] if values else []

    @staticmethod
    def _get_url(item):
        url = getattr(item, "absolute_url", None)
        if callable(url):
            return url()
        return url or ""

    @staticmethod
    def _get_source(item):
        """菜单来源：core（新 setup）/ legacy（bika_setup）/ addon（虚拟）"""
        if not hasattr(item, "portal_type"):
            return "addon"
        path = api.get_path(item)
        if path.startswith("/setup"):
            return "core"
        if path.startswith("/bika_setup"):
            return "legacy"
        return "other"

    @staticmethod
    def _get_icon(item):
        return getattr(item, "icon", None) or ""
