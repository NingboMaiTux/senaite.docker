# -*- coding: utf-8 -*-
"""已发布样品/测试重新激活服务。"""

from collections import OrderedDict
import json

from bika.lims import api
from bika.lims.api.snapshot import get_storage
from bika.lims.api.snapshot import take_snapshot
from bika.lims.api.user import get_user_id
from bika.lims.interfaces import IRejected
from bika.lims.subscribers.auditlog import reindex_object
from bika.lims.utils import changeWorkflowState
from bika.lims.workflow import isTransitionAllowed
from Products.CMFCore.WorkflowCore import WorkflowException
from zope.interface import noLongerProvides


ANALYSIS_PORTAL_TYPES = (
    "Analysis",
)

SAMPLE_PORTAL_TYPES = (
    "AnalysisRequest",
)

ANALYSIS_WORKFLOW_ID = "senaite_analysis_workflow"
WORKSHEET_WORKFLOW_ID = "senaite_worksheet_workflow"
REACTIVATE_REASON_FIELD = u"重新激活原因"

WORKSHEET_ROLLBACK_TRANSITIONS = {
    "to_be_verified": "rollback_to_open",
}


def reactivate_objects(objects, reason):
    """批量激活对象，并避免重复处理同一样品。"""
    validate_reason(reason)
    objects = unique_objects(objects)
    selected_sample_uids = set()
    reactivated_sample_uids = set()
    summaries = []

    for obj in objects:
        portal_type = getattr(obj, "portal_type", "")
        if portal_type in SAMPLE_PORTAL_TYPES:
            summaries.append(reactivate_sample(obj, reason))
            sample_uid = api.get_uid(obj)
            selected_sample_uids.add(sample_uid)
            reactivated_sample_uids.add(sample_uid)

    for obj in objects:
        portal_type = getattr(obj, "portal_type", "")
        if portal_type not in ANALYSIS_PORTAL_TYPES:
            continue
        sample = get_parent_sample(obj)
        sample_uid = sample and api.get_uid(sample) or None
        if sample_uid in selected_sample_uids:
            continue
        summaries.append(reactivate_analysis(
            obj,
            reason,
            reactivate_parent_sample=sample_uid not in reactivated_sample_uids))
        if sample_uid:
            reactivated_sample_uids.add(sample_uid)

    return summaries


def reactivate_sample(sample, reason):
    """重新激活样品，并联动其下测试和工作表。"""
    validate_reason(reason)

    # 样品自身的原状态决定了它底下 rejected 分析项的来历，所以必须在样品迁移
    # **之前**取，迁移之后就取不到了。见 should_reactivate_with_sample。
    origin_state = api.get_review_status(sample)

    transition_object(sample, "reactivate", reason)

    analyses = []
    worksheets = []
    seen_worksheets = set()
    for analysis in get_sample_analyses(sample):
        if not should_reactivate_with_sample(analysis, origin_state):
            continue
        analyses.append(analysis)
        reactivate_analysis_object(analysis, reason)

        worksheet = get_analysis_worksheet(analysis)
        worksheet_uid = worksheet and api.get_uid(worksheet) or None
        if worksheet is None or worksheet_uid in seen_worksheets:
            continue
        rollback_worksheet(worksheet, reason)
        seen_worksheets.add(worksheet_uid)
        worksheets.append(worksheet)

    audit_reactivate(
        sample,
        target_type="sample",
        reason=reason,
        sample=sample,
        analyses=analyses,
        worksheets=worksheets,
    )
    reindex_related([sample] + analyses + worksheets)
    return {
        "sample_uid": api.get_uid(sample),
        "analysis_count": len(analyses),
        "worksheet_count": len(worksheets),
    }


def should_reactivate_with_sample(analysis, sample_origin_state):
    """整单激活样品时，这条分析项要不要跟着回来。

    **被单独拒绝的分析项不跟着回来。** 报告就是按「不含它」的形态发出去的，
    整单激活不该推翻那个决定；客户要恢复它，单独点那一条的 Reactivate
    —— 分析项自己有独立的激活入口，两次操作即可。

    唯一的例外是**样品自己就是被拒绝的**：那种情况下它底下的 rejected 是
    ``after_reject`` 级联出来的，不是一条一条独立决定的，所以应当一起回来。
    这就是为什么要用样品**迁移之前**的状态来判断。

    其余状态一律看「这条 transition 现在拿不拿得到」：

    - ``retracted`` 是 retract 留下的历史副本（原件已另生成重测项），没有出口
    - ``cancelled`` 只能走样品的 reinstate，也没有出口

    ★ 这一步同时是**防崩溃的兜底**：改之前，样品里只要有一条 retracted，
      ``transition_object`` 就会抛 RuntimeError，把整单激活全部回滚 ——
      而那条分析项本来就不该被激活。
    """
    state = api.get_review_status(analysis)

    if state == "rejected":
        return sample_origin_state == "rejected"

    return isTransitionAllowed(analysis, "reactivate")


