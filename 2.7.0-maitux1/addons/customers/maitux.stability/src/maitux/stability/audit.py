# -*- coding: utf-8 -*-
"""稳定性方案的**审计追踪**唯一入口（快照 + 状态流水）。

为什么必须有这个模块
--------------------

平台的审计机制（``senaite.core.snapshots`` annotation + ``@@auditlog`` 页）只在
**新增 / 编辑 / 工作流流转**时自动拍快照（``bika/lims/subscribers/auditlog.py``）。
而本模块自己的写操作是"直接改字段 + ``reindexObject()``"——
**不触发 ``IObjectModifiedEvent``，所以一条快照都不产生**：

* ``samplegeneration.py`` 的登样 / 零点关联 / 撤销登样三处写回；
* ``browser/view.py`` 的「样品放置」写回；
* ``plan_status`` 的状态变更（这一处好在是工作流流转，会自动产生快照，
  但"万一没产生"也要有兜底）。

于是这些动作此前只有行上的自制字段（``generated_at`` / ``revoked_at`` …）与日志，
**在平台审计页里完全看不到**。本模块把缺口补上，并按设计决策 D8 收敛成
**唯一写入口** :func:`record_plan_audit` —— 所有写路径都走它，不得各写一份。

本仓库的现成先例
----------------

``maitux.stock/usageapproval.py`` 的 ``append_batch_audit_snapshot()``
就是为同一个问题写的，它注释里记着三个坑，本模块照抄那套做法：

1. 直接改字段 + ``reindexObject()`` 不触发事件 -> 必须显式 ``take_snapshot``；
2. ``get_object_data()`` 有 **RAM 缓存**（键 = uid + review_state + 修改时间），
   不先推进修改时间就可能把**改动前**的数据写成快照；
3. ``take_snapshot(actor=None)`` 会用 None **覆盖**自动识别的当前用户。
   所以 actor 只有真给了才传这个 kwarg。

另加一个平台实现上的坑：``take_snapshot(store=True)`` 是**先存再返回**，
想在快照里塞额外字段（``timepoint`` / ``sample_uid``）就来不及 ——
所以这里用 ``store=False`` 拿回快照、``update(extra)`` 之后再自己存。
"""

import json

from senaite.core import logger

from maitux.stability.sampleautomation import as_text
from maitux.stability.sampleautomation import format_timestamp


# 状态流水的 annotation 键（与平台自己的 SNAPSHOT_STORAGE 不冲突）。
# 为什么单独存一份而不是只靠审计快照：
#   审计页是给"查账"用的（要一页页翻 diff），业务人员日常只想看
#   "谁、什么时候、把方案从什么状态改成了什么、为什么" —— 那正是这份流水。
#   它是**派生展示数据**，丢了不影响业务，所以用最轻的形态存。
STATUS_HISTORY_KEY = "maitux.stability.plan_status_history"

# 流水最多保留多少条（只截断展示用的流水，**不动审计快照**）。
# 方案生命周期很长的站点上，状态变更次数通常个位数，256 足够；
# 设个上限只是为了不让一次异常循环把 annotation 撑爆。
HISTORY_LIMIT = 256

# 方案级审计动作名（进 Audit Log 的 Action 列）。**英文原样落库，不翻译。**
ACTION_CREATE = u"create"
ACTION_EDIT = u"edit"
ACTION_PAUSE = u"pause"
ACTION_RESUME = u"resume"
ACTION_TERMINATE = u"terminate"
ACTION_GENERATE_SAMPLE = u"generate_sample"
ACTION_LINK_SAMPLE = u"link_sample"
ACTION_REVOKE_SAMPLE = u"revoke_sample"
ACTION_PLACE_SAMPLE = u"place_sample"
ACTION_VOID_TIMEPOINT = u"void_timepoint"
ACTION_SYNC_TASKS = u"sync_tasks"

ACTIONS = (
    ACTION_CREATE,
    ACTION_EDIT,
    ACTION_PAUSE,
    ACTION_RESUME,
    ACTION_TERMINATE,
    ACTION_GENERATE_SAMPLE,
    ACTION_LINK_SAMPLE,
    ACTION_REVOKE_SAMPLE,
    ACTION_PLACE_SAMPLE,
    ACTION_VOID_TIMEPOINT,
    ACTION_SYNC_TASKS,
)


