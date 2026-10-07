# -*- coding: utf-8 -*-
"""稳定性方案「状态」的唯一实现：状态机、冻结判据、状态变更的落库与留痕。

★ 本模块分两段，边界必须守住：

* **第 1 段：纯逻辑**（``normalize_state`` / ``can_transition`` / ``can_modify_plan`` …）
  —— 不 import Zope / bika，能直接用 py2.7 / py3 跑离线自检
  （与 ``timepoints.py`` / ``sampleautomation.py`` 同一套路）。
* **第 2 段：对象级**（读写方案对象、驱动工作流流转、迁移存量方案）
  —— ``api`` 一律**在函数内部** import，保证第 1 段能被离线自检 import。

为什么判定必须收在一个模块里
----------------------------

自动登样、方案编辑页、登样页、零点关联页、样品放置页、撤销登样页 —— **六处**都要问
"这个方案现在还能不能写"。判定散开写，必然会出现"看板说能登、服务端说不能"
这类自相矛盾（见《方案状态与过期规则-需求确认稿》的设计决策 D4 / D5）。

状态与流转
----------

::

    进行中 in_progress ──pause──▶ 已暂停 paused ──resume──▶ 进行中
         │                             │
         └────────── terminate ────────┴──▶ 已终止 terminated（终态）

三条铁律（需求原文见《方案状态与过期规则-需求确认稿》）：

1. **已终止是终态**：不可恢复、不可再终止（第 2 轮第 6 条）；
2. **暂停即完全冻结**：该方案下一切写操作都禁止（第 3 轮第 1、5 条）；
3. **空状态一律当「进行中」**：存量方案在迁移前后都必须照常自动登样 ——
   迁移没跑到也不能因为"读不到状态"就把全站方案停掉。

★ 为什么状态放在**工作流**里而不是普通字段：流转会自动产生审计快照
（``ObjectTransitionedEventHandler``，见 ``bika/lims/subscribers/configure.zcml``），
权限可按流转配，``review_state`` 又是现成的目录索引（列表/看板筛选走平台原生能力）。
"""

from maitux.stability.sampleautomation import as_text
from maitux.stability.sampleautomation import format_timestamp

try:  # py2 / py3 兼容（本环境是 py2.7，但自检脚本用 py3 跑）
    text_type = unicode  # noqa: F821
except NameError:
    text_type = str


# ══════════════════════════════════════════════════════════════════════════
# 第 1 段：纯逻辑（可离线自检）
# ══════════════════════════════════════════════════════════════════════════

# 工作流 id —— 与 profiles/default/workflows/senaite_stability_plan_workflow/
# definition.xml 的 workflow_id、workflows.xml 的绑定必须完全一致。
WORKFLOW_ID = u"senaite_stability_plan_workflow"

# ── 状态 ───────────────────────────────────────────────────────────────────
STATE_IN_PROGRESS = u"in_progress"
STATE_PAUSED = u"paused"
STATE_TERMINATED = u"terminated"

STATES = (STATE_IN_PROGRESS, STATE_PAUSED, STATE_TERMINATED)

# 状态 -> 界面标题（英文 msgid，渲染时按语言翻译）
STATE_TITLES = {
    STATE_IN_PROGRESS: u"In Progress",
    STATE_PAUSED: u"Paused",
    STATE_TERMINATED: u"Terminated",
}

# ── 流转 ───────────────────────────────────────────────────────────────────
TRANSITION_PAUSE = u"pause"
TRANSITION_RESUME = u"resume"
TRANSITION_TERMINATE = u"terminate"

TRANSITIONS = (TRANSITION_PAUSE, TRANSITION_RESUME, TRANSITION_TERMINATE)

# 状态 -> 该状态下**允许发出**的流转。
# ⚠️ 必须与 definition.xml 里的 <exit-transition> 逐条一致，否则会出现
#    "按钮在、点了不被工作流接受"（或反过来：工作流允许但界面没入口）。
ALLOWED_TRANSITIONS = {
    STATE_IN_PROGRESS: (TRANSITION_PAUSE, TRANSITION_TERMINATE),
    STATE_PAUSED: (TRANSITION_RESUME, TRANSITION_TERMINATE),
    STATE_TERMINATED: (),
}

# 流转 -> 目标状态
TARGET_STATE = {
    TRANSITION_PAUSE: STATE_PAUSED,
    TRANSITION_RESUME: STATE_IN_PROGRESS,
    TRANSITION_TERMINATE: STATE_TERMINATED,
}

