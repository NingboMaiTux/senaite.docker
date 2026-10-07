# -*- coding: utf-8 -*-
"""稳定性「自动登样」站点设置页（plone.app.registry + Site Setup 入口）。

入口：Site Setup → Products → **Stability Sample Automation**
URL：``<站点>/@@stability-automation-controlpanel``

⭐ 关于权限（这里刻意不用 `cmf.ManagePortal`）
--------------------------------------------

本包走 `package-includes/*-configure.zcml`（`site.zcml` **第 15 行**）加载，
而 `cmf.*` 权限由 `Products.CMFCore` 在**第 16 行** `five:loadProducts` 才注册。
把 `permission="cmf.ManagePortal"` 写进 `configure.zcml`，
`protectClass` 会找不到 `IPermission` → `ComponentLookupError` → **Zope 起不来**
（2026-09-28 线上就是这么炸的，见 README「坑 1」与开发规则 R1 订正）。

所以这里的做法与同包另外几个页面一致：

* ZCML 只写 ``permission="zope2.View"``（`zope2.*` 由第 6 行的 `Products.Five` 注册，安全）；
* **真正的权限校验在本文件 `can_manage()` 里二次完成**。

另有一条等价写法（`maitux.oauth2` 用的）：在 `configure.zcml` 顶部
``<include package="Products.CMFCore" file="permissions.zcml" />`` 把 `cmf.*`
的注册钉在自己前面。两种都行，本包统一走"zope2.View + 二次校验"。
"""

from bika.lims.api.security import check_permission
from plone.app.registry.browser import controlpanel
from plone import api as ploneapi
from zExceptions import Unauthorized

from maitux.stability import stabilityMessageFactory as _
from maitux.stability.automation import IStabilityAutomationSettings
from maitux.stability.automation import REGISTRY_PREFIX
from maitux.stability.automation import ensure_records
from maitux.stability.permissions import ManageSampleAutomation
from maitux.stability.permissions import permission_name


try:
    from plone.protect.interfaces import IDisableCSRFProtection
except Exception:  # pragma: no cover
    IDisableCSRFProtection = None


def _disable_csrf(request):
    """本页在 GET 上补 registry 记录（一次合法的 ZODB 写入）。"""
    if IDisableCSRFProtection is not None:
        try:
            from zope.interface import alsoProvides
            alsoProvides(request, IDisableCSRFProtection)
        except Exception:
            pass


def can_manage(context):
    """是否有权打开/保存本设置页。

    ★ 权限名必须**先解析成 Zope 真正认的名字**（= ZCML 的 title 形式）：
    实测（2026-09-30）`check_permission()` 直接 `SecurityManager.checkPermission()`，
    **不做** `queryUtility` —— 传 ZCML 的 id 形式时，站点权限映射里没有这个键，
    非 Manager 用户**一律被拒**；admin 之所以一直能过，是 Zope 对 Manager 角色硬编码放行。
    详见 `maitux/stability/permissions.py` 的模块注释与 `permission_name()`。

    另外留两条兜底：
    * ``cmf.ManagePortal`` —— 站点管理员本来就该能改这些全局设置；
    * ``Manager`` 角色 —— 万一 rolemap 还没重跑（本权限尚未授给任何角色），
      不能把管理员自己锁在设置页外面。
    """
    for name in (permission_name(ManageSampleAutomation), "cmf.ManagePortal"):
        try:
            if check_permission(name, context):
                return True
        except Exception:
            continue
    try:
        roles = set(ploneapi.user.get_current().getRolesInContext(context))
        if "Manager" in roles:
            return True
    except Exception:
        pass
    return False


class StabilityAutomationSettingsEditForm(controlpanel.RegistryEditForm):
    """设置表单本体。"""

    schema = IStabilityAutomationSettings
    schema_prefix = REGISTRY_PREFIX
    label = _(u"Stability Sample Automation")

    @property
    def description(self):
        return _(u"Site wide defaults for the automatic sample creation of "
                 u"stability studies. The generation time is read from here, "
                 u"so changing it does not require touching the server "
                 u"scheduler.")

    def getContent(self):
        # plone.app.registry 的 getContent() 对"没有记录的新字段"会抛 KeyError，
        # 整页 500。这里先自愈补记录（幂等），再交给父类。
        # 与 maitux.oauth2 的同款处理一致。
        if ensure_records():
            _disable_csrf(self.request)
        return super(StabilityAutomationSettingsEditForm, self).getContent()


class StabilityAutomationSettingsView(controlpanel.ControlPanelFormWrapper):
    """设置页外壳（FormWrapper）。"""

    form = StabilityAutomationSettingsEditForm

    def __call__(self, *args, **kwargs):
        # ⚠️ 权限必须在这里补：ZCML 只能声明 zope2.View，
        # 少了这一句，任何能看站点的人都能打开并保存全站自动登样口径。
        if not can_manage(self.context):
            raise Unauthorized(
                "You are not allowed to manage the stability sample "
                "automation settings.")
        return super(StabilityAutomationSettingsView, self).__call__(
            *args, **kwargs)
