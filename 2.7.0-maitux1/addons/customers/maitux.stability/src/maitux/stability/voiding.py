# -*- coding: utf-8 -*-
"""阶段 6c/6d：时间点行「删除 = 状态删除（废弃）」的**对象级写入口**。

需求（《方案状态与过期规则-需求确认稿》0.1/0.2、2.5、D6/D7、Q1–Q5）：

* 方案明细**只增不减** —— 用户"删行"不再真删，改成在行上写
  ``voided_at`` / ``voided_by`` / ``void_reason`` 三个标记键；
* 三个键**不进 schema**、也**不新增 ``detail_status`` 取值**
  （状态词表不动，8 处状态映射都不用改；与 ``revoked_*`` 三件套同类）；
* **唯一入口（阶段 6d 起）**：编辑页 DataGrid 删行 —— 走
  ``timepoints.sanitize_submitted_rows``，它内部调用本模块的
  :func:`void_plan_rows`。6c 曾有过的「作废时间点」动作页已按用户要求撤掉；
* **C1 前置条件**：行上关联了样品时，样品必须**已达终态**，否则拦下并提示；
* 作废后：关联样品**保留**、样品对象本身**不动**、对应的时间点任务**保留并标记**；
* 写审计快照（``audit.ACTION_VOID_TIMEPOINT``）。

分层（与 ``plan_status`` / ``samplegeneration`` 同一条纪律 —— 判据唯一）：

    timepoints.py      行的事实：标记键、is_voided / is_voidable / void_row
    plan_status.py     纯判据：void_precondition(row, sample_state, sample_id)
          ↑
    voiding.py         本模块：**把样品状态读出来**喂给纯判据 + 一次性写库 + 镜像任务 + 审计
          ↑
    browser/*.py       页面层：只做提示与跳转，判据一律从上面两层取

★★ 为什么作废标记必须在 ``sanitize_submitted_rows`` 里**最后**落：
   "作废一个过期行"是需求明确允许的动作（过期行只允许作废或新增），
   而过期行同时是编辑页的**锁定行**（``restore_locked_rows`` 会用原行覆盖它）——
   顺序错了，刚写上的作废标记会被原行盖掉，用户看到的是
   "点了删除、行回来了、也没作废"（见 ``timepoints.sanitize_submitted_rows``
   的第 5b 步）。
"""

from datetime import datetime

from bika.lims import api
from senaite.core import logger

from maitux.stability import audit
from maitux.stability import plan_status
from maitux.stability import timepoints as tp
from maitux.stability.indexing import ensure_indexed
from maitux.stability.timepoints import void_marker


#: 结果码与判定都在 ``plan_status``（纯逻辑，唯一实现）—— 这里只做转出，
#: 让浏览器层不必同时 import 两个模块（与 ``automation`` 的做法一致）。
VOID_OK = plan_status.VOID_OK
VOID_UNKNOWN_ROW = plan_status.VOID_UNKNOWN_ROW
VOID_ALREADY_VOIDED = plan_status.VOID_ALREADY_VOIDED
VOID_ROW_PROTECTED = plan_status.VOID_ROW_PROTECTED
VOID_SAMPLE_UNFINISHED = plan_status.VOID_SAMPLE_UNFINISHED

#: 行上的原因键（编辑页/动作页都往这里写）
VOID_REASON_FIELD = tp.VOID_REASON_FIELD

#: 结果码 -> 日志/审计用的一句话（页面文案在浏览器层的 VOID_MESSAGES）
void_reason_text = plan_status.void_reason_text


def current_void_actor():
    """当前用户 id（写进 ``voided_by`` 与审计快照）。取不到时返回空串。"""
    try:
        from maitux.stability.samplegeneration import current_user_id
        return current_user_id()
    except Exception:
        return u""