# 流转 -> 审计动作名（进 Audit Log 的 Action 列；**英文原样落库，不翻译**）。
# 与工作流 transition_id 取同一个值：流转自动产生的快照里 action 就是
# transition id（来自 review_history），我们兜底补的那条也用同一个值，
# 两条路径的审计动作名必须一致，否则同一个动作会出现两种写法。
ACTION_BY_TRANSITION = {
    TRANSITION_PAUSE: u"pause",
    TRANSITION_RESUME: u"resume",
    TRANSITION_TERMINATE: u"terminate",
}

# ── 方案上的留痕字段（★ 必须是 schema 字段）────────────────────────────────
#
# 为什么必须是 schema 字段而不是普通属性：审计快照的数据来自
# ``SuperModel(obj).to_dict()``，它只遍历 **schema 字段** ——
# 普通属性（如明细行上的 revoked_at）根本不会进快照，
# 于是"暂停原因"在审计页里就永远看不到。
# （明细行的撤销三件套可以不做 schema 字段，是因为它们写在行备注里给人看；
#   方案级的这三件必须进快照，所以走 schema。见 content/stabilityplan.py。）
STATUS_CHANGED_AT_FIELD = "status_changed_at"
STATUS_CHANGED_BY_FIELD = "status_changed_by"
STATUS_REASON_FIELD = "status_reason"

# ── 拒绝原因码（界面按码取文案）────────────────────────────────────────────
#
# 取值刻意与 REASON_* / LINK_* / REVOKE_* / RESULT_* 都不重复 ——
# 各套码有自己的文案表，"按码找文案"一旦撞值就会查错表
# （这是 stage 3 的 LINK_NO_TARGET_DATE 定下的约定，这里沿用）。
BLOCK_OK = u"ok"
BLOCK_PLAN_PAUSED = u"plan_paused"
BLOCK_PLAN_TERMINATED = u"plan_terminated"
# 状态不认识（脏数据）：保守**不冻结**，但记日志 —— 见 can_modify_plan 的说明
BLOCK_UNKNOWN_STATE = u"unknown_plan_state"

# 流转被拒的两种情形
TRANSITION_NOT_ALLOWED = u"transition_not_allowed"

# 原因必填（口径与「撤销登样」完全一致：见 sampleautomation.REVOKE_REASON_MIN_LENGTH）
REASON_REQUIRED = u"reason_required"
REASON_MIN_LENGTH = 2


def normalize_state(value):
    """把任意形态的状态值归一成状态 token。

    **空值一律当「进行中」** —— 这是本模块最重要的一条容错：
      * 存量方案在迁移脚本跑到之前，工作流状态是空的；
      * 迁移若因故没跑（或新装站点顺序不同），读到的也是空；
    这两种情况下都必须**照常自动登样**，否则一次升级就等于把全站方案停掉。
    未知的非空值（脏数据）原样返回，由 :func:`is_frozen` 决定怎么处置。
    """
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    value = as_text(value).strip()
    return value or STATE_IN_PROGRESS


def state_title(state):
    """状态 -> 英文 msgid（渲染时翻译）；认不出的状态原样返回，便于排查。"""
    state = normalize_state(state)
    return STATE_TITLES.get(state, state)


def is_known_state(state):
    """是不是本模块认识的状态值。"""
    return normalize_state(state) in STATES


def is_frozen(state):
    """该状态下方案是否**完全冻结**（暂停 / 终止）。

    ★ 未知状态（脏数据）**不算冻结**：宁可让它照常工作并记日志，
      也不能因为"认不出"就把一个方案锁死 —— 锁死的代价是不可逆的
      （用户既不能编辑、也不能暂停/恢复来纠正）。
      真正会出问题的是"暂停了却还在自动登样"，而那需要状态**恰好等于**
      ``paused``，不受这里影响。
    """
    return normalize_state(state) in (STATE_PAUSED, STATE_TERMINATED)


def can_transition(state, transition):
    """这个状态下能不能发出这个流转。返回 ``(ok, reason)``。

    只判"状态机允许不允许"，不判权限、不判原因（那两层各有各的入口）。
    """
    state = normalize_state(state)
    if transition not in TRANSITIONS:
        return (False, TRANSITION_NOT_ALLOWED)
    if transition not in ALLOWED_TRANSITIONS.get(state, ()):
        return (False, TRANSITION_NOT_ALLOWED)
    return (True, BLOCK_OK)


