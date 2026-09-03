# -*- coding: utf-8 -*-
"""模块配置常量"""

# 项目标识（用于日志和配置查找）
PROJECTNAME = "maitux.setupmenu"

# 安装标记（portal property）：安装时写入、卸载时清除，
# 用于在浏览器层尚未移除时也保证功能整体失效
INSTALLED_PROPERTY = "maitux_setupmenu_installed"

# 浏览器层名称（profiles/default/browserlayer.xml 中的 name）
BROWSER_LAYER_NAME = "maitux.setupmenu"

# 用户端 Setup 界面视图名（非管理员齿轮按钮指向这里）
USER_SETUP_VIEW = "@@maitux-setup"

# 管理界面视图名（Site Setup configlet 指向这里）
MANAGEMENT_VIEW = "@@maitux-setupmenu"

# 管理界面中不可分配给菜单的系统角色
HIDDEN_ROLES = [
    "Anonymous",
    "Authenticated",
    "Client",
    "ClientGuest",
    "Contributor",
    "Editor",
    "Member",
    "Owner",
    "Reader",
    "Reviewer",
    "Site Administrator",
]

# 管理员角色（不受菜单过滤影响，右上角齿轮进入原 @@lims-setup）
#
# 注意：不要用 "senaite.core: Manage Bika" 权限判定管理员 —— 该权限
# 授给了 LabClerk / LabManager / Manager，会把普通角色也当成管理员，
# 导致这些账号绕过菜单过滤、始终看到全部菜单。
ADMIN_ROLES = [
    "Manager",
    "Site Administrator",
]