def snapshot_count(obj):
    """对象现有多少条审计快照（取不到时返回 0，绝不抛异常）。

    用途：调用工作流流转前记下数字，流转后再看一次 ——
    ``ObjectTransitionedEventHandler`` **通常**会自动拍一张，
    但"通常"不够，兜底逻辑要靠这个数字判断该不该补。
    """
    if obj is None:
        return 0
    try:
        from bika.lims.api.snapshot import get_snapshot_count
        return int(get_snapshot_count(obj))
    except Exception:
        return 0


def record_plan_audit(plan, action, comments=u"", actor=u"", extra=None):
    """给稳定性方案追加一条审计快照 —— **全模块唯一写入口**。

    :param plan: 方案对象（``StabilityPlan``）
    :param action: 动作名，进审计页的 Action 列（用本模块的 ``ACTION_*`` 常量）
    :param comments: 原因 / 说明（有就进快照 metadata 的 ``comments``）
    :param actor: 指定操作人（**只有真给了才覆盖**，见模块说明的坑 #3）；
        自动登样的定时任务传 ``scheduler``、看板懒触发传 ``lazy-trigger``。
    :param extra: 额外字段，合并进快照（如 ``{"timepoint": 3, "sample": "H2O-0001"}``）。
        这些字段**只在这条快照里有**，不会写进对象 —— 用于"这一次动作针对的是哪一行"。
    :returns: True 表示已写入；对象不支持快照 / 出错时返回 False（**不抛异常**）

    ★ 为什么不抛异常：审计是"动作的附属品"。登样本身成功了却因为审计写不进去
      而整单回滚，对用户来说是更难理解的失败。所以这里一律降级为
      ``logger.exception`` + 返回 False，让动作继续 —— 但日志里必须留下证据。
    """
    if plan is None:
        return False

    try:
        from bika.lims.api.snapshot import get_storage
        from bika.lims.api.snapshot import supports_snapshots
        from bika.lims.api.snapshot import take_snapshot
        from bika.lims.subscribers.auditlog import reindex_object
    except ImportError:
        logger.warning(
            "maitux.stability: snapshot API unavailable, skipping audit for %r",
            action)
        return False

    if not supports_snapshots(plan):
        # 对象不支持快照（声明了 IDoNotSupportSnapshots）。对 StabilityPlan 不该发生，
        # 但升级期间可能存在，记一条日志即可。
        logger.warning(
            "maitux.stability: %r does not support snapshots, "
            "skipping audit for %r", plan, action)
        return False

    # 坑 #2：metadata 的 modified 默认取对象修改时间；不推进它，
    # 审计条目会显示成"上一次编辑"的时间，而且 get_object_data 的 RAM 缓存
    # 键里也有它 —— 不推进就可能把改动前的数据写成快照。
    stamp = _now()
    try:
        plan.setModificationDate(stamp)
    except Exception:
        logger.exception(
            "maitux.stability: failed to stamp the modification date of %r",
            plan)

    snapshot_kwargs = {
        "action": as_text(action),
        "comments": as_text(comments),
    }
    if stamp is not None:
        try:
            snapshot_kwargs["modified"] = stamp.ISO()
        except Exception:
            pass
    # 坑 #3：take_snapshot 内部是 metadata.update(kw)，传 None 会把 actor 抹掉。
    if as_text(actor):
        snapshot_kwargs["actor"] = as_text(actor)

    try:
        # store=False：先构造、后补字段、最后自己存（见模块说明最后一个坑）。
        snapshot = take_snapshot(plan, store=False, **snapshot_kwargs)
    except Exception:
        logger.exception(
            "maitux.stability: failed to build an audit snapshot for %r (%s)",
            plan, action)
        return False

    if extra:
        try:
            # 先 dict() 再 update：extra 可能是 PersistentMapping / 其它 mapping，
            # 直接 update 在某些形态上会踩类型坑（与 stock 那份注释同一考虑）。
            snapshot.update(dict(extra))
        except Exception:
            logger.exception(
                "maitux.stability: failed to merge extra fields into the "
                "audit snapshot of %r", plan)

    try:
        get_storage(plan).append(json.dumps(snapshot))
    except Exception:
        logger.exception(
            "maitux.stability: failed to store the audit snapshot of %r (%s)",
            plan, action)
        return False

    try:
        # 本模块的方案显式实现 IMultiCatalogBehavior，审计目录通常已被
        # reindexObject 带上；这里再调一次是幂等兜底（见 stock 那份注释的坑 #2 变体）。
        reindex_object(plan)
    except Exception:
        logger.exception(
            "maitux.stability: failed to reindex the audit catalog for %r", plan)

    logger.info(
        "maitux.stability: audit '%s' recorded for %s (actor=%s, comments=%r)",
        action, _label(plan), as_text(actor) or u"(current user)",
        as_text(comments)[:120])
    return True


