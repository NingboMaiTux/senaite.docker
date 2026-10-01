# -*- coding: utf-8 -*-
import threading
from contextlib import contextmanager
from datetime import timedelta

from bika.lims import api
from bika.lims.api.security import as_privileged_user
from plone import api as ploneapi
from senaite.core import logger
from senaite.core.upgrade.utils import temporary_allow_type
from zope.annotation.interfaces import IAnnotations

from maitux.stability import automation
from maitux.stability.i18n import translate_stability
from maitux.stability.indexing import ensure_indexed
from maitux.stability.sampleautomation import MESSAGE_CONTACT_CLEARED
from maitux.stability.sampleautomation import target_date as stability_target_date
from maitux.stability.sampleautomation import window_end as stability_window_end
from maitux.stability.timepoints import DETAIL_UID_FIELD
from maitux.stability.timepoints import build_task_title
from maitux.stability.timepoints import ensure_row_uids
from maitux.stability.timepoints import get_row_uid
from maitux.stability.timepoints import normalize_months as _normalize_months
from maitux.stability.timepoints import void_marker


# 正在同步的方案（线程内），见 sync_plan_timepoint_tasks 的重入说明。
_SYNC_STATE = threading.local()


def _task_uid(task):
    """取时间点任务上的行标识（历史任务没有，返回空串）。"""
    try:
        value = getattr(task, DETAIL_UID_FIELD, None)
    except Exception:
        return u""
    if not value:
        return u""
    try:
        return value.strip() if isinstance(value, str) else str(value).strip()
    except Exception:
        return u""


def _normalize_quantity(value):
    return value or 0


def _first(value):
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


# `_normalize_months` 的实现已收敛到 maitux.stability.timepoints.normalize_months
# （上面按别名导入）——月份归一化只保留一份实现，避免两处口径漂移。


def _plan_log_label(plan):
    """生成日志可读标签，便于定位是哪一个计划的哪一行数据。"""
    try:
        return api.get_path(plan)
    except Exception:
        return api.get_id(plan) or repr(plan)


def _plan_sync_key(plan):
    """同一方案在同一线程内的同步标识（路径 + id 双保险）。"""
    try:
        path = api.get_path(plan)
    except Exception:
        path = u""
    return "%s/%s" % (path, id(plan))


def _plan_sync_active(plan):
    """本线程此刻是否已经在处理这个方案。"""
    active = getattr(_SYNC_STATE, "active", None)
    if not active:
        return False
    return _plan_sync_key(plan) in active


@contextmanager
def _plan_sync_scope(plan, action):
    """「生成 / 对账时间点任务」的临界区，产出本次是否真的进入。

    ★ 必须防重入，而且**两条路径都要防**：

    给方案增删子对象时，Zope 的 `ObjectManager._setObject` / `manage_delObjects`
    会 `notifyContainerModified(plan)`，而 `ContainerModifiedEvent` 是
    `IObjectModifiedEvent` 的**子接口** —— 于是每建一个时间点任务，
    `stability_plan_modified` 都会立刻被回调一次，又回到
    `sync_plan_timepoint_tasks`。

    嵌套的那次对账看到的是一个**还没写上 `detail_uid` 的半成品任务**
    （身份是在 `create()` 返回之后才写的），按"明细里已经没有这一行"判成
    多余任务**当场删掉**；等 `plone.api.content.create` 走到
    `content = container[content_id]` 回查对象时，对象已经不在了，
    抛 `AttributeError: 'tp-001'`（真机实测：加方案即报错，方案建不出来）。

    临界区同时罩住「生成」（`_generate_plan_timepoint_tasks`）和「对账」
    （`sync_plan_timepoint_tasks`）：只要本线程已经在处理同一个方案，
    里层调用直接跳过 —— **绝不删除自己正在拼装的对象**。
    """
    if _plan_sync_active(plan):
        logger.info(
            "Skip re-entrant timepoint %s for plan '%s' "
            "(triggered by the operation itself, see _plan_sync_scope)",
            action, _plan_log_label(plan))
        yield False
        return

    active = getattr(_SYNC_STATE, "active", None)
    if active is None:
        active = set()
        _SYNC_STATE.active = active
    key = _plan_sync_key(plan)
    active.add(key)
    try:
        yield True
    finally:
        active.discard(key)
        if not active:
            _SYNC_STATE.active = None


