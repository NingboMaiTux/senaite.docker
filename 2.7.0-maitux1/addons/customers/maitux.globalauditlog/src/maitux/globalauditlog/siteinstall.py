# -*- coding: utf-8 -*-
"""当前站点是否安装了本 addon —— 供进程级注册做站点级收口

背景（开发规则 R14 第二条通道）：ZCML 注册是整个 Zope 实例级的，启动即生效；
GenericSetup profile 的安装是站点级的。两者不挂钩，于是本包
`configure.zcml` 里那个

    <subscriber for="senaite.core.interfaces.ISetup
                    zope.lifecycleevent.interfaces.IObjectModifiedEvent" ...>

会在**所有**站点触发，包括从没装过 maitux.globalauditlog 的站点 ——
而它做的事是「把设置里的全局审计日志打开」，那是**写别人的站点配置**。

这个订阅器的签名里没有 request，R14 的 ZCML 门控（把 IBrowserRequest
换成自己的 layer）在这里无处可插，只能在处理函数内部做站点级判定，
未安装就放行。判断口径沿用 `maitux.esignature/siteinstall.py`（同一环境里
已经踩过并单测过的写法），只是这里不需要按请求缓存 —— 本订阅器每次
设置对象被改写才跑一次，不像 guard 那样每行每 transition 跑一遍。
"""

try:
    from Products.CMFCore.utils import getToolByName
    from zope.component.hooks import getSite
except ImportError:  # pragma: no cover - 纯逻辑单测会在 Zope 之外加载本模块
    getToolByName = None
    getSite = None

from maitux.globalauditlog import PROFILE_ID
from maitux.globalauditlog import PROJECTNAME

# portal_setup 对没装过的 profile 返回字符串 "unknown"，装过则返回版本，
# 实测可能是版本元组，例如 (u'1000',)。
UNKNOWN_PROFILE_VERSION = "unknown"


def is_profile_version_installed(version):
    """纯判定：portal_setup 返回的 profile 版本是否代表「已安装」"""
    if not version:
        return False
    if isinstance(version, (tuple, list)):
        values = [item for item in version if item]
        if not values:
            return False
        return list(values) != [UNKNOWN_PROFILE_VERSION]
    return version != UNKNOWN_PROFILE_VERSION


def query_site_installed(site):
    """不带缓存地问一次站点：本 addon 的 profile 装了没有

    先问 portal_quickinstaller —— 它维护的是 Add-ons 面板安装/卸载的那份记录，
    也是判断「这个站点要不要本 addon」最贴切的语义。取不到再退回
    portal_setup 的 profile 版本。
    """
    if site is None or getToolByName is None:
        return False

    quickinstaller = getToolByName(site, "portal_quickinstaller", None)
    if quickinstaller is not None:
        try:
            return bool(quickinstaller.isProductInstalled(PROJECTNAME))
        except Exception:
            pass

    setup_tool = getToolByName(site, "portal_setup", None)
    if setup_tool is None:
        return False
    try:
        version = setup_tool.getLastVersionForProfile(PROFILE_ID)
    except Exception:
        return False
    return is_profile_version_installed(version)


def is_installed_in_current_site():
    """本 addon 是否安装在当前站点。取不到站点时按未安装处理（不动它）。"""
    if getSite is None:
        return False
    try:
        return query_site_installed(getSite())
    except Exception:
        return False
