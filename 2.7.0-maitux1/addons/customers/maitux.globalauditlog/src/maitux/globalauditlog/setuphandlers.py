# -*- coding: utf-8 -*-
"""安装 / 卸载处理

安装：把设置里的「启用全局审计日志」打开（幂等）。
卸载：**故意不动这个开关** —— 理由见 uninstall_handler 的 docstring。
"""

from Products.CMFPlone.interfaces import INonInstallable
from bika.lims import api
from maitux.globalauditlog import PROJECTNAME
from senaite.core import logger
from zope.interface import implementer


@implementer(INonInstallable)
class HiddenProfiles(object):
    """隐藏卸载 Profile，保持 Add-ons 面板整洁。"""

    def getNonInstallableProfiles(self):  # noqa camelCase
        return [
            "%s:uninstall" % PROJECTNAME,
        ]

    def getNonInstallableProducts(self):  # noqa camelCase
        return []


def enable_global_auditlog():
    """把全局审计日志打开；已经是 True 就什么都不做（幂等）

    ★ 只在 False 时写。core 的 setter 收到 False 会
      `manage_catalogClear()` 清空审计目录 —— 我们永远只写 True，
      不碰那条分支；重复写也没意义（每次写都触发一次
      IObjectModifiedEvent，连带重算子对象权限等订阅者）。

    :returns: 调用结束时开关是否为「开」
    """
    try:
        setup = api.get_senaite_setup()
    except Exception as exc:
        # 建站早期 / 无站点上下文：不抛，让安装继续走完。
        logger.warning(
            "maitux.globalauditlog: cannot get SENAITE setup: %s", exc)
        return False

    if setup is None:
        logger.warning(
            "maitux.globalauditlog: SENAITE setup not found, "
            "global auditlog left unchanged")
        return False

    try:
        if setup.getEnableGlobalAuditlog():
            logger.info(
                "maitux.globalauditlog: global auditlog already enabled")
            return True
        setup.setEnableGlobalAuditlog(True)
    except Exception as exc:
        logger.error(
            "maitux.globalauditlog: failed to enable global auditlog: %s", exc)
        return False

    logger.info("maitux.globalauditlog: global auditlog enabled")
    return True


def setup_handler(context):
    """标准插件安装入口。"""
    install_file = "%s.txt" % PROJECTNAME
    if context.readDataFile(install_file) is None:
        return

    logger.info("Maitux.Globalauditlog setup handler [BEGIN]")
    enable_global_auditlog()
    logger.info("Maitux.Globalauditlog setup handler [DONE]")


def import_various(context):
    """兼容旧入口，统一委托到标准安装入口。"""
    setup_handler(context)


def uninstall_handler(context):
    """标准插件卸载入口。

    ★ 卸载**故意不把开关关掉**：

    1. 关掉就等于清空审计目录（core 的 setter 在 False 分支里
       `manage_catalogClear()`）—— 卸载一个「显示层」插件不该毁掉审计记录；
    2. 审计追踪是否开启在法规上不由用户决定（见 R4b 对合规类 addon 的口径），
       本包卸载后设置页面只是重新显示那个复选框，值仍是「开」，
       由管理员显式决定要不要关。

    卸载要清掉的东西只有 profile 级注册（browserlayer 等），
    GenericSetup 自己会处理，这里没有额外状态可清。
    """
    uninstall_file = "%s-uninstall.txt" % PROJECTNAME
    if context.readDataFile(uninstall_file) is None:
        return

    logger.info("Maitux.Globalauditlog uninstall handler [BEGIN]")
    logger.info(
        "Maitux.Globalauditlog: 'enable_global_auditlog' left as-is "
        "(not disabling the auditlog on uninstall)")
    logger.info("Maitux.Globalauditlog uninstall handler [DONE]")
