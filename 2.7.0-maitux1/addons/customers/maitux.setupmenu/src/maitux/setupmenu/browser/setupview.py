# -*- coding: utf-8 -*-
"""用户端 Setup 界面（``@@maitux-setup``）

与 senaite.core 的 ``@@lims-setup`` 同风格（tile 网格 + 搜索过滤），但：

  - 页面骨架用 main_template（任何登录用户可渲染，不依赖控制面板权限）
  - 菜单按当前用户角色过滤（管理员始终可见全部）
  - 未配置任何菜单时显示空状态提示
"""

from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.core.browser.controlpanel.setupview import SetupView as BaseSetupView

from maitux.setupmenu.api import get_roles
from maitux.setupmenu.api import is_admin as is_admin_user
from maitux.setupmenu.api import is_filtering_enabled
from maitux.setupmenu.api import is_menu_visible_for
from maitux.setupmenu.menus import get_all_menu_items
from maitux.setupmenu.menus import get_menu_id


class SetupMenuView(BaseSetupView):
    """按角色过滤的 Setup 界面"""
    template = ViewPageTemplateFile("templates/setupmenu.pt")

    def setupitems(self):
        """返回对当前用户可见的菜单条目"""
        items = get_all_menu_items()
        if not is_filtering_enabled():
            return items
        admin = is_admin_user()
        roles = set(get_roles())
        return [item for item in items
                if is_menu_visible_for(get_menu_id(item), roles, admin=admin)]

    def get_count(self, obj):
        """虚拟条目没有 portal_type，兜底用 objectIds()"""
        if not hasattr(obj, "portal_type"):
            try:
                return len(obj.objectIds())
            except Exception:  # noqa: B902
                return 0
        return super(SetupMenuView, self).get_count(obj)

    def get_icon_for(self, brain, **kw):
        """虚拟条目使用默认 FontAwesome 图标，其余走内容类型图标"""
        if not hasattr(brain, "portal_type"):
            css = kw.get("css_class", "")
            cls = "fas fa-cog"
            if css:
                cls = "{} {}".format(cls, css)
            return '<i class="{}"></i>'.format(cls)
        return super(SetupMenuView, self).get_icon_for(brain, **kw)