def _resolve_uid_reference(value, allowed_type, field_name, plan=None, sequence=None):
    """解析并校验 UID 引用，非法值返回 None 并记录日志。

    这里不抛异常，避免单个无效引用阻断整条任务创建链路。
    """
    candidate = _first(value)
    if not candidate:
        return None

    obj = candidate if api.is_object(candidate) else None
    uid = api.get_uid(obj) if obj is not None else candidate

    if not api.is_uid(uid):
        logger.warning(
            "Skip invalid %s reference for plan '%s' seq %s: %r is not a UID",
            field_name, _plan_log_label(plan), sequence, candidate)
        return None

    if obj is None:
        try:
            obj = api.get_object_by_uid(uid)
        except Exception:
            obj = None

    if not api.is_object(obj):
        logger.warning(
            "Skip missing %s reference for plan '%s' seq %s: %r",
            field_name, _plan_log_label(plan), sequence, uid)
        return None

    if api.get_portal_type(obj) != allowed_type:
        logger.warning(
            "Skip invalid %s reference for plan '%s' seq %s: expected %s, got %s",
            field_name, _plan_log_label(plan), sequence,
            allowed_type, api.get_portal_type(obj))
        return None

    return api.get_uid(obj) or uid


def _sync_template_fields(obj):
    changed = False

    plan_id = api.get_id(obj)
    if plan_id and getattr(obj, "study_plan_id", None) != plan_id:
        obj.study_plan_id = plan_id
        changed = True

    total = (
        _normalize_quantity(getattr(obj, "sample_quantity", None)) +
        _normalize_quantity(getattr(obj, "reserve_quantity", None))
    )
    if getattr(obj, "total_quantity", None) != total:
        obj.total_quantity = total
        changed = True

    if changed:
        obj.reindexObject()


def ensure_plan_detail_uids(plan):
    """给方案明细里缺 ``detail_uid`` 的行补上稳定标识（幂等）。

    历史方案（本功能上线前创建的）没有这一列，第一次被打开或保存时在这里补齐。
    返回本次补上的行数。

    写回前会核对行数：``ensure_row_uids`` 只认识 dict 行，
    万一库里存在非 dict 的脏行，宁可**不写**（记日志）也不能把它丢掉。
    """
    if api.get_portal_type(plan) != "StabilityPlan":
        return 0

    rows = list(getattr(plan, "plan_details", None) or [])
    if not rows:
        return 0

    new_rows, assigned = ensure_row_uids(rows)
    if not assigned:
        return 0

    if len(new_rows) != len(rows):
        logger.warning(
            "Skip assigning timepoint row ids for plan '%s': "
            "row count would change (%s -> %s)",
            _plan_log_label(plan), len(rows), len(new_rows))
        return 0

    try:
        plan.plan_details = new_rows
        plan.reindexObject()
    except Exception:
        logger.exception(
            "Failed to assign timepoint row ids for plan '%s'",
            _plan_log_label(plan))
        return 0
    return assigned


def _sync_plan_fields(obj):
    if api.get_portal_type(obj) != "StabilityPlan":
        return False

    changed = False

    plan_id = api.get_id(obj)
    if plan_id and getattr(obj, "plan_id", None) != plan_id:
        obj.plan_id = plan_id
        changed = True

    total = (
        _normalize_quantity(getattr(obj, "sample_quantity", None)) +
        _normalize_quantity(getattr(obj, "reserve_quantity", None))
    )
    if getattr(obj, "total_quantity", None) != total:
        obj.total_quantity = total
        changed = True

    if changed:
        obj.reindexObject()

    return changed


def _generate_plan_timepoint_tasks(plan):
    """新建方案时按明细行生成时间点任务。

    建任务会触发方案自己的 `IObjectModifiedEvent`（见 `_plan_sync_scope`），
    所以这里必须走同一个临界区 —— 否则嵌套的那次对账会把
    "还没写上 `detail_uid` 的半成品任务"删掉，`plone.api` 回查 id 时崩溃。
    """
    if api.get_portal_type(plan) != "StabilityPlan":
        return False

    with _plan_sync_scope(plan, u"generation") as entered:
        if not entered:
            return False
        return _create_plan_timepoint_tasks(plan)


