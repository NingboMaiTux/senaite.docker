# -*- coding: utf-8 -*-
"""安装/卸载处理器

安装（setup_handler）：
1. 前置检查：stock 模块（maitux.stock / StockBatch 类型）必须已安装，
   否则抛错终止安装（需求：安装前需确认 stock 模块在不在）。
2. 将 Worksheet 多选行为挂到 Worksheet FTI（enable_behavior），
   使所有 Worksheet 对象获得 instruments / stock_batches 两个新字段。

卸载（uninstall_handler）：
- 从 Worksheet FTI 摘掉行为（disable_behavior）；
- 已写入对象上的旧值作为普通持久化属性保留（不主动删数据）。
"""

from Products.CMFPlone.interfaces import INonInstallable
from bika.lims import api
from senaite.core import logger
from zope.interface import implementer

from maitux.worksheetfields.config import PROJECTNAME
from maitux.worksheetfields.config import STOCK_BATCH_PORTAL_TYPE
from maitux.worksheetfields.config import STOCK_DISTRIBUTION_NAME
from maitux.worksheetfields.config import WORKSHEET_MULTISELECT_BEHAVIOR


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

    logger.info("Maitux.Worksheetfields setup handler [BEGIN]")
    portal = context.getSite()
    run_install_steps(portal)
    logger.info("Maitux.Worksheetfields setup handler [DONE]")


def run_install_steps(portal):
    """编排安装步骤（必须先做 stock 模块检查，再改动任何状态）"""
    ensure_stock_module_installed(portal)
    setup_behaviors()


def ensure_stock_module_installed(portal):
    """前置检查：库存模块必须已安装（本功能依赖 StockBatch 类型）。

    判定方式（任选其一通过即可）：
    1. portal_quickinstaller.isProductInstalled("maitux.stock")
    2. portal_types 中存在 "StockBatch" FTI

    失败时抛出 RuntimeError，安装流程以明确错误终止，不会留下半安装状态。
    """
    logger.info("*** Check Stock Module Availability ***")
    if is_stock_module_available(portal):
        logger.info("Stock module detected (maitux.stock / StockBatch)")
        return

    message = (
        u"Cannot install maitux.worksheetfields: the stock module "
        u"(maitux.stock, portal type '%s') is not installed. Please install "
        u"the stock module first and run the install again. / "
        u"无法安装 maitux.worksheetfields：未检测到库存模块（maitux.stock / "
        u"StockBatch 类型），请先安装库存模块后再重试。"
        % STOCK_BATCH_PORTAL_TYPE
    )
    logger.error(api.to_utf8(message))
    raise RuntimeError(api.to_utf8(message))


def is_stock_module_available(portal):
    """返回 stock 模块是否可用"""
    # 1) quickinstaller：产品已安装
    try:
        qi = api.get_tool("portal_quickinstaller")
        if qi is not None and qi.isProductInstalled(STOCK_DISTRIBUTION_NAME):
            return True
    except Exception:
        pass

    # 2) portal_types 中存在 StockBatch FTI（覆盖未走 quickinstaller 的安装）
    try:
        types_tool = api.get_tool("portal_types")
        if types_tool is not None and \
                types_tool.getTypeInfo(STOCK_BATCH_PORTAL_TYPE) is not None:
            return True
    except Exception:
        pass

    return False


def setup_behaviors():
    """启用 Worksheet 多选行为（仪器 + 库存批次字段）"""
    logger.info("*** Setup Worksheet Multi-Select Behavior ***")
    api.enable_behavior("Worksheet", WORKSHEET_MULTISELECT_BEHAVIOR)
    logger.info("Enabled behavior '%s' on 'Worksheet'",
                WORKSHEET_MULTISELECT_BEHAVIOR)


def uninstall_handler(context):
    """标准插件卸载入口。"""
    uninstall_file = "%s-uninstall.txt" % PROJECTNAME
    if context.readDataFile(uninstall_file) is None:
        return

    logger.info("Maitux.Worksheetfields uninstall handler [BEGIN]")
    try:
        api.disable_behavior("Worksheet", WORKSHEET_MULTISELECT_BEHAVIOR)
        logger.info("Disabled behavior '%s' on 'Worksheet'",
                    WORKSHEET_MULTISELECT_BEHAVIOR)
    except Exception:
        logger.warn("Could not disable behavior '%s' on 'Worksheet'",
                    WORKSHEET_MULTISELECT_BEHAVIOR, exc_info=True)
    logger.info("Maitux.Worksheetfields uninstall handler [DONE]")


def setup_worksheetfields_content(context):
    """兼容旧入口，统一委托到标准安装入口。"""
    setup_handler(context)


def uninstall(context):
    """兼容旧入口，统一委托到标准卸载入口。"""
    uninstall_handler(context)