def reactivate_analysis(analysis, reason, reactivate_parent_sample=True):
    """重新激活单条测试，并联动父样品和所属工作表。"""
    validate_reason(reason)

    sample = get_parent_sample(analysis)

    # ★ 分析项先走，父样品后退 —— 这个顺序是硬要求，不是风格问题。
    # guard_rollback_to_receive 要求样品下至少有一条 unassigned/assigned 的
    # 分析项；在本条分析项还没迁移之前，那个条件必然不成立，样品会纹丝不动。
    # core 的 after_retract 也是这个顺序（先建好重测副本，再回退样品）。
    reactivate_analysis_object(analysis, reason)

    if reactivate_parent_sample and sample is not None:
        rollback_parent_sample(sample, reason)

    worksheet = get_analysis_worksheet(analysis)
    if worksheet is not None:
        rollback_worksheet(worksheet, reason)

    audit_reactivate(
        analysis,
        target_type="analysis",
        reason=reason,
        sample=sample,
        analyses=[analysis],
        worksheets=worksheet and [worksheet] or [],
    )
    related = [analysis]
    if sample is not None:
        related.append(sample)
    if worksheet is not None:
        related.append(worksheet)
    reindex_related(related)
    return {
        "sample_uid": sample and api.get_uid(sample) or None,
        "analysis_uids": [api.get_uid(analysis)],
        "worksheet_uids": worksheet and [api.get_uid(worksheet)] or [],
    }


def reactivate_analysis_object(analysis, reason):
    """分析项走单一 Reactivate 落到 unassigned，仍挂着工作表的再同步回 assigned。

    落点必须分流：工作表的"添加分析"列表只取 review_state=unassigned，所以
    没有工作表却停在 assigned 的分析项既不在任何工作表上、又进不了任何工作表
    的候选列表 —— 是个谁也够不着的孤儿。被拒绝/被取消的分析项尤其如此，
    core 的 after_reject / after_cancel 都会先把它们摘出工作表。

    为什么不是"先落 unassigned 再 doActionFor(assign) 补回去"：guard_assign
    第一句就是 `if not is_worksheet_context(): return False`，从样品页发起时
    永远为假，而且**静默失败** —— 分析项会不声不响地留在 unassigned。
    """
    # 落点由移动之前的事实决定，所以先把工作表抓住再做 transition。
    worksheet = get_analysis_worksheet(analysis)
    was_rejected = IRejected.providedBy(analysis)

    transition_object(analysis, "reactivate", reason)

    if was_rejected:
        clear_reject_residue(analysis)

    if worksheet is None:
        # 不在工作表上：unassigned 就是终点，也正是能被工作表重新收录的状态。
        return

    sync_analysis_to_assigned(analysis, worksheet)


def rollback_parent_sample(sample, reason):
    """把父样品拉回可继续录入的状态。返回实际执行的 transition id 或 None。

    **优先走原生 `rollback_to_receive`**，理由不只是"对齐 core"：
    它的 after 处理会顺手清掉样品的 `IVerified` 标记，而本包的 `reactivate`
    不会 —— 那是样品侧与分析项侧 `IRejected` 同构的一处残留。

    `published` 样品**没有** `rollback_to_receive` 这条出口（状态层面就没有，
    不是 guard 挡的），所以才回落到本包的 `reactivate`。

    两条都不可用时什么都不做，这也是正确的：样品可能本来就在
    `sample_received`，或者处于 rejected / cancelled 这类不该被单条分析项
    拖着走的状态。**用 isTransitionAllowed 判断而不是拿状态名硬编码**，
    避免再出现"改了样品侧范围、这里的状态清单就过期"的情况。
    """
    for transition_id in ("rollback_to_receive", "reactivate"):
        if isTransitionAllowed(sample, transition_id):
            transition_object(sample, transition_id, reason)
            return transition_id
    return None