def target_state(transition):
    """流转的目标状态；未知流转返回 ``None``。"""
    return TARGET_STATE.get(transition)


def can_modify_plan(state):
    """该状态下的方案还能不能被修改（编辑、登样、关联、放置、撤销、删加行）。

    返回 ``(ok, reason)``；``reason`` 是**拒绝**的原因码（``ok`` 时是 ``BLOCK_OK``）。
    """
    state = normalize_state(state)
    if state == STATE_PAUSED:
        return (False, BLOCK_PLAN_PAUSED)
    if state == STATE_TERMINATED:
        return (False, BLOCK_PLAN_TERMINATED)
    return (True, BLOCK_OK)


def can_auto_generate(state):
    """该状态下允不允许**自动登样**（到期扫描）。

    只有「进行中」允许。暂停 / 终止一律不允许 —— 这是需求里"暂停后
    到时间不再自动请验"的落点。
    """
    return normalize_state(state) == STATE_IN_PROGRESS


def reason_is_blank(reason):
    """状态变更原因算不算"没填"（去空白后长度不足即算没填）。

    ★ 与「撤销登样」用**同一条**判据（``sampleautomation.REVOKE_REASON_MIN_LENGTH``），
      避免出现"撤销 2 个字才算填、暂停 1 个字也算填"这种两套口径。
    """
    return len(as_text(reason).strip()) < REASON_MIN_LENGTH


# ── 样品（AR）的「完成」判定（阶段 6a）────────────────────────────────────
#
# 需求口径（第 2 轮第 5 条）：**"样品完成 = 结果录入完成并且审核"**。
# 本部署的样品走 ``senaite_sample_workflow``，共 13 个状态：
#   sample_registered / scheduled_sampling / to_be_sampled / sample_due /
#   sample_received / to_be_verified / to_be_preserved / verified / published /
#   rejected / invalid / cancelled / dispatched
#
# ★ 只用 AR 的**工作流状态**判定，不逐个分析项去数结果 ——
#   AR 状态本身已经涵盖"结果齐 + 审核"，逐项去数会引入第二个真相
#   （而且"结果录完了但没审核"= to_be_verified，正是需求里明确要算**未完成**的那一种）。
SAMPLE_STATES_FINISHED = (u"verified", u"published")
# 终态：除了"完成"，还包括被否掉的三种。阶段 6c 的「作废时间点」拿它当
# 前置条件（样品必须在终态才允许作废时间点），见需求确认稿 C1。
SAMPLE_STATES_TERMINAL = (u"verified", u"published", u"rejected", u"invalid",
                          u"cancelled")


def normalize_sample_state(value):
    """把任意形态的样品状态值归一成 token（空值返回空串）。"""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return as_text(value).strip()


def sample_is_finished(state):
    """样品是否**已完成**（结果录入完成且已审核）。

    「未完成」的判定就是 ``not sample_is_finished(state)`` ——
    ``rejected`` / ``invalid`` / ``cancelled`` **都算未完成**（第 3 轮第 6 条），
    所以终止确认时它们同样会被列出来拦住用户。
    """
    return normalize_sample_state(state) in SAMPLE_STATES_FINISHED


def sample_is_terminal(state):
    """样品是否处于**终态**（不会再变）：完成或被否掉都算。"""
    return normalize_sample_state(state) in SAMPLE_STATES_TERMINAL


# ── 阶段 6c：行「作废」的前置条件（纯逻辑部分）────────────────────────────
#
# 需求确认稿 2.5 / C1：任何"可删"的行都改走作废；**有关联样品时**，
# 样品必须已达终态，否则拦下并提示「该时间点关联的样品 XXX 尚未完成…」。
#
# ★ 为什么放在这里（而不是 voiding.py）：本函数的两个输入
#   —— "行还能不能作废"与"样品状态" —— 分别属于 timepoints 与 plan_status，
#   而本模块正好同时拥有这两套口径（终态词表在 22 行处）。
#   放在对象级模块里就得靠桩模块才能自检（本包的自检只加载**纯**模块）。
VOID_OK = u"ok"
VOID_UNKNOWN_ROW = u"void_unknown_row"
VOID_ALREADY_VOIDED = u"void_already_voided"
# 状态层面不允许作废（已登样 / 已完成 / 认不出的脏状态）—— 与"不许删"同一口径
VOID_ROW_PROTECTED = u"void_row_protected"
# C1 前置条件未满足：关联的样品还没到终态
VOID_SAMPLE_UNFINISHED = u"void_sample_unfinished"