def _create_plan_timepoint_tasks(plan):
    """``_generate_plan_timepoint_tasks`` 的实现体（不含重入判定）。"""
    if api.get_portal_type(plan) != "StabilityPlan":
        return False

    key = "maitux.stability.tasks_generated"
    try:
        annotations = IAnnotations(plan)
    except Exception:
        annotations = None

    existing = []
    try:
        for child in plan.objectValues():
            if api.get_portal_type(child) == "StabilityTimepointTask":
                existing.append(child)
    except Exception:
        existing = []

    if existing:
        if annotations is not None:
            annotations[key] = True
        return False

    if annotations is not None and annotations.get(key):
        return False

    plan_details = getattr(plan, "plan_details", None) or []
    detail_rows = []
    for idx, row in enumerate(plan_details, start=1):
        if not isinstance(row, dict):
            continue
        detail_rows.append((idx, row))

    if not detail_rows:
        return False

    start_time = getattr(plan, "start_time", None)

    created = False
    for idx, tp in enumerate(detail_rows, start=1):
        row = tp[1]
        seq = idx
        months = _normalize_months(row.get("timepoint_days"))

        window_months = row.get("window_days")
        if not isinstance(window_months, int) or window_months < 0:
            window_months = 0

        base_id = "tp-{0:03d}".format(seq)
        obj_id = base_id
        suffix = 1
        while getattr(plan, "get", lambda _id: None)(obj_id) is not None:
            obj_id = "{0}-{1}".format(base_id, suffix)
            suffix += 1

        # 时间点单位为 Months，窗口期单位为 Days。
        # 标题形态由 timepoints.build_task_title 统一给出（零点 -> `TP 1 (Initial)`），
        # 落库一律英文，渲染时按语言翻译（title.localized_task_title）。
        title = build_task_title(seq, months)

        # 建任务这一步整段包住：`plone.api.content.create` 自己会用请求的 id
        # 回查新对象，只要对象在创建过程中被谁删掉/改名，它就抛
        # `AttributeError: '<id>'`。加到方案上的订阅者链路（含本模块的对账）
        # 已经在 `_plan_sync_scope` 里被挡住，这里再兜一层 ——
        # 单个时间点建不出来时**不要**把新建方案这件事一起弄崩，
        # 剩下的行留给下一次保存时的对账去补。
        try:
            with temporary_allow_type(plan, "StabilityTimepointTask"):
                task = ploneapi.content.create(
                    container=plan,
                    type="StabilityTimepointTask",
                    id=obj_id,
                    title=title,
                )
            new_id = None if task is None else api.get_id(task)
            if not new_id or plan.get(new_id, None) is None:
                logger.error(
                    "Timepoint task '%s' vanished right after creation for "
                    "plan '%s' seq %s; stop generating and let the next "
                    "sync create the remaining rows", obj_id,
                    _plan_log_label(plan), seq)
                break

            task.sequence = seq
            # 与明细行同一个稳定标识：任务与明细的配对只能靠它
            # （序号会随删行/排序平移，见 maitux.stability.timepoints）。
            task.detail_uid = get_row_uid(row)
            task.timepoint_days = months
            task.window_days = window_months

            task.packaging_specification = _first(row.get("packaging_specification"))
            task.storage_condition = _first(row.get("storage_condition"))
            task.orientation = row.get("orientation")
            # 样品模板逐个时间点维护（行上的"检验标准/分析套餐"已删除）
            task.sample_template = _first(row.get("sample_template"))
            task.batch = _first(row.get("batch"))
            # StockBatch 引用可能已经失效，这里降级为 None 并记录日志，
            # 避免单个无效引用导致整个时间点任务生成中断。
            task.stock_batch = _resolve_uid_reference(
                row.get("stock_batch"), "StockBatch", "stock_batch", plan, seq)
            task.inspection_quantity = _normalize_quantity(row.get("inspection_quantity"))
            task.detail_status = row.get("detail_status") or "pending_placement"
            task.notes = row.get("notes")
            # 阶段 6c：作废三件套（行是唯一真相；建任务时原样镜像）
            _marker = void_marker(row)
            task.voided_at = _marker.get("voided_at") or ""
            task.voided_by = _marker.get("voided_by") or ""
            task.void_reason = _marker.get("void_reason") or ""

            if start_time:
                # 时间点按月计算，约定 1 月 = 30 天（折算口径的唯一实现在
                # sampleautomation.target_date / window_end，看板/同步/登样
                # 共用一份 —— 阶段 6b 起窗口结束日也走唯一实现，
                # 否则任务上的结束日与看板的过期判据会各算各的）。
                target = stability_target_date(start_time, months)
                if window_months:
                    # 窗口期直接使用天数。
                    w_start = target - timedelta(days=window_months)
                else:
                    w_start = target
                w_end = stability_window_end(start_time, months, window_months)
                task.target_date = target
                task.window_start = w_start
                task.window_end = w_end

            task.reindexObject()
            # ★ reindexObject() 在本包里可能是**静默空操作**（见 indexing 模块）：
            #   不显式编目的话，任务在 uid_catalog 里有、在 senaite_catalog_setup
            #   里没有 —— 看板/列表就看不到它。
            ensure_indexed(task)
        except Exception:
            logger.exception(
                "Failed to create timepoint task '%s' for plan '%s' seq %s; "
                "stop generating and let the next sync create the remaining rows",
                obj_id, _plan_log_label(plan), seq)
            break

        created = True

    if created and annotations is not None:
        annotations[key] = True

    return created


