# -*- coding: utf-8 -*-
u"""每天凌晨自己跑一次用户同步。

为什么调度放在 add-on 里，而不是 clock-server 或外部 cron：

* Zope 的 ``<clock-server>`` 只能表达「进程起来之后每 N 秒一次」，每重启一次
  容器时间就漂一次，定不到「凌晨两点」这种钟点；
* 外部 cron / 计划任务要在每个客户现场单独配一遍，还要多维护一个触发口令。

「统一登录」和「启用用户同步」两个开关都开着，就该每天凌晨自己跑起来 ——
这是产品行为，不该落到部署步骤里。关掉任一开关就是关掉调度，不用改配置、
不用进容器。

两个实例共用同一个库，所以两边的线程都会醒。谁先把 ``last_sync`` 写成今天，
谁就算抢到了这一轮：另一边要么读到新值直接跳过，要么在提交时撞上
ConflictError —— 两种情况都不会重复同步。

Zope 那一堆 import 刻意写在函数里：这样这个模块在没有 Zope 的解释器里也能
import，``due()`` 这个唯一值得测的判断才测得动（见 tests.py）。
"""

import threading
import time
from datetime import datetime

from maitux.oauth2 import config
from maitux.oauth2 import logger
from maitux.oauth2 import safe_text

#: 多久醒一次看看到点没。窗口是整个钟点，所以 5 分钟足够准，
#: 又不至于让一个常年空转的线程频繁开数据库连接。
CHECK_INTERVAL = 300

#: 默认凌晨 2 点。0-23，可在控制面板或 MAITUX_OAUTH2_SYNC_AT_HOUR 里改。
DEFAULT_HOUR = 2

_started = False
_start_lock = threading.Lock()


def scheduled_hour():
    hour = config.get("sync_at_hour")
    try:
        hour = int(hour)
    except (TypeError, ValueError):
        return DEFAULT_HOUR
    if hour < 0 or hour > 23:
        return DEFAULT_HOUR
    return hour


def due(now, hour, last_sync):
    u"""到点了没。

    ``last_sync`` 是 registry 里那个 ``YYYY-mm-dd HH:MM:SS``。只比日期：
    今天已经跑过就不再跑，哪怕是手动触发的那一次。
    """
    if now.hour != hour:
        return False
    return (last_sync or u"")[:10] != now.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 线程
# ---------------------------------------------------------------------------


def start(event=None):
    u"""``IDatabaseOpenedWithRoot`` 的订阅器：每个进程起一个线程，只起一次。"""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    thread = threading.Thread(target=_loop)
    thread.name = "maitux.oauth2.scheduler"
    # daemon：关容器时不许它拖住退出。
    thread.daemon = True
    thread.start()
    logger.info("Nightly user sync scheduler started, checking every %s s",
                CHECK_INTERVAL)


def _loop():
    while True:
        # 先睡再干：实例刚起来时 buildout 可能还在收尾，站点不一定就绪。
        time.sleep(CHECK_INTERVAL)
        try:
            tick()
        except Exception as exc:  # 线程绝不能因为一轮出错就死掉
            logger.warning("Nightly sync tick failed: %s", safe_text(exc))


def tick(now=None):
    u"""跑一轮检查，返回这一轮真正同步了的站点 id 列表。"""
    import transaction
    import Zope2
    from Products.CMFPlone.interfaces import IPloneSiteRoot

    now = now or datetime.now()
    done = []
    app = Zope2.app()
    try:
        for site in app.objectValues():
            if not IPloneSiteRoot.providedBy(site):
                continue
            if _run_for(site, now):
                done.append(site.getId())
    finally:
        # 连接上还挂着未提交的改动就关，ZODB 会直接抛「Cannot close a
        # connection joined to a transaction」，把下一轮也带崩。
        try:
            transaction.abort()
            app._p_jar.close()
        except Exception:  # pragma: no cover
            pass
    return done


def _run_for(site, now):
    u"""一个站点的一轮。真跑了返回 True。"""
    import transaction
    from AccessControl.SecurityManagement import newSecurityManager
    from AccessControl.SecurityManagement import noSecurityManager
    from ZODB.POSException import ConflictError
    from zope.component.hooks import setSite

    try:
        from AccessControl.SpecialUsers import system as system_user
    except ImportError:  # pragma: no cover - 老版本 AccessControl
        from AccessControl.User import system as system_user

    setSite(site)
    try:
        if not due(now, scheduled_hour(), config.get("last_sync")):
            return False
        if not config.is_enabled() or not config.get("sync_enabled"):
            return False

        # 先把 last_sync 占上再跑。另一个实例要么读到今天的日期直接跳过，
        # 要么在这里撞 ConflictError —— 两种都不会重复同步。一天只试一次：
        # 竹云那边刚好不可用就等明天，好过在凌晨反复敲对方的接口。
        newSecurityManager(None, system_user)
        try:
            config.set_value("last_sync", now.strftime("%Y-%m-%d %H:%M:%S"))
            transaction.commit()
        except ConflictError:
            transaction.abort()
            logger.info("Another instance took tonight's sync for %s", site.getId())
            return False

        logger.info("Nightly user sync starting for %s", site.getId())
        from maitux.oauth2 import sync
        try:
            stats = sync.sync_users(site)
            transaction.commit()
        except Exception as exc:
            transaction.abort()
            logger.error("Nightly user sync failed for %s: %s",
                         site.getId(), safe_text(exc))
            return False
        logger.info("Nightly user sync done for %s: created=%s disabled=%s "
                    "errors=%s", site.getId(), stats.get("created"),
                    stats.get("disabled"), len(stats.get("errors") or []))
        return True
    finally:
        noSecurityManager()
        setSite(None)