VOID_CODES = (VOID_OK, VOID_UNKNOWN_ROW, VOID_ALREADY_VOIDED,
              VOID_ROW_PROTECTED, VOID_SAMPLE_UNFINISHED)


def void_precondition(row, sample_state=None, sample_id=u""):
    """**纯逻辑**的作废判据：``(ok, reason_code, detail)``。

    1. 不是 dict -> ``VOID_UNKNOWN_ROW``；
    2. 已经作废过 -> ``VOID_ALREADY_VOIDED``
       （作废是一次性的：再作废一次会把原来的时间/人/原因覆盖掉，
       等于把审计痕迹弄脏）；
    3. 状态层面不可作废（已登样 / 已完成 / 认不出的脏状态）->
       ``VOID_ROW_PROTECTED``（既有"不许删"的口径，6c 沿用）；
    4. 行上关联了样品、且样品**未达终态** -> ``VOID_SAMPLE_UNFINISHED``
       （C1；`sample_id` 只用于提示"哪个样品还没完成"，不参与判定）；
    5. 其余 -> ``(True, VOID_OK, u"")``。

    ★ "读不到样品状态"按**未完成**处理：那说明样品对象已经取不到了
      （被删 / 目录陈旧），放行等于把一个未知状态的样品"作废掉"。
      保守拦下的代价只是让用户去找管理员确认。
    """
    from maitux.stability.timepoints import get_row_uid
    from maitux.stability.timepoints import is_voidable
    from maitux.stability.timepoints import is_voided

    if not isinstance(row, dict):
        return (False, VOID_UNKNOWN_ROW, u"")
    if is_voided(row):
        return (False, VOID_ALREADY_VOIDED, get_row_uid(row))
    if not is_voidable(row):
        return (False, VOID_ROW_PROTECTED, get_row_uid(row))
    sample_uid = first_uid(row.get("analysis_request"))
    if not sample_uid:
        return (True, VOID_OK, u"")
    if not sample_is_terminal(sample_state):
        return (False, VOID_SAMPLE_UNFINISHED,
                u"%s (%s)" % (as_text(sample_id).strip() or sample_uid,
                              normalize_sample_state(sample_state) or u"unknown"))
    return (True, VOID_OK, u"")


def first_uid(value):
    """行上的引用字段在 DataGrid 里是 ``[uid]``（也容忍单值 / 空值 / 脏值）。"""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return as_text(value).strip()


def void_reason_text(code, detail=u""):
    """把作废原因码摊成一句可读的英文（日志 / 审计 extra / 页面文案复用）。"""
    if code == VOID_OK:
        return u"discarded"
    if code == VOID_SAMPLE_UNFINISHED:
        return u"sample not finished: %s" % (as_text(detail).strip() or u"?")
    if code == VOID_ALREADY_VOIDED:
        return u"already discarded"
    if code == VOID_ROW_PROTECTED:
        return u"row is not deletable in its current state"
    return u"unknown row"


def transition_available(state, transition):
    """界面用：某状态下某个动作按钮该不该出现。"""
    ok, _reason = can_transition(state, transition)
    return ok


# ══════════════════════════════════════════════════════════════════════════
# 第 2 段：对象级（api 在函数内 import，保住第 1 段的离线可测性）
# ══════════════════════════════════════════════════════════════════════════


def get_plan_state(plan):
    """读方案当前状态（归一化后）。对象为 None / 读不到时一律返回「进行中」。"""
    if plan is None:
        return STATE_IN_PROGRESS
    try:
        from bika.lims import api
        return normalize_state(api.get_review_status(plan))
    except Exception:
        return STATE_IN_PROGRESS


def _workflow_tool():
    from bika.lims import api
    return api.get_tool("portal_workflow")