def resolve_sample_state(plan, row):
    """这一行关联样品的工作流状态：``(state, sample_id)``。

    ★ 只**读**样品对象的状态，对样品不做任何写操作 ——
      需求原文（确认稿 2.5）："样品对象本身不做任何动作"。
    """
    uid = plan_status.first_uid((row or {}).get("analysis_request"))
    if not uid or not api.is_uid(uid):
        return None, u""
    sample = api.get_object_by_uid(uid, None)
    if sample is None:
        return None, uid
    try:
        state = api.get_workflow_status_of(sample)
    except Exception:
        state = None
    return state, api.get_id(sample) or uid


def can_void_row(plan, row):
    """对象级作废判据：``(ok, reason_code, detail)``（页面与写库都走它）。

    两道，缺一不可：

    1. **方案状态**：被暂停 / 终止的方案一律不许作废（与登样 / 关联 / 撤销 /
       放置同一道门，见 ``plan_status.can_modify_plan``）。
       ★ 2026-09-30 真机抓到：这一道**第一版漏了** —— 当时的 ``@@void_point``
         页面只看行本身（行没样品、状态也允许），于是**已终止方案的作废按钮是亮的**，
         点下去才被服务端拒（"方案已终止"）。这正是 6b 用户报过的同一类
         "页面上摆得出来、提交才被拒"，所以判据必须包含方案状态。
         （6d 起那个页面没了，但这条判据照样必须留着：编辑页删行也要过它。）
    2. **行 + 样品**：``plan_status.void_precondition``（C1：有关联样品时
       样品必须已达终态；已作废的不再作废；已登样/已完成的不许删）。
    """
    state = plan_status.get_plan_state(plan)
    ok, blocked_code = plan_status.can_modify_plan(state)
    if not ok:
        return (False, blocked_code, u"")
    sample_state, sample_id = resolve_sample_state(plan, row)
    return plan_status.void_precondition(row, sample_state=sample_state,
                                         sample_id=sample_id)