def sync_plan_timepoint_tasks(plan, delete_excess=True):
    """把 StabilityPlan.plan_details 同步到已生成的 StabilityTimepointTask。

    ★ 本函数**必须防重入**（临界区见 `_plan_sync_scope`）：
    实测「删/加方案里的子对象」都会触发方案的 `IObjectModifiedEvent`，
    也就是会再次回到这里。不设防的话：

    - 删除方向：变成「同步 → 删掉多余任务 → 再次同步 → 给这一行重新建任务
      → 再删 → …」，任务对象成倍增长（实测一次删行能造出几十个 `tp-00N-xx`）；
    - **新增方向（真机事故）**：新建方案时生成任务 → 每个任务入容器都回调一次
      本函数 → 嵌套的这次对账把"还没写上 `detail_uid` 的半成品任务"当多余任务
      删掉 → `plone.api.content.create` 用 id 回查对象时抛
      `AttributeError: 'tp-001'`，方案直接建不出来。

    其它调用方（脚本 / 升级）可以放心调用，重入判定只拦"同一次操作里
    由自身触发的嵌套调用"。
    """
    with _plan_sync_scope(plan, u"sync") as entered:
        if not entered:
            return (0, 0, 0)
        return _sync_plan_timepoint_tasks(plan, delete_excess=delete_excess)


def _comparable(value):
    """把字段值归一成可直接比较的形态（用于"值没变就不写库"）。

    * 单值列表取第一个（DataGrid 里的引用常是列表）；
    * ``DateTime`` / ``datetime`` 的 ``str()`` 格式不同（``2026/08/23 15:42:00 GMT+0``
      vs ``2026-08-23 15:42:00+00:00``），所以统一走 ISO 形式，
      否则日期字段会被判成"每次都变了"。
    """
    value = _first(value)
    if value is None:
        return u""
    if isinstance(value, (list, tuple, dict)):
        return u""
    for attr in ("ISO8601", "isoformat"):
        method = getattr(value, attr, None)
        if callable(method):
            try:
                return method()
            except Exception:
                pass
    try:
        return value
    except Exception:
        return u""


def _values_equal(current, desired):
    try:
        return _comparable(current) == _comparable(desired)
    except Exception:
        return False


