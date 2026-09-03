# -*- coding: utf-8 -*-
"""maitux.setupmenu 接口定义

- ``IMaituxSetupMenuLayer``：浏览器层（继承 ISenaiteCore），安装后生效
- ``ISetupMenuRegistry``：Setup 菜单角色分配存储（plone.registry）
- ``IMenuEntryProvider``：addon 声明式注册 Setup 菜单条目的公开 API
"""

from plone.registry import field
from plone.theme.interfaces import IDefaultPloneLayer
from senaite.core.interfaces import ISenaiteCore
from zope.interface import Interface


class IMaituxSetupMenuLayer(ISenaiteCore, IDefaultPloneLayer):
    """maitux.setupmenu 浏览器层

    安装后：
      - ``plone.toolbar`` 管理器被本 add-on 的子类覆盖（齿轮按钮行为）
      - ``@@maitux-setup`` / ``@@maitux-setupmenu`` 视图可用
    卸载后浏览器层被移除，所有覆盖随之失效。
    """


class IMenuEntryProvider(Interface):
    """Addon 通过实现并注册此 utility 来声明 Setup 菜单条目

    注册方式（addon 侧 ZCML）：:

        <utility component=".menus.MenuProvider"
                 provides="maitux.setupmenu.interfaces.IMenuEntryProvider"
                 name="my.addon"/>

    ``get_menu_entries()`` 返回 ``list[dict]``，每项：:

        menu_id  (str, 必填)  全局唯一 ID，如 "my.addon.settings"
        title    (str, 必填)  显示标题（可翻译）
        url      (str, 必填)  相对门户的路径，如 "/@@my-settings"
        icon     (str, 可选)  FontAwesome class，如 "fas fa-cog"
        enabled  (bool, 可选) 默认是否启用（默认 True；False 表示默认隐藏，
                              管理员在管理界面分配角色后才可见）

    注册的条目自动出现在 ``@@maitux-setupmenu`` 管理界面，
    无需对 maitux.setupmenu 做任何改动。
    """

    def get_menu_entries():
        """返回 Setup 菜单条目列表"""


class ISetupMenuRegistry(Interface):
    """Setup 菜单角色分配存储（plone.registry）"""

    enabled = field.Bool(
        title=u"Enable role-based menu filtering",
        description=u"When enabled, only menus enabled below and assigned to "
                    u"the user's roles are displayed in the setup interface. "
                    u"When disabled, all menus are visible.",
        default=True,
        required=False,
    )

    menu_enabled = field.Dict(
        title=u"Enabled menus",
        description=u"Mapping of menu id to enabled state. Menus absent from "
                    u"this mapping are disabled (hidden for non-admin users).",
        key_type=field.ASCIILine(title=u"Menu ID"),
        value_type=field.Bool(title=u"Enabled"),
        default={},
        required=False,
    )

    menu_allowed_roles = field.Dict(
        title=u"Menu allowed roles",
        description=u"Mapping of menu id to tuple of allowed role names.",
        key_type=field.ASCIILine(title=u"Menu ID"),
        value_type=field.Tuple(
            title=u"Allowed roles",
            value_type=field.ASCIILine(title=u"Role")),
        default={},
        required=False,
    )