def ensure_plan_state(plan, actor=u"", only_if_missing=False):
    """保证方案有一个**本工作流的状态记录**（幂等）。

    为什么需要它：换了工作流绑定之后，存量方案在新工作流下**没有状态记录** ——
    ``getInfoFor`` 返回空串。虽然 :func:`normalize_state` 会把空当「进行中」，
    但空状态在目录里也是空、在列表页的状态列里也是空，等于"状态没生效"。
    所以升级步骤要显式补一次。

    两条路径（顺序有讲究）：

    1. **``notifyCreated``** —— CMF 给新对象设初始状态的标准路径，
       会走工作流的 ``initial_state``。★ 它比显式 ``setStatusOf`` 稳：
       ``setStatusOf`` 内部要 ``getWorkflowById()`` 拿工作流对象，
       拿不到时抛 ComponentLookupError（真机实测踩到过）。
    2. **``setStatusOf``** —— 路径 1 没生效时的兜底。

    :param only_if_missing: True 时只在"完全没有状态"时才写
        （升级步骤用这个 —— 已经是 paused / terminated 的方案绝不能被覆盖）。
    :returns: True 表示写过（或本来就有）
    """
    if plan is None:
        return False
    from senaite.core import logger

    try:
        tool = _workflow_tool()
        if tool is None:
            return False
        current = tool.getInfoFor(plan, "review_state", "")
        if current:
            return True

        # 路径 1：标准路径
        try:
            tool.notifyCreated(plan)
        except Exception:
            logger.exception(
                "maitux.stability: notifyCreated failed for %r", plan)
        if tool.getInfoFor(plan, "review_state", ""):
            return True

        # 路径 2：显式写状态记录
        tool.setStatusOf(WORKFLOW_ID, plan, {
            "review_state": STATE_IN_PROGRESS,
            "action": None,
            "actor": as_text(actor) or u"system",
            "time": _now(),
            "comments": u"Initial state",
        })
        tool.updateRoleMappingsFor(plan)
        after = tool.getInfoFor(plan, "review_state", "")
        if not after:
            logger.error(
                "maitux.stability: could not initialize the workflow state of "
                "%r (workflow '%s' may be missing from portal_workflow)",
                plan, WORKFLOW_ID)
            return False
        return True
    except Exception:
        logger.exception(
            "maitux.stability: failed to ensure the workflow state of %r", plan)
        return False


def workflow_diagnostics():
    """工作流与绑定的诊断快照（迁移脚本与排查用）。

    为什么要它：这类问题（工作流对象没建出来 / 绑定没生效 / 状态记录缺失）
    的症状都一样 —— "界面上状态是空的"，而原因完全不同。
    把事实一次性摊出来比猜快得多（阶段 6a 真机迁移就是这么定位的）。
    """
    out = {"all_count": 0, "stability_ids": [], "has_ours": False,
           "initial_state": u"", "our_states": [], "chain": [], "error": u""}
    try:
        tool = _workflow_tool()
        if tool is None:
            out["error"] = u"portal_workflow not found"
            return out
        ids = list(tool.objectIds() or [])
        out["all_count"] = len(ids)
        out["stability_ids"] = [i for i in ids if "stability" in i]
        out["has_ours"] = WORKFLOW_ID in ids
        if out["has_ours"]:
            wf = tool[WORKFLOW_ID]
            out["initial_state"] = as_text(getattr(wf, "initial_state", u""))
            states = getattr(wf, "states", None)
            out["our_states"] = list(states.objectIds() or []) if states \
                is not None else []
        out["chain"] = list(tool.getChainForPortalType("StabilityPlan") or ())
    except Exception:
        from senaite.core import logger
        logger.exception("maitux.stability: workflow diagnostics failed")
        out["error"] = u"exception (see log)"
    return out


def _now():
    try:
        from DateTime import DateTime
        return DateTime()
    except Exception:
        return None