def _sync_plan_timepoint_tasks(plan, delete_excess=True):
    """``sync_plan_timepoint_tasks`` 的实现体（不含重入判定）。

    同步策略尽量保守：

    - **配对**：优先用 ``detail_uid``（明细行与任务同值）；
      只有"任务自身没有 id"（本功能上线前建的历史任务）才按 ``sequence`` 兜底。
      绝不能一律按序号配对 —— 明细删掉中间一行后行号会平移，
      按序号配会**删错对象**。
    - **创建**：明细里新增的行，创建对应的任务。
    - **更新**：只更新 ``detail_status=pending_placement`` 的任务；
      已经开始的（进行中/已完成）不动，避免覆盖实际执行结果。
    - **删除**：只删除"明细里已经没有、且自身还是待放置"的任务；
      已经开始的**永不删除**。删除走 ``as_privileged_user()``（见下）。
    """
    if api.get_portal_type(plan) != "StabilityPlan":
        return (0, 0, 0)

    plan_details = getattr(plan, "plan_details", None) or []
    desired = []
    for idx, row in enumerate(plan_details, start=1):
        if not isinstance(row, dict):
            continue
        desired.append((idx, row))

    desired_seqs = set([seq for seq, _row in desired])
    desired_uids = set([get_row_uid(row) for _seq, row in desired])
    desired_uids.discard(u"")

    existing = []
    try:
        for child in plan.objectValues():
            if api.get_portal_type(child) == "StabilityTimepointTask":
                existing.append(child)
    except Exception:
        existing = []

    by_uid = {}
    by_seq = {}
    for task in existing:
        uid = _task_uid(task)
        if uid:
            if uid not in by_uid:
                by_uid[uid] = task
            continue
        seq = getattr(task, "sequence", None)
        if isinstance(seq, int) and seq > 0 and seq not in by_seq:
            by_seq[seq] = task

    # 已经被认领的任务，删除阶段不再考虑它。
    claimed = set()

    def claim_task(row_uid, seq):
        """找这一行对应的任务。

        1. 行有 id -> 按 id 精确配；
        2. 配不上、且该序号上是一条**没有 id 的历史任务** -> 认领它（升级路径）；
        3. 其余一律不配（宁可新建，也不把新行塞进别的任务里）。
        """
        task = by_uid.get(row_uid) if row_uid else None
        if task is not None and task not in claimed:
            return task

        legacy = by_seq.get(seq)
        if legacy is None or legacy in claimed:
            return None
        if row_uid and _task_uid(legacy):
            return None
        return legacy

    start_time = getattr(plan, "start_time", None)

    created = 0
    updated = 0
    deleted = 0

    def apply_row_to_task(task, seq, row):
        """把行数据写入任务对象（只用于 pending_placement），返回"是否真的有字段变了"。

        只写**确实变了**的字段：同步是在方案每次保存时都会跑的，
        无条件重写会让 ZODB 每次保存都白写一遍，
        也让"同步是否幂等"无法验证（updated 永远等于行数）。
        """
        months = _normalize_months(row.get("timepoint_days", 0))
        window_days = row.get("window_days", 0)
        if not isinstance(window_days, int) or window_days < 0:
            window_days = 0

        desired = {}
        desired["sequence"] = seq
        desired[DETAIL_UID_FIELD] = get_row_uid(row)
        desired["timepoint_days"] = months
        desired["window_days"] = window_days
        desired["packaging_specification"] = _first(row.get("packaging_specification"))
        desired["storage_condition"] = _first(row.get("storage_condition"))
        desired["orientation"] = row.get("orientation") or getattr(task, "orientation", None)
        desired["sample_template"] = _first(row.get("sample_template"))
        desired["batch"] = _first(row.get("batch"))
        # 同步时同样要容忍已失效的 StockBatch 引用，避免整个任务同步失败。
        desired["stock_batch"] = _resolve_uid_reference(
            row.get("stock_batch"), "StockBatch", "stock_batch", plan, seq)
        desired["inspection_quantity"] = _normalize_quantity(row.get("inspection_quantity"))
        desired["notes"] = row.get("notes") or ""

        # 阶段 6c：**作废三件套也要镜像到任务上**（确认稿 0.2 ③：
        # "作废行的任务保留并同步标记为已作废"）。
        # ★ 值从**明细行**取（行才是唯一真相），任务只是展示层；
        #   行上没作废 -> 任务上也要清空（万一历史数据里任务带着旧标记）。
        marker = void_marker(row)
        desired["voided_at"] = marker.get("voided_at") or ""
        desired["voided_by"] = marker.get("voided_by") or ""
        desired["void_reason"] = marker.get("void_reason") or ""

        # 时间点单位为月：目标日期 = T0 + (Months * 30 天)。
        # 折算口径统一走 sampleautomation.target_date / window_end
        # （见模块顶部导入）—— 窗口结束日不再自己加 timedelta。
        if start_time:
            target = stability_target_date(start_time, months)
            w_start = target - timedelta(days=window_days) if window_days else target
            w_end = stability_window_end(start_time, months, window_days)
            desired["target_date"] = target
            desired["window_start"] = w_start
            desired["window_end"] = w_end

        # 标题统一使用 Months；零点用 `TP n (Initial)`（见 timepoints.build_task_title）。
        desired["title"] = build_task_title(seq, months)

        changed = False
        for name in sorted(desired.keys()):
            value = desired[name]
            try:
                current = getattr(task, name, None)
            except Exception:
                current = None
            if _values_equal(current, value):
                continue
            try:
                setattr(task, name, value)
                changed = True
            except Exception:
                logger.exception(
                    "Failed to set %s on timepoint task for plan '%s' seq %s",
                    name, _plan_log_label(plan), seq)
        return changed

    # 先完成全部创建/更新，再删除多余任务，避免中途失败导致 pending 任务丢失。
    sync_ok = True

    # 更新或创建任务。
    for seq, row in desired:
        created_now = False
        task = None
        row_uid = get_row_uid(row)
        task = claim_task(row_uid, seq)
        try:
            if task is None:
                base_id = "tp-{0:03d}".format(seq)
                obj_id = base_id
                suffix = 1
                while getattr(plan, "get", lambda _id: None)(obj_id) is not None:
                    obj_id = "{0}-{1}".format(base_id, suffix)
                    suffix += 1

                months = _normalize_months(row.get("timepoint_days", 0))
                title = build_task_title(seq, months)

                with temporary_allow_type(plan, "StabilityTimepointTask"):
                    task = ploneapi.content.create(
                        container=plan,
                        type="StabilityTimepointTask",
                        id=obj_id,
                        title=title,
                    )
                task.detail_uid = row_uid
                created += 1
                created_now = True
            else:
                claimed.add(task)
                # 认领到历史任务（引入 detail_uid 之前建的）时，把行标识补上。
                # 这里只写"身份"，不碰任何业务字段 ——
                # 补上之后，后续同步/排样都能按 id 精确配对，不再依赖会平移的序号。
                try:
                    if row_uid and _task_uid(task) != row_uid:
                        task.detail_uid = row_uid
                except Exception:
                    logger.exception(
                        "Failed to assign timepoint row id to task for plan '%s' seq %s",
                        _plan_log_label(plan), seq)

            status = getattr(task, "detail_status", None) or "pending_placement"
            if status != "pending_placement":
                # 已经开始的时间点不动：它的目标日期与排样是实际执行结果，
                # 不能被后续的明细编辑覆盖。
                continue

            if apply_row_to_task(task, seq, row):
                task.reindexObject()
                updated += 1
            # 刚建出来的任务也要显式编目（reindexObject 可能是空操作）。
            if created_now:
                ensure_indexed(task)
        except Exception:
            sync_ok = False
            logger.exception(
                "Failed to sync pending timepoint task for plan '%s' seq %s",
                _plan_log_label(plan), seq)
            # 新建任务失败时尽量回滚本次新增对象，避免留下半成品任务。
            if created_now and api.is_object(task):
                try:
                    ploneapi.content.delete(obj=task)
                    created -= 1
                except Exception:
                    logger.exception(
                        "Failed to rollback newly created task for plan '%s' seq %s",
                        _plan_log_label(plan), seq)
            continue

    # 删除多余的任务：明细里已经没有、且自身还是"待放置"的。
    # 已经开始的（进行中/已完成）**永不删除**，即使明细里已经找不到对应行
    # （正常流程删不掉它们，走到这里说明有脏数据，留着比删掉安全）。
    if delete_excess and sync_ok:
        for task in list(existing):
            if task in claimed:
                continue
            status = getattr(task, "detail_status", None) or "pending_placement"
            if status != "pending_placement":
                continue

            uid = _task_uid(task)
            if uid:
                if uid in desired_uids:
                    continue
                label = "uid %s" % uid
            else:
                seq = getattr(task, "sequence", None)
                if isinstance(seq, int) and seq > 0 and seq in desired_seqs:
                    continue
                if not (isinstance(seq, int) and seq > 0):
                    # ★ 认不出"这条任务是哪一行的"就**不删**。
                    #
                    #   删除阶段的本意是「明细里删掉了某一行 → 把它的任务一起删掉」，
                    #   而那些任务一律带着身份（新的是 detail_uid，历史的是 sequence）。
                    #   两者都没有的任务只可能是**别人正在创建、字段还没写完的半成品**
                    #   （建任务本身会回调本函数，见 _plan_sync_scope），
                    #   或者是外来的手工对象 —— 两种都不该由"对账"来判死刑：
                    #   删掉半成品正是 AttributeError: 'tp-001' 的成因。
                    logger.warning(
                        "Keep unidentifiable pending timepoint task '%s' of plan "
                        "'%s' (no detail_uid, sequence=%r): it is either being "
                        "created right now or belongs to somebody else",
                        api.get_id(task), _plan_log_label(plan), seq)
                    continue
                label = "seq %s" % seq

            try:
                # ★ 必须提权删除：`plone.dexterity` 的容器在删子对象时会做
                #   `getSecurityManager().checkPermission(DeleteObjects, item)`，
                #   而本栈里 AccessControl 4.4 对**字符串**权限名先去
                #   `queryUtility(IPermission, name)` 查，查不到就直接判 False ——
                #   `"Delete objects"` 注册的是权限标题，工具名是 `cmf.DeleteObjects`，
                #   于是**只要装了真实 SecurityManager（真请求），
                #   连 Manager 删自己的子对象都会 Unauthorized**（已实测）。
                #   平台为此提供了 `as_privileged_user()`（其 docstring 举的例子
                #   正是"删除对象"），这里按官方姿势调用；会话身份在退出时自动恢复。
                #
                #   注意：能走到这里的任务已经过两道业务判定 ——
                #   明细里已经没有这一行、且它自己还是"待放置"。
                with as_privileged_user():
                    ploneapi.content.delete(obj=task)
                deleted += 1
            except Exception:
                logger.exception(
                    "Failed to delete excess pending task for plan '%s' %s",
                    _plan_log_label(plan), label)
    elif delete_excess and not sync_ok:
        logger.warning(
            "Skip deletion phase for plan '%s' because create/update phase was not fully successful",
            _plan_log_label(plan))

    return (created, updated, deleted)