def clear_reject_residue(analysis):
    """清掉 reject 在这条分析项自己身上留下的痕迹。

    core 的 after_reject 做了三件事：打 IRejected 标记、把附件的 RenderInReport
    置 False、把下游一并拒绝。前两件是这条分析项**自己**的状态，激活时必须还原；
    第三件涉及别的对象，按「善意提醒、不级联」的决定交给确认页去提示，
    这里绝不代劳（core 的 reject 本身也只向下游单向级联，不动上游）。

    ★ IRejected 不是装饰性标记：``get_dependents()`` 默认（with_retests=False）
    会把带这个标记的分析项从依赖集合里滤掉。不清掉它，这条分析项**状态活了、
    却仍被排除在重算之外** —— 录入上游结果时不会被重新计算，而且不报错。
    """
    noLongerProvides(analysis, IRejected)

    # after_reject 把该分析项的附件全部置为不进报告，这里全部恢复。
    # ⚠ 这一步是不对称的：如果某个附件在被拒绝**之前**就已经被人为设成不进报告，
    # 这里会把它一并打开。reject 没有记录改动前的值，无从区分。
    for attachment in analysis.getAttachment():
        attachment.setRenderInReport(True)


def get_reactivate_warnings(objects):
    """确认页要展示的提醒。**只读，不改变任何对象。**

    两个方向各提醒一次（F13：core 的 reject 只向下游级联，不动上游）：

    - 激活**上游**：当初被它连累拒绝的下游不会跟着活过来，列出来让人知道
    - 激活**下游**：它依赖的上游若仍是 rejected，本项激活后也算不出结果

    ★ 两处都必须传 ``with_retests=True``。``getDependents`` / ``getDependencies``
    默认会把 retracted / rejected / retested 的项滤掉 —— 而我们要找的**恰恰就是
    那些 rejected 的**。用默认参数的话，这个函数会永远返回空列表，
    而且看起来一切正常。
    """
    warnings = []
    for obj in unique_objects(objects):
        portal_type = getattr(obj, "portal_type", "")

        # 整单激活样品：把不会跟着回来的分析项列出来。不提示的话，
        # 「被单独拒绝的项要自己再点一次」这个设计客户根本发现不了。
        if portal_type in SAMPLE_PORTAL_TYPES:
            skipped = get_skipped_analyses(obj)
            if skipped:
                warnings.append({
                    "kind": "skipped",
                    "analysis": api.safe_unicode(api.get_id(obj)),
                    "items": skipped,
                })
            continue

        if portal_type not in ANALYSIS_PORTAL_TYPES:
            continue

        title = api.safe_unicode(api.get_title(obj))

        downstream = get_rejected_related(obj, "getDependents")
        if downstream:
            warnings.append({
                "kind": "dependents",
                "analysis": title,
                "items": downstream,
            })

        upstream = get_rejected_related(obj, "getDependencies")
        if upstream:
            warnings.append({
                "kind": "dependencies",
                "analysis": title,
                "items": upstream,
            })
    return warnings


def get_skipped_analyses(sample):
    """整单激活样品时**不会**跟着回来的那些分析项，返回标题列表。"""
    origin_state = api.get_review_status(sample)
    titles = []
    for analysis in get_sample_analyses(sample):
        if should_reactivate_with_sample(analysis, origin_state):
            continue
        titles.append(api.safe_unicode(api.get_title(analysis)))
    return titles


def get_rejected_related(analysis, method_name):
    """取该分析项上游或下游中**仍处于拒绝状态**的那些，返回标题列表。"""
    method = getattr(analysis, method_name, None)
    if method is None:
        return []
    try:
        related = method(with_retests=True)
    except TypeError:
        # 兼容不接受 with_retests 参数的实现
        related = method()
    titles = []
    for item in related or []:
        item = api.get_object(item)
        if IRejected.providedBy(item):
            titles.append(api.safe_unicode(api.get_title(item)))
    return titles


def sync_analysis_to_assigned(analysis, worksheet):
    """把仍挂在工作表上的分析项从 unassigned 同步回 assigned。

    这里不再写审计快照：reactivate transition 本身已经带着原因记进了该分析项的
    workflow history，本步只是把状态摆回与"它还在工作表上"这一事实相符的位置。
    这与 sync_worksheet_to_open 不同 —— 那边整条路径上没有任何 transition
    承载原因，所以必须自己补一条快照。

    action 取一个可识别的名字，让 workflow history 里能看出这一步是谁干的。
    """
    changeWorkflowState(
        analysis,
        ANALYSIS_WORKFLOW_ID,
        "assigned",
        trigger_events=False,
        action="reactivate_assign_sync",
    )
    return worksheet


