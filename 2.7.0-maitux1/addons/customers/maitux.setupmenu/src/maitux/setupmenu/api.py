# -*- coding: utf-8 -*-
"""Setup 菜单的角色分配与可见性判定

所有判定逻辑收敛在本模块，供 ``@@maitux-setup``（用户端过滤）、
``@@maitux-setupmenu``（管理界面）与单元测试复用。
"""

from bika.lims import api
from bika.lims.api.security import get_roles
from plone.registry.interfaces import IRegistry
from zope.component import getUtility

from maitux.setupmenu.config import ADMIN_ROLES
from maitux.setupmenu.interfaces import ISetupMenuRegistry


def get_registry():
    """返回 plone.registry"""
    return getUtility(IRegistry)


def _registry_proxy():
    """返回 ISetupMenuRegistry 的 RecordsProxy"""
    registry = get_registry()
    return registry.forInterface(ISetupMenuRegistry)


def is_admin(user=None):
    """当前用户是否管理员（持有 Manager / Site Administrator 角色）

    管理员始终可见全部菜单，不受角色过滤影响。

    注意：不能用 "senaite.core: Manage Bika" 权限判定管理员 —— 该权限
    授给了 LabClerk / LabManager / Manager（见 core 的 rolemap.xml），
    会把普通角色也当成管理员，导致这些账号绕过菜单过滤。
    """
    roles = get_roles(user) or []
    return bool(set(ADMIN_ROLES) & set(roles))


def is_filtering_enabled():
    """全局过滤开关（默认开启）"""
    try:
        return bool(_registry_proxy().enabled)
    except Exception:  # noqa: B902
        return True


def get_menu_enabled(menu_id):
    """菜单是否启用（默认未启用：除管理员外都不可见）"""
    try:
        return bool(_registry_proxy().menu_enabled.get(menu_id, False))
    except Exception:  # noqa: B902
        return False


def _normalize_roles(roles):
    """把任意形态的角色值归一化为字符串列表

    兼容：list/tuple / 单个字符串（整体作为一个角色，不能拆成字符）。
    用于读取侧容错（历史脏数据）与写入侧清洗。
    """
    if not roles:
        return []
    if isinstance(roles, (list, tuple)):
        out = []
        for role in roles:
            if not role:
                continue
            if isinstance(role, (list, tuple)):
                out.extend(role)
            else:
                out.append(role)
        return out
    # 单值：整体作为一个角色名
    return [roles]


def get_menu_allowed_roles(menu_id):
    """菜单允许的角色列表（未配置返回空列表）"""
    try:
        roles = _registry_proxy().menu_allowed_roles.get(menu_id, ())
        return _normalize_roles(roles)
    except Exception:  # noqa: B902
        return []


def set_filtering_enabled(enabled):
    """写入全局过滤开关"""
    _registry_proxy().enabled = bool(enabled)


def set_menu_config(menu_id, enabled, roles):
    """写入单个菜单的启用状态与允许角色

    未启用或未分配角色的菜单从配置中移除（恢复默认 = 隐藏）。
    """
    proxy = _registry_proxy()
    enabled_map = dict(proxy.menu_enabled or {})
    roles_map = dict(proxy.menu_allowed_roles or {})

    roles = _normalize_roles(roles)
    if enabled:
        enabled_map[menu_id] = True
    else:
        enabled_map.pop(menu_id, None)

    if roles:
        roles_map[menu_id] = tuple(roles)
    else:
        roles_map.pop(menu_id, None)

    proxy.menu_enabled = enabled_map
    proxy.menu_allowed_roles = roles_map


def decide_visibility(menu_enabled, allowed_roles, user_roles,
                      admin=False, filtering=True):
    """纯判定函数（便于单测）

    :param menu_enabled: 菜单是否启用
    :param allowed_roles: 菜单允许的角色列表
    :param user_roles: 用户角色列表/集合
    :param admin: 是否管理员（管理员始终可见）
    :param filtering: 全局过滤开关是否开启
    :returns: True 表示可见
    """
    if admin:
        return True
    if not filtering:
        return True
    if not menu_enabled:
        return False
    return bool(set(allowed_roles) & set(user_roles or []))


def is_menu_visible_for(menu_id, roles, admin=False, filtering=None):
    """菜单对给定角色集合是否可见（含 registry 读取）

    :param menu_id: 菜单 ID
    :param roles: 用户角色集合（可迭代）
    :param admin: 是否管理员
    :param filtering: 全局过滤开关（None 时自动读取）
    """
    if filtering is None:
        filtering = is_filtering_enabled()
    enabled = get_menu_enabled(menu_id)
    allowed = get_menu_allowed_roles(menu_id)
    return decide_visibility(enabled, allowed, roles,
                             admin=admin, filtering=filtering)
