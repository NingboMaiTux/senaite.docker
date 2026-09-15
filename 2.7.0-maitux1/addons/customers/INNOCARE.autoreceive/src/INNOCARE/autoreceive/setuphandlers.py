# -*- coding: utf-8 -*-
"""安装 / 卸载处理。"""

from bika.lims import api

from INNOCARE.autoreceive import logger

# browserlayer.xml 里注册的层名
LAYER_NAME = "INNOCARE.autoreceive"


def setup_handler(context):
    """安装后处理：把全站的「Autoreceive samples」置为不勾选。

    核心只有**一个**全站开关（Setup → Sampling → Autoreceive samples）来决定
    登样后是否自动接收，无法按 Client 区分。本 addon 按 Client 接管这个判定，
    因此必须把全站开关关掉，否则所有 Client 的样品都会被自动接收，
    「其他部门 / 稳定性须人工接收」就不成立了。

    幂等：已经是不勾选时不做任何事。
    """
    setup = api.get_senaite_setup()
    if setup is None:
        logger.warn("setup_handler: SENAITE setup not found, skipped")
        return

    if setup.getAutoreceiveSamples():
        setup.setAutoreceiveSamples(False)
        logger.info(
            "setup_handler: disabled the site wide 'Autoreceive samples' "
            "setting, auto reception is now driven per client by "
            "INNOCARE.autoreceive")
    else:
        logger.info(
            "setup_handler: site wide 'Autoreceive samples' already disabled")


def uninstall(context):
    """卸载后处理：注销本包的 browser layer。

    注销 layer 是必须的 —— Client / 样品的 schema 扩展与样品列表的
    「接收人」列都靠 layer 门控，layer 留着等于卸载后仍在对所有站点生效。

    另外两件事**刻意不做**：

    - 不把全站「Autoreceive samples」重新勾上：安装时的原值无法可靠还原，
      擅自打开会让所有 Client 的样品再次被自动接收。需要时请人工在
      Setup → Sampling 里自行设置。
    - 不删除 Client 上的 ``AutoReceive`` 字段值（保留业务数据，重装即恢复）。
    """
    try:
        from plone.browserlayer import utils as layer_utils
        layer_utils.unregister_layer(name=LAYER_NAME)
        logger.info("uninstall: unregistered browser layer %s", LAYER_NAME)
    except Exception as exc:
        logger.warn("uninstall: browser layer unregister failed: %s", exc)