def void_plan_rows(plan, seqs, reason=u"", actor=u"", now=None,
                   expected_uids=None):
    """把方案里的若干行**一次性**作废（唯一写库实现）。

    :param plan: ``StabilityPlan``
    :param seqs: 要作废的行号（1 起；与看板 ``plan_uid::seq`` 同一口径）
    :param reason: 作废原因（**选填**，Q3；快速作废留空）
    :param actor: 操作人（写 ``voided_by``，进审计快照）
    :param now: 注入时间（自检用）
    :param expected_uids: ``{seq: detail_uid}`` 行身份校验（页面渲染 → 提交
        之间别人改了方案时，行号可能已经指向另一行 —— 那种情况下宁可不作废）

    :returns: ``{"ok", "voided": [seq...], "blocked": [(seq, code, detail)...],
                "tasks_marked", "snapshots", "plan_state"}``

    ★ 只写一次 ``plan_details``：一次作废 5 行也只落库一次
      （全量快照的代价在那儿，见确认稿 §11 第 4 条）。
    ★ 方案被暂停 / 终止时整批拒绝（与登样 / 关联 / 撤销 / 放置同一道门）。
    """
    result = {"ok": False, "voided": [], "blocked": [], "snapshots": 0,
              "tasks_marked": 0, "plan_state": None}
    if plan is None or api.get_portal_type(plan) != "StabilityPlan":
        result["blocked"].append((None, VOID_UNKNOWN_ROW, u""))
        return result

    # 方案级冻结：判据唯一实现在 plan_status.can_modify_plan
    state = plan_status.get_plan_state(plan)
    result["plan_state"] = state
    ok, blocked_code = plan_status.can_modify_plan(state)
    if not ok:
        for seq in (seqs or []):
            result["blocked"].append((seq, blocked_code, u""))
        return result

    if actor is None:
        actor = current_void_actor()
    if now is None:
        now = datetime.now()

    rows = list(getattr(plan, "plan_details", None) or [])
    expected_uids = expected_uids or {}

    changes = {}                      # index -> 作废后的新行
    for seq in (seqs or []):
        try:
            index = int(seq) - 1
        except Exception:
            result["blocked"].append((seq, VOID_UNKNOWN_ROW, u""))
            continue
        if index < 0 or index >= len(rows) or not isinstance(rows[index], dict):
            result["blocked"].append((seq, VOID_UNKNOWN_ROW, u""))
            continue

        row = rows[index]
        expected = expected_uids.get(seq)
        if expected is not None:
            stored_uid = tp.get_row_uid(row)
            if stored_uid and stored_uid != api.safe_unicode(expected).strip():
                result["blocked"].append((seq, VOID_UNKNOWN_ROW, u"row_changed"))
                continue

        ok, code, detail = can_void_row(plan, row)
        if not ok:
            result["blocked"].append((seq, code, detail))
            continue

        changes[index] = tp.void_row(row, actor=actor, reason=reason, now=now)
        result["voided"].append(seq)

    if not changes:
        return result

    for index, new_row in changes.items():
        rows[index] = new_row

    try:
        plan.plan_details = rows
        plan.reindexObject()
        ensure_indexed(plan)
    except Exception:
        logger.exception(
            "Failed to write the voided rows back to plan '%s'",
            api.get_path(plan))
        result["voided"] = []
        result["blocked"].append((None, VOID_UNKNOWN_ROW, u"write failed"))
        return result

    # 任务：**保留**并同步标记（0.2 ③：作废行的任务不删、标成已作废）
    for index in sorted(changes.keys()):
        try:
            result["tasks_marked"] += mirror_task_void(
                plan, index + 1, tp.get_row_uid(changes[index])) or 0
        except Exception:
            logger.exception(
                "Failed to mirror the void marker to the timepoint task of "
                "plan '%s' seq %s", api.get_path(plan), index + 1)

    # 审计快照（唯一写入口 audit.py）：原因进 comments，行号进 timepoints
    before = audit.snapshot_count(plan)
    audit.record_write_back(
        plan, audit.ACTION_VOID_TIMEPOINT, actor=actor,
        seqs=sorted(result["voided"]), reason=api.safe_unicode(reason or u""))
    result["snapshots"] = audit.snapshot_count(plan) - before
    result["ok"] = True
    logger.info(
        "maitux.stability: voided %d timepoint row(s) of plan '%s' "
        "(by %s, reason=%r)", len(result["voided"]), api.get_path(plan),
        actor, reason)
    return result


def mirror_task_void(plan, seq, row_uid):
    """把"已作废"同步到对应的时间点任务（**不删任务**）。

    任务的 ``voided_*`` 三个字段是阶段 6c 新加的 schema 字段
    （见 ``content/stabilitytimepointtask.py``）。任务对象上没有这些字段时
    **只记日志**，不让"镜像失败"把已经落库的作废整体回滚 ——
    作废本身是明细行上的事实，任务标记只是展示层。
    """
    marker = None
    for candidate in (getattr(plan, "plan_details", None) or []):
        if not isinstance(candidate, dict):
            continue
        if row_uid and tp.get_row_uid(candidate) == row_uid:
            marker = void_marker(candidate)
            break
    if marker is None:
        marker = void_marker({})

    desired = (("voided_at", marker.get("voided_at") or u""),
               ("voided_by", marker.get("voided_by") or u""),
               ("void_reason", marker.get("void_reason") or u""))

    touched = 0
    try:
        children = list(plan.objectValues())
    except Exception:
        children = []
    for child in children:
        if api.get_portal_type(child) != "StabilityTimepointTask":
            continue
        if not tp.task_matches_row(child, row_uid, seq):
            continue
        for name, value in desired:
            try:
                if getattr(child, name, None) != value:
                    setattr(child, name, value)
            except Exception:
                logger.warning(
                    "Timepoint task '%s' has no '%s' field: void marker not "
                    "mirrored (plan '%s' seq %s)",
                    api.get_id(child), name, api.get_path(plan), seq)
                return touched
        try:
            child.reindexObject()
        except Exception:
            pass
        touched += 1
    return touched
