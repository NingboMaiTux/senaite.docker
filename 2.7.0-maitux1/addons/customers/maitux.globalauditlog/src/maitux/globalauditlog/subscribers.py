# -*- coding: utf-8 -*-
"""设置对象被改写后，把「启用全局审计日志」钉回开启

界面那一侧（`browser/senaitesetup.py`）只在「人用设置表单保存」这条路上成立。
这里兜住其余所有改写路径：ZMI、jsonapi、别的 addon 直接调 setter。
"""

from maitux.globalauditlog.siteinstall import is_installed_in_current_site
from senaite.core import logger


def on_senaite_setup_modified(senaite_setup, event):
    """SENAITE 设置对象保存后：若全局审计日志被关掉，立刻打开

    只在**当前值确实是 False** 时才写，因此不会事件递归：写入本身会再触发
    一次本订阅者，那一次读到的已经是 True，直接返回。

    ★ 为什么不用 `setEnableGlobalAuditlog(False)` 做「关掉」这件事的拦截：
      core 的 setter 收到 False 时会 `manage_catalogClear()` 清空审计目录，
      那一步发生在本事件之前 —— 真有人绕到那条路，目录已经被清了，
      这里只能把开关拨回来。要拦在清空之前得 monkey patch core，
      代价（R10：不碰数据与工作流；随 core 升级漂移）大于收益。
      设置页面上该字段已隐藏且强制勾选，正常路径到不了那里。
    """
    # 未安装本 profile 的站点：本包 ZCML 是全局加载的，这个订阅者同样会跑，
    # 但绝不能去改别人的站点配置（R14）。
    if not is_installed_in_current_site():
        return

    try:
        if senaite_setup.getEnableGlobalAuditlog():
            return
    except Exception as exc:
        # 读不出来就别猜（比如建站早期的半成品对象），但要说一声：
        # 这里静默 return 会让「兜底没生效」变成没人知道的事（R9）。
        logger.warning(
            "maitux.globalauditlog: cannot read enable_global_auditlog: %s",
            exc)
        return

    logger.warning(
        "maitux.globalauditlog: global auditlog was disabled, enabling again")
    senaite_setup.setEnableGlobalAuditlog(True)