def _now():
    try:
        from DateTime import DateTime
        return DateTime()
    except Exception:
        return None


def record_write_back(plan, action, actor=u"", seqs=None, samples=None,
                      stock_batch=u"", reason=u""):
    """把一次"**写回方案明细行**"的动作记进审计快照（阶段 6b · A2）。

    为什么要有这一层（而不是各处直接调 :func:`record_plan_audit`）：
    登样 / 自动登样 / 零点关联 / 撤销登样 / 样品放置**五个**写点的审计
    形状完全一样（动作 + 操作人 + 涉及哪些时间点与样品），各写一遍必然漂移 ——
    迟早有一处忘了带 `extra`、或者把 actor 传成 None。

    :param action: 用本模块的 ``ACTION_*`` 常量（见 ACTIONS）
    :param actor: 操作人；自动/定时路径传 ``scheduler`` / ``lazy-trigger``
    :param seqs: 涉及的时间点序号（1 起），进快照的 ``timepoints``
    :param samples: 涉及的样品号（``H2O-0001`` 这种**人读的号**，不是 UID），
        进快照的 ``samples``
    :param stock_batch: 放置动作涉及的库存批次号
    :param reason: 原因（撤销登样有；其余为空）
    :returns: 同 :func:`record_plan_audit`（失败返回 False，**不抛异常**）
    """
    extra = {
        # 过滤掉 0/None/空串：空值进快照只会给审计页添噪音
        "timepoints": [int(s) for s in (seqs or []) if s],
        "samples": [as_text(s) for s in (samples or []) if as_text(s)],
    }
    if as_text(stock_batch):
        extra["stock_batch"] = as_text(stock_batch)
    return record_plan_audit(plan, action=action, comments=reason,
                             actor=actor, extra=extra)


def _label(obj):
    try:
        from bika.lims import api
        return api.get_path(obj)
    except Exception:
        return repr(obj)


# ── 状态流水 ───────────────────────────────────────────────────────────────


def _history_storage(plan, create=False):
    """取状态流水的存储（``PersistentList`` 挂在对象 annotation 上）。"""
    from zope.annotation.interfaces import IAnnotations
    annotation = IAnnotations(plan)
    storage = annotation.get(STATUS_HISTORY_KEY)
    if storage is None and create:
        from persistent.list import PersistentList
        storage = PersistentList()
        annotation[STATUS_HISTORY_KEY] = storage
    return storage


def get_status_history(plan):
    """读状态流水（**最新的在前**），认不出形态时返回空列表。

    读侧刻意做得非常宽容：annotation 里的内容可能来自更早的版本、
    也可能被手工改过 —— 页面不能因为一条脏记录就打不开。
    """
    if plan is None:
        return []
    try:
        storage = _history_storage(plan)
    except Exception:
        return []
    entries = []
    for raw in list(storage or []):
        if isinstance(raw, dict):
            entries.append(dict(raw))
        else:
            try:
                entries.append(json.loads(raw))
            except Exception:
                continue
    entries.reverse()
    return entries


def append_status_history(plan, state_before, state_after, transition,
                          reason=u"", actor=u""):
    """追加一条状态流水（最新的存在末尾，读的时候再反转）。

    :returns: True 表示已写入
    """
    if plan is None:
        return False
    try:
        storage = _history_storage(plan, create=True)
    except Exception:
        logger.exception(
            "maitux.stability: failed to open the status history of %r", plan)
        return False

    entry = {
        "time": format_timestamp(_now()),
        "actor": as_text(actor),
        "transition": as_text(transition),
        "state_before": as_text(state_before),
        "state_after": as_text(state_after),
        "reason": as_text(reason),
    }
    try:
        storage.append(entry)
        # 超限时从头截断（保留最近的）。
        overflow = len(storage) - HISTORY_LIMIT
        if overflow > 0:
            del storage[0:overflow]
    except Exception:
        logger.exception(
            "maitux.stability: failed to append the status history of %r", plan)
        return False
    return True


def clear_status_history(plan):
    """清空状态流水（复制方案时用：新方案不该继承源方案的状态痕迹）。"""
    if plan is None:
        return False
    try:
        from zope.annotation.interfaces import IAnnotations
        annotation = IAnnotations(plan)
        if STATUS_HISTORY_KEY in annotation:
            del annotation[STATUS_HISTORY_KEY]
        return True
    except Exception:
        logger.exception(
            "maitux.stability: failed to clear the status history of %r", plan)
        return False
