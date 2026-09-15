# -*- coding: utf-8 -*-
"""登样后按 Client 自动接收。

核心 `create_analysisrequest()` 在样品创建末尾会 `notify(ObjectInitializedEvent)`，
AR 新增页（登样）、稳定性任务板的「创建样品」、以及任何走 API 的创建路径
都会经过这里，所以只订阅这一个事件就能覆盖全部登样入口。

判定口径（与核心的全局自动接收保持一致）：
- Client 勾选了「自动接收」→ 直接复用核心的 `receive_sample()`
  把样品置为 `sample_received`（同时写接收时间、写工作流接收人）；
- 未勾选 → 什么都不做，样品停在 `sample_due`（待接收），
  由人到列表里点「接收」，核心工作流据此写入接收时间与接收人。

★ R14：本订阅者的签名里没有 request，ZCML 无处插 `layer=`，
  而 `package-includes/` 的注册是**全局**的 —— 必须在这里运行时判本包
  browser layer，否则没装本 addon 的站点也会被自动接收。
"""

from bika.lims import api
from bika.lims.interfaces import IReceived
from bika.lims.utils.analysisrequest import receive_sample
from senaite.core.api.workflow import check_guard
from senaite.core.permissions.sample import can_receive

from INNOCARE.autoreceive import logger
from INNOCARE.autoreceive.interfaces import IAutoReceiveLayer

# 核心创建样品时使用的初始状态（无需采样流程时落在这一状态）
SAMPLE_DUE = "sample_due"

# Client 上由本 addon 添加的字段名
AUTO_RECEIVE_FIELD = "AutoReceive"


def is_addon_installed(sample):
    """本 addon 是否在当前请求上下文生效（等价于「本站点装了没装」）。

    browser layer 由 `profiles/default/browserlayer.xml` 在装 profile 时挂上，
    所以"层在不在"就是"装了没装"。
    """
    request = getattr(sample, "REQUEST", None)
    if request is None:
        return False
    return IAutoReceiveLayer.providedBy(request)


def client_auto_receives(sample):
    """样品所属 Client 是否勾选了「自动接收」

    ★ 必须通过 Schema 取字段再取值，不能写成 ``client.getAutoReceive()``：
      schemaextender 的扩展字段**不会**在内容类上生成 getXxx 方法
      （`ExtensionField` 混入的 `BaseExtensionField.getAccessor()` 直接返回
      `self.get(instance)`），所以类上根本不存在这个方法。
    """
    client = sample.getClient()
    if client is None:
        return False

    field = client.Schema().getField(AUTO_RECEIVE_FIELD)
    if field is None:
        return False

    return bool(field.get(client))


def after_sample_created(sample, event):
    """样品创建后：Client 勾选了「自动接收」则直接进入已接收状态

    由 `configure.zcml` 的 `<subscriber handler=... />` 直接调用，
    所以这里是普通函数（不加 `@adapter`，与 senaite.core 的
    `subscribers.client.on_client_created` 同一写法）。
    """
    # ★ 没装本 addon 的站点：什么都不做（见模块 docstring / R14）
    if not is_addon_installed(sample):
        return

    # 已经接收过的（二次取样、分区等）不再处理
    if IReceived.providedBy(sample):
        return

    # 只处理核心刚创建出来、停在「待接收」的样品
    if api.get_workflow_status_of(sample) != SAMPLE_DUE:
        return

    # 需采样流程的样品由核心先推到 to_be_sampled，这里不介入
    if sample.getSamplingRequired():
        return

    if not client_auto_receives(sample):
        return

    # 与核心的全局自动接收一致：权限 / 守卫不通过就不动
    if not can_receive(sample):
        logger.warn(
            "auto receive skipped for %s: current user has no permission to "
            "receive samples" % sample.getId())
        return
    if not check_guard(sample, "receive"):
        logger.warn(
            "auto receive skipped for %s: the 'receive' guard did not pass "
            "(e.g. 'Date Sampled' is required in this site)"
            % sample.getId())
        return

    receive_sample(sample)
    logger.info(
        "auto received sample %s (client=%s)"
        % (sample.getId(), api.get_uid(sample.getClient())))