def change_plan_status(plan, transition, reason, actor=u""):
    """执行一次状态流转并留痕 —— **唯一实现**。

    步骤（顺序有讲究，别调换）：

    1. **先校验**：状态机允许吗？原因填了吗？（不通过就一个字段都不写）
    2. **先写留痕字段**（``status_reason`` / ``status_changed_by`` / ``status_changed_at``）
       —— ★ 必须在流转**之前**写：流转会触发 ``ObjectTransitionedEventHandler``
       自动拍一张快照，先写字段才能让这一张快照**同时**包含"新状态 + 原因"。
       顺序反了的话原因字段不在快照里，就得为同一个动作再补一张 —— 审计页上
       一个动作两条记录，反而更难读。
    3. **驱动工作流流转**（``doActionFor``，comment 传原因 → 进快照的 comments）。
    4. **兜底补快照**：万一流转没产生快照（事件没接上 / 对象不支持快照），
       这里显式补一条，保证"每一次状态变更都有痕迹"不是空话。
    5. **追加状态流水**（annotation，界面上的「状态变更历史」面板读它）。

    :returns: ``(ok, payload)``；payload 含 ``state_before`` / ``state_after`` /
        ``action`` / ``error`` / ``snapshot_added``。
    """
    payload = {
        "state_before": get_plan_state(plan),
        "state_after": None,
        "action": ACTION_BY_TRANSITION.get(transition, as_text(transition)),
        "error": BLOCK_OK,
        "snapshot_added": False,
    }
    if plan is None:
        payload["error"] = TRANSITION_NOT_ALLOWED
        return (False, payload)

    # 1) 校验
    ok, reason_code = can_transition(payload["state_before"], transition)
    if not ok:
        payload["error"] = reason_code
        return (False, payload)
    reason = as_text(reason).strip()
    if reason_is_blank(reason):
        payload["error"] = REASON_REQUIRED
        return (False, payload)

    from maitux.stability import audit

    try:
        actor = as_text(actor) or _current_user_id()
    except Exception:
        actor = as_text(actor)

    # 2) 先写留痕字段（进快照）
    try:
        _write_status_fields(plan, actor, reason)
    except Exception:
        from senaite.core import logger
        logger.exception(
            "Failed to write the status change fields for %r", plan)

    # 3) 流转
    tool = _workflow_tool()
    if tool is None:
        payload["error"] = TRANSITION_NOT_ALLOWED
        return (False, payload)

    count_before = audit.snapshot_count(plan)
    try:
        tool.doActionFor(plan, transition, comment=reason)
    except Exception:
        from senaite.core import logger
        logger.exception(
            "Workflow transition '%s' failed for %r", transition, plan)
        payload["error"] = TRANSITION_NOT_ALLOWED
        return (False, payload)

    state_after = get_plan_state(plan)
    payload["state_after"] = state_after
    if state_after != target_state(transition):
        # 流转"执行了但状态没变"：说明工作流被改过 / 绑定没生效。
        # 不留假痕迹：报错让调用方提示用户，日志里能看到。
        from senaite.core import logger
        logger.error(
            "Transition '%s' on %r did not reach state '%s' (got '%s')",
            transition, plan, target_state(transition), state_after)
        payload["error"] = TRANSITION_NOT_ALLOWED
        return (False, payload)

    # 4) 兜底补快照
    if audit.snapshot_count(plan) <= count_before:
        payload["snapshot_added"] = audit.record_plan_audit(
            plan, action=payload["action"], comments=reason, actor=actor)

    # 5) 状态流水
    try:
        audit.append_status_history(plan, state_before=payload["state_before"],
                                    state_after=state_after, transition=transition,
                                    reason=reason, actor=actor)
    except Exception:
        from senaite.core import logger
        logger.exception(
            "Failed to append the status history for %r", plan)

    return (True, payload)


def _current_user_id():
    try:
        from bika.lims import api
        return as_text(api.get_current_user().getId())
    except Exception:
        return u""


def _write_status_fields(plan, actor, reason):
    """把留痕三件套写进方案（并推进修改时间，见 audit 模块的坑 #2 说明）。"""
    setattr(plan, STATUS_CHANGED_AT_FIELD, format_timestamp(_now()))
    setattr(plan, STATUS_CHANGED_BY_FIELD, actor)
    setattr(plan, STATUS_REASON_FIELD, reason)
    try:
        from DateTime import DateTime
        plan.setModificationDate(DateTime())
    except Exception:
        pass


def plan_status_summary(plan):
    """把方案状态摊平成一份可读摘要（页面、日志、自检都用它）。

    与 ``automation.describe()`` 同一套路：只描述"现在是什么状态"，
    不判定能不能操作（那是 :func:`can_modify_plan` 的事）。
    """
    state = get_plan_state(plan)
    ok, reason = can_modify_plan(state)
    return {
        "state": state,
        "state_title": state_title(state),
        "frozen": is_frozen(state),
        "can_modify": ok,
        "block_reason": reason if not ok else u"",
        "can_auto_generate": can_auto_generate(state),
        "transitions": [t for t in TRANSITIONS
                        if transition_available(state, t)],
        "changed_at": as_text(getattr(plan, STATUS_CHANGED_AT_FIELD, u"")),
        "changed_by": as_text(getattr(plan, STATUS_CHANGED_BY_FIELD, u"")),
        "reason": as_text(getattr(plan, STATUS_REASON_FIELD, u"")),
    }


