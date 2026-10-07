# -*- coding: utf-8 -*-
"""本包的权限常量与**权限名解析**。

⚠️ 这里有两种"权限名"，别混：

1. **ZCML 的 id 形式**：`maitux.stability.permissions.ManageSampleAutomation`
   —— 用来让 `queryUtility(IPermission, name)` 找得到权限对象
   （`plone.autoform` 的 `directives.write_permission()` 走这条路）。
2. **Zope 真正认的权限名 = ZCML 里的 title**：
   `maitux.stability: Manage Sample Automation`
   —— 站点权限映射（rolemap / 站点后台的角色管理）里的键就是它，
   `checkPermission()` 也认它。

★ 2026-09-30 阶段 5 实测（真机，Cron 专用账号暴露出来的坑）：
   `bika.lims.api.security.check_permission("maitux.stability.permissions.X", obj)`
   里那个函数**并不做** `queryUtility`（它直接 `SecurityManager.checkPermission`），
   所以传 id 形式对**非 Manager 用户一律返回 False**：
   `portal.rolesOfPermission(id_form)` 直接报"不是合法权限"，而
   `portal.rolesOfPermission("maitux.stability: Manage Sample Automation")`
   正常列出 `['BusinessSystemAdministrator', 'LabManager', 'Manager',
   'StabilityAdministrator']`。
   之所以一直"看起来没事"，是因为 Zope 的 ZopeSecurityPolicy 对 **Manager 角色有硬编码放行**
   —— admin 能过，别人全被挡。凡是查权限，都用下面的 :func:`permission_name` 先解析。
"""

# 添加稳定性方案模板（在 configure.zcml 里声明）
AddStabilityPlanTemplate = (
    "maitux.stability.permissions.AddStabilityPlanTemplate"
)

# 管理「样品模板 + 自动登样」的配置：模板/方案上的自动登样开关、联系人，
# 以及站点级设置页（生成时刻、提前天数、零点回溯窗口）。
#
# 这个权限同时管两处，是"权限可配置"的落点：
#   * 字段级 —— 挂在本包 schema 的相关字段上（权限不足时字段不渲染、不可写）
#   * 页面级 —— 站点设置页 @@stability-automation-controlpanel
ManageSampleAutomation = (
    "maitux.stability.permissions.ManageSampleAutomation"
)

# 管理「方案状态」（暂停 / 恢复 / 终止）：阶段 6a 新增。
#
# 两处共用（与 ManageSampleAutomation 同一套路）：
#   * 工作流层 —— senaite_stability_plan_workflow 的三个流转都拿它当 guard；
#   * 页面层   —— browser/planstatus.py 进表单前再校验一次（双门）。
#
# 为什么与 ManageSampleAutomation 给同一批角色：见 rolemap.xml 的注释。
ManagePlanStatus = (
    "maitux.stability.permissions.ManagePlanStatus"
)

# senaite.core 定义的审计页读权限。阶段 6a 要把 StabilityAdministrator 加进去
# （默认只给 LabManager / Manager，本模块自己的管理角色看不到审计页）。
ViewLogTab = "senaite.core: View Log Tab"


def permission_name(permission):
    """把 ZCML 的 id 形式解析成 **Zope 真正认的权限名**（= IPermission 的 title）。

    取不到权限对象（未注册、或本来就是 title/CMF 权限名）时原样返回，绝不抛异常 ——
    调用方拿它去 `check_permission()` 是安全的。

    >>> permission_name("maitux.stability.permissions.ManageSampleAutomation")
    'maitux.stability: Manage Sample Automation'
    >>> permission_name("cmf.ManagePortal")
    'cmf.ManagePortal'
    """
    if not permission:
        return permission
    try:
        from zope.component import queryUtility
        from zope.security.interfaces import IPermission
    except Exception:                                    # pragma: no cover
        return permission
    try:
        utility = queryUtility(IPermission, name=permission)
    except Exception:
        utility = None
    title = getattr(utility, "title", None)
    return title or permission
