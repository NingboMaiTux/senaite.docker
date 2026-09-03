# -*- coding: utf-8 -*-
"""安装/卸载处理器

本 add-on 不创建内容类型，仅注册浏览器视图（工具栏覆盖 +
两个 Setup 界面）。安装/卸载时需要维护：

  1. 安装标记（portal property）
     浏览器层在卸载时可能残留（依赖 plone.browserlayer 行为），
     功能渲染会检查该标记，保证卸载后 UI 立即失效。

  2. 浏览器层移除
     尽力从 portal_skins 移除本 add-on 的浏览器层，使视图覆盖
     在卸载后整体失效。

  3. Site Setup configlet 移除
     卸载时从 portal_controlpanel 注销 "Menu Management" 配置项。
"""

from Products.CMFCore.utils import getToolByName
from Products.CMFPlone.interfaces import INonInstallable
from senaite.core import logger
from zope.interface import implementer

from maitux.setupmenu.config import BROWSER_LAYER_NAME
from maitux.setupmenu.config import INSTALLED_PROPERTY
from maitux.setupmenu.config import PROJECTNAME

# portal_controlpanel 中 configlet 的 action_id（见 profiles/default/controlpanel.xml）
CONFIGLET_ID = PROJECTNAME


@implementer(INonInstallable)
class HiddenProfiles(object):
    """隐藏卸载 Profile，避免 Add-ons 面板重复显示。"""

    def getNonInstallableProfiles(self):  # noqa camelCase
        return [
            "%s:uninstall" % PROJECTNAME,
        ]

    def getNonInstallableProducts(self):  # noqa camelCase
        return []


def setup_handler(context):
    """标准插件安装入口。"""
    install_file = "%s.txt" % PROJECTNAME
    if context.readDataFile(install_file) is None:
        return

    logger.info("maitux.setupmenu setup handler [BEGIN]")
    portal = context.getSite()
    run_install_steps(portal)
    logger.info("maitux.setupmenu setup handler [DONE]")


def run_install_steps(portal):
    """按标准插件方式编排安装步骤。"""
    _set_installed_marker(portal, True)


def uninstall_handler(context):
    """标准插件卸载入口。"""
    uninstall_file = "%s-uninstall.txt" % PROJECTNAME
    if context.readDataFile(uninstall_file) is None:
        return

    logger.info("maitux.setupmenu uninstall handler [BEGIN]")
    portal = context.getSite()
    run_uninstall_steps(portal)
    logger.info("maitux.setupmenu uninstall handler [DONE]")


def run_uninstall_steps(portal):
    """编排卸载步骤。"""
    # 1. 清除安装标记 -> 功能 UI 立即失效
    _set_installed_marker(portal, False)
    # 2. 移除浏览器层 -> 视图覆盖整体失效（齿轮行为、Setup 界面不可再访问）
    _remove_browser_layer(portal)
    # 3. 注销 Site Setup configlet（registry 记录由 uninstall profile 移除）
    _remove_configlet(portal)


def _set_installed_marker(portal, installed):
    """写入/清除安装标记（portal property）"""
    try:
        if installed:
            if not portal.hasProperty(INSTALLED_PROPERTY):
                portal.manage_addProperty(
                    INSTALLED_PROPERTY, True, "boolean")
        else:
            if portal.hasProperty(INSTALLED_PROPERTY):
                portal.manage_delProperties([INSTALLED_PROPERTY])
    except Exception as exc:  # noqa: B902
        logger.warn(
            "maitux.setupmenu: could not %s installed marker: %s"
            % ("set" if installed else "remove", exc))


def _remove_browser_layer(portal):
    """尽力移除浏览器层，使 layer 上的视图注册不再命中请求"""
    try:
        skinstool = getToolByName(portal, "portal_skins")
    except Exception as exc:  # noqa: B902
        logger.warn(
            "maitux.setupmenu: could not get portal_skins: %s" % exc)
        return

    layer_id = BROWSER_LAYER_NAME

    # 首选 plone.browserlayer 约定的皮肤工具 API（Plone 5）
    remove = getattr(skinstool, "delSkinLayer", None)
    if callable(remove):
        try:
            remove(layer_id)
            logger.info(
                "maitux.setupmenu: removed browser layer '%s' "
                "via delSkinLayer" % layer_id)
            return
        except Exception as exc:  # noqa: B902
            logger.warn(
                "maitux.setupmenu: delSkinLayer failed: %s" % exc)

    # 兜底：直接删除 portal_skins 中同名的 layer 对象
    try:
        if layer_id in skinstool.objectIds():
            skinstool.manage_delObjects([layer_id])
            logger.info(
                "maitux.setupmenu: removed browser layer '%s' "
                "via manage_delObjects" % layer_id)
    except Exception as exc:  # noqa: B902
        logger.warn(
            "maitux.setupmenu: manage_delObjects failed: %s" % exc)


def _remove_configlet(portal):
    """从 portal_controlpanel 注销 Menu Management configlet"""
    try:
        cp = getToolByName(portal, "portal_controlpanel")
    except Exception as exc:  # noqa: B902
        logger.warn(
            "maitux.setupmenu: could not get portal_controlpanel: %s" % exc)
        return
    try:
        if hasattr(cp, "unregisterConfiglet"):
            cp.unregisterConfiglet(CONFIGLET_ID)
            logger.info(
                "maitux.setupmenu: unregistered configlet '%s'" % CONFIGLET_ID)
            return
        # 兜底：按 action id 删除
        if cp.getActionById(CONFIGLET_ID) is not None:
            cp.manage_delActions([CONFIGLET_ID])
            logger.info(
                "maitux.setupmenu: removed configlet action '%s'" % CONFIGLET_ID)
    except Exception as exc:  # noqa: B902
        logger.warn(
            "maitux.setupmenu: could not remove configlet '%s': %s"
            % (CONFIGLET_ID, exc))