def _drop_mismatched_contact(obj):
    """保存时清掉"客户与联系人不是同一家"的错配值，并给出提示。

    为什么在**保存时**做，而不是等登样报错：`Contact` 的下拉是全站联系人，
    客户是同表单里另选的，很容易出现"A 客户 + B 家联系人"的组合；
    登样时的拦截属于事后发现，用户已经填错一次了。
    这里把错配值清掉 + 明确提示，错误配置就不会留在库里
    （登样那边的 ``PROBLEM_CONTACT_OTHER_CLIENT`` 仍然保留，做最后一道闸）。
    """
    try:
        removed = automation.drop_mismatched_contact(obj)
    except Exception:
        logger.exception(
            "Failed to check contact/client match for %s", _plan_log_label(obj))
        return
    if not removed:
        # 自身没写联系人、但"生效联系人"（可能来自方案模板）错配时也要留痕，
        # 否则用户只会在登样页看到报错，不知道根在模板上。
        try:
            effective = automation.get_contact(obj)
            client = automation.get_client(obj)
            if automation.contact_belongs_to_other_client(effective, client):
                logger.warning(
                    "Contact '%s' (belongs to '%s') of %s does not match client "
                    "'%s': it comes from the plan template and must be fixed there",
                    api.get_title(effective) or api.get_id(effective),
                    automation.contact_client_title(effective),
                    _plan_log_label(obj),
                    api.get_title(client) or api.get_id(client))
        except Exception:
            logger.exception(
                "Failed to log the contact/client mismatch of %s",
                _plan_log_label(obj))
        return

    contact_title, contact_client_title, client_title = removed
    logger.warning(
        "Cleared mismatching contact '%s' (belongs to '%s') of %s: the samples "
        "are created for client '%s'",
        contact_title, contact_client_title, _plan_log_label(obj), client_title)

    message = translate_stability(MESSAGE_CONTACT_CLEARED).format(
        contact=contact_title, contact_client=contact_client_title,
        client=client_title)
    try:
        request = api.get_request()
    except Exception:
        request = None
    if request is not None:
        try:
            ploneapi.portal.show_message(
                message=message, request=request, type="warning")
        except Exception:
            logger.exception("Failed to show the contact-cleared message")

    try:
        obj.reindexObject()
        ensure_indexed(obj)
    except Exception:
        logger.exception(
            "Failed to reindex %s after clearing the mismatching contact",
            _plan_log_label(obj))