def get_plan_samples(plan):
    """方案下所有**已登样**的时间点行 -> 样品概览。

    用途：终止确认页要列出"哪些样品还没完成"，方案页的状态面板也要显示同一份清单。

    返回列表（按行号升序），每项：

    ``row_seq`` / ``detail_uid`` / ``timepoint_months`` /
    ``sample_uid`` / ``sample_id`` / ``sample_url`` / ``sample_state`` / ``finished``

    ★ 样品对象取不到时（被删 / 未编目）``sample_state`` 为空、``finished`` 为 False：
      宁可多拦一次让用户看一眼，也不能因为"读不到状态"就当成已完成放行 ——
      终止是终态，放行错了就没有回头路。
    """
    from bika.lims import api
    from maitux.stability.timepoints import get_row_uid
    from maitux.stability.timepoints import normalize_months

    if plan is None:
        return []
    rows = list(getattr(plan, "plan_details", None) or [])
    result = []
    for seq, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        sample_uid = _first_value(row.get("analysis_request"))
        if not sample_uid:
            continue
        item = {
            "row_seq": seq,
            "detail_uid": get_row_uid(row),
            "timepoint_months": normalize_months(row.get("timepoint_days", 0)),
            "sample_uid": as_text(sample_uid),
            "sample_id": u"",
            "sample_url": u"",
            "sample_state": u"",
            "finished": False,
        }
        sample = None
        try:
            if api.is_uid(item["sample_uid"]):
                sample = api.get_object_by_uid(item["sample_uid"], None)
        except Exception:
            sample = None
        if sample is not None:
            try:
                item["sample_id"] = api.get_id(sample) or u""
                item["sample_url"] = api.get_url(sample)
                item["sample_state"] = normalize_sample_state(
                    api.get_review_status(sample))
                item["finished"] = sample_is_finished(item["sample_state"])
            except Exception:
                pass
        result.append(item)
    return result


def unfinished_sample_count(plan):
    """方案下**未完成**的样品数（终止确认的判据，也用于提示）。"""
    return len([item for item in get_plan_samples(plan)
                if not item.get("finished")])


def _first_value(value):
    """取引用字段的第一个值（DataGrid 里常是单元素列表）。"""
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def iter_plans(portal=None):
    """列出站点上所有 StabilityPlan（升级步骤、自检、迁移都用它）。

    ★ 必须查 **SETUP_CATALOG**（``senaite_catalog_setup``）：
      ``StabilityPlan`` 的 ``_catalogs`` 是 ``[SETUP_CATALOG]``，
      senaite 的目录总闸门只会把它编进 setup 目录（外加自动追加的审计目录）——
      **portal_catalog / uid_catalog 里根本没有它**。
      查错目录不会报错，只会**静默返回空列表**，于是"迁移存量方案"变成
      "一个都没迁移"，而且看不出任何异常（本仓库踩过同类坑：
      ``samplegeneration.find_link_conflict`` 的注释里也专门写了这一点）。

    `portal` 参数只为兼容旧签名，实际不使用。
    """
    from bika.lims import api
    from senaite.core.catalog import SETUP_CATALOG

    plans = []
    try:
        brains = api.search({"portal_type": "StabilityPlan",
                             "sort_on": "created"}, catalog=SETUP_CATALOG)
    except Exception:
        from senaite.core import logger
        logger.exception(
            "maitux.stability: failed to list stability plans from %s",
            SETUP_CATALOG)
        return []
    for brain in brains:
        try:
            obj = api.get_object(brain)
        except Exception:
            continue
        if api.get_portal_type(obj) == "StabilityPlan":
            plans.append(obj)
    return plans


def migrate_existing_plans(actor=u"upgrade"):
    """给存量方案补工作流状态（幂等）。返回补过状态的方案数。

    只补"完全没有状态"的：已经是 ``paused`` / ``terminated`` 的方案
    **绝不能被覆盖** —— 那会静默解冻一个被人工停掉的方案。
    """
    changed = 0
    for plan in iter_plans():
        try:
            tool = _workflow_tool()
            if tool is None:
                break
            if tool.getInfoFor(plan, "review_state", ""):
                continue
            if ensure_plan_state(plan, actor=actor, only_if_missing=True):
                changed += 1
        except Exception:
            from senaite.core import logger
            logger.exception(
                "Failed to migrate the workflow state of %r", plan)
    return changed