def rollback_worksheet(worksheet, reason):
    """仅在工作表处于待审核/已审核时回到 open。"""
    state = api.get_review_status(worksheet)
    if state == "verified":
        sync_worksheet_to_open(worksheet, reason, state)
        return
    transition_id = WORKSHEET_ROLLBACK_TRANSITIONS.get(state)
    if not transition_id:
        return
    # 待审核工作表官方支持 rollback_to_open，优先走原生 transition。
    transition_object(worksheet, transition_id, reason)


def sync_worksheet_to_open(worksheet, reason, source_state):
    """在无合法 transition 时，受控同步工作表状态到 open 并记录审计。"""
    # verified 工作表没有 rollback_to_open，而其 retract guard 又依赖子分析可 retract，
    # 在 reactivate 场景下这两个条件都不成立，只能走受控状态同步。
    changeWorkflowState(
        worksheet,
        WORKSHEET_WORKFLOW_ID,
        "open",
        trigger_events=False,
        action="reactivate_worksheet_sync",
    )
    store_reactivate_snapshot(
        worksheet,
        action="reactivate_worksheet_sync",
        actor=get_user_id(),
        reason=reason,
        source_state=source_state,
        target_state="open",
    )


def transition_object(obj, transition_id, reason):
    """执行工作流迁移，并透传审计备注。"""
    workflow_tool = api.get_tool("portal_workflow")
    try:
        workflow_tool.doActionFor(obj, transition_id, comment=reason)
    except WorkflowException as exc:
        message = normalize_workflow_error_message(exc, transition_id)
        raise RuntimeError(message)
    return obj


def normalize_workflow_error_message(error, action_id):
    """将工作流异常中的占位符替换为真实 transition 名称。"""
    message = str(error)
    return message.replace("${action_id}", action_id)


def audit_reactivate(root, target_type, reason, sample=None, analyses=None, worksheets=None):
    """在根对象上追加一条重激活汇总审计。"""
    analyses = analyses or []
    worksheets = worksheets or []
    metadata = {
        "action": "reactivate_audit",
        "actor": get_user_id(),
        "reason": reason,
        "target_type": target_type,
        "sample_uid": sample and api.get_uid(sample) or None,
        "analysis_uids": [api.get_uid(item) for item in analyses],
        "worksheet_uids": [api.get_uid(item) for item in worksheets],
    }
    store_reactivate_snapshot(root, **metadata)


def store_reactivate_snapshot(obj, **metadata):
    """写入带“重新激活原因”字段的审计快照，供原生 Changes diff 直接展示。"""
    reason = metadata.get("reason", u"")
    snapshot = take_snapshot(obj, store=False, **metadata)
    # 将原因写入快照正文而不是仅写 metadata，这样无需修改 core 页面也会进入 diff。
    snapshot[REACTIVATE_REASON_FIELD] = reason
    storage = get_storage(obj)
    storage.append(json.dumps(snapshot))
    return snapshot


def reindex_related(objects):
    """重建对象与审计索引。"""
    for obj in unique_objects(objects):
        if hasattr(obj, "reindexObject"):
            obj.reindexObject()
        reindex_object(obj)


def get_sample_analyses(sample):
    """兼容获取样品下所有测试对象。"""
    analyses = sample.getAnalyses(full_objects=True)
    analyses = list(analyses or [])
    return [
        analysis for analysis in analyses
        if getattr(analysis, "portal_type", "") in ANALYSIS_PORTAL_TYPES
    ]


def get_parent_sample(analysis):
    """兼容不同 Analysis 对象的父样品获取方式。"""
    if hasattr(analysis, "getRequest"):
        return analysis.getRequest()
    return None


def get_analysis_worksheet(analysis):
    """兼容获取测试所在工作表。"""
    if hasattr(analysis, "getWorksheet"):
        return analysis.getWorksheet()
    return None


def unique_objects(objects):
    """按 UID 去重，保持原顺序。"""
    values = OrderedDict()
    for obj in objects or []:
        uid = api.get_uid(obj)
        values[uid] = obj
    return values.values()


def validate_reason(reason):
    """激活原因必填，避免无法审计。"""
    if not api.is_string(reason):
        raise ValueError("Reactivate reason must be a string")
    if not reason.strip():
        raise ValueError("Reactivate reason is required")
    return reason