def stability_study_template_added(obj, event):
    _sync_template_fields(obj)
    _drop_mismatched_contact(obj)


def stability_study_template_modified(obj, event):
    _sync_template_fields(obj)
    _drop_mismatched_contact(obj)


stability_plan_template_added = stability_study_template_added
stability_plan_template_modified = stability_study_template_modified


def stability_plan_added(obj, event):
    # 阶段 6a：新方案一律从「进行中」开始。
    #
    # ★ 为什么不能只靠工作流的 initial_state：本模块的 setuphandlers 里
    #   `update_security()` 也是**显式**给对象补 review_state 的
    #   （注释写着 "Ensure object is in 'active' state if it has no state"）——
    #   说明这条自动初始化的路径在本部署里并不总是生效（顺序/事件依赖）。
    #   新方案没有状态的话，列表状态列是空的、状态筛选也筛不到它。
    #   only_if_missing=True：已经由工作流设过就不动。
    _ensure_plan_status_state(obj)
    # 状态流水是 annotation 上的数据，**复制对象时会被一起带过来**
    # （ZMI 复制粘贴、manage_clone 都会复制 annotation）。
    # 新方案不该继承别人的状态痕迹 —— 清掉，代价一次属性访问。
    _clear_plan_status_history(obj)
    _sync_plan_fields(obj)
    # 先给明细行发身份，再按明细生成任务 —— 顺序不能反：
    # 任务的 detail_uid 取自明细行，晚补就等于任务全部没有身份。
    ensure_plan_detail_uids(obj)
    _generate_plan_timepoint_tasks(obj)
    # 客户/联系人错配（客户是 A、联系人是 B 家的人）在保存时就清掉并提示，
    # 不要留到登样时才报错（见 _drop_mismatched_contact）。
    _drop_mismatched_contact(obj)
    # ★ 方案本体也要显式编目：`reindexObject()` 在本包里可能是静默空操作，
    #   结果就是"方案确实建出来了，但列表 / API 里看不到"（见 indexing 模块）。
    ensure_indexed(obj)


def _ensure_plan_status_state(obj):
    """给方案补初始状态（幂等，失败不影响建方案）。"""
    try:
        from maitux.stability import plan_status
        plan_status.ensure_plan_state(obj, actor=u"system",
                                      only_if_missing=True)
    except Exception:
        logger.exception(
            "Failed to initialize the workflow state of %s",
            _plan_log_label(obj))


def _clear_plan_status_history(obj):
    """清掉状态流水（新建方案不该继承任何痕迹）。"""
    try:
        from maitux.stability import audit
        audit.clear_status_history(obj)
    except Exception:
        logger.exception(
            "Failed to clear the status history of %s", _plan_log_label(obj))


def stability_plan_modified(obj, event):
    _sync_plan_fields(obj)
    # 1) 历史方案补齐行标识；
    # 2) 明细与任务对账（新增行建任务、删掉的行删任务；进行中/已完成的行不动）。
    #
    # 为什么放在这里：方案明细既可能被编辑表单改（那条路径在
    # browser/edit.py 里已经校验过"只删待放置的行"），
    # 也可能被脚本 / ZMI / 其它流程直接改。这里做的是**兜底对账**：
    # 不做删除守卫（守卫在表单里），但保证任务对象不会与明细分家。
    ensure_plan_detail_uids(obj)
    sync_plan_timepoint_tasks(obj, delete_excess=True)
    _drop_mismatched_contact(obj)
    ensure_indexed(obj)
