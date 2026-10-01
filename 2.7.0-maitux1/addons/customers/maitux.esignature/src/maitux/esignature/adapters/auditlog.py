# -*- coding: utf-8 -*-
"""AuditLog and signature record integration for successful transitions."""

import json
import transaction

from bika.lims import api
from bika.lims import logger
from bika.lims.api.snapshot import get_storage as get_snapshot_storage
from bika.lims.api.snapshot import supports_snapshots
from bika.lims.api.snapshot import take_snapshot
from bika.lims.api.user import get_user_id
from bika.lims.subscribers.auditlog import reindex_object

from maitux.esignature.services.context import (
    build_signature_summary,
    clear_verified_signature_context,
    consume_verified_signature_context,
    get_verified_signature_context,
    is_verified_signature_context_valid,
)
from maitux.esignature.services.policy import SignaturePolicyResolver
from maitux.esignature.siteinstall import is_installed_in_current_site
from maitux.esignature.storage.store import SignatureRecordStore


def _build_esignature_metadata(verified_context, action):
    return {
        "enabled": True,
        "signature_id": verified_context.get("signature_id"),
        "initiator_user_id": verified_context.get("initiator_user_id"),
        "user_id": verified_context.get("user_id"),
        "primary_signer_user_id": verified_context.get("primary_signer_user_id"),
        "signer_userids": verified_context.get("signer_userids") or [],
        "transition_id": verified_context.get("transition_id"),
        "signature_type": verified_context.get("signature_type"),
        "require_countersign": verified_context.get("require_countersign", False),
        "countersign_completed": verified_context.get("countersign_completed", False),
        "countersigner_user_id": verified_context.get("countersigner_user_id"),
        "meaning": verified_context.get("meaning"),
        "reason": verified_context.get("reason"),
        "auth_backend_id": verified_context.get("auth_backend_id"),
        "countersign_auth_backend_id": verified_context.get("countersign_auth_backend_id"),
        "description": build_signature_summary(verified_context),
        "status": verified_context.get("status") or "applied",
        "audit_action": "electronic_signature_{}".format(
            verified_context.get("transition_id") or action
        ),
    }


def _find_transition_snapshot_index(storage, transition_id):
    """Index of the audit entry this transition wrote, or None.

    Located by identity rather than by position.  Both this subscriber and
    senaite's ObjectTransitionedEventHandler listen to IActionSucceededEvent,
    and ours runs first -- so at this point the entry we are looking for may
    not exist yet, and storage[-1] is still the *previous* transition.  Writing
    there put the signature on an unrelated audit entry.

    Scans backwards so the newest matching entry wins when an object went
    through the same transition more than once.
    """
    for index in range(len(storage) - 1, -1, -1):
        try:
            metadata = json.loads(storage[index]).get("__metadata__", {})
        except ValueError:
            continue
        if metadata.get("action") == transition_id:
            return index
    return None


def _enrich_transition_snapshot(obj, verified_context, action):
    """Attach the structured signature data to the transition's own entry.

    The human-readable summary already travels through DCWorkflow into the
    entry's `comments` (see browser/workflow.py: do_action_with_comment), so if
    this does not find its target the signature is still recorded -- only the
    machine-readable dict for the audit UI is missing.
    """
    storage = get_snapshot_storage(obj)
    if not storage:
        return False

    transition_id = verified_context.get("transition_id") or action
    index = _find_transition_snapshot_index(storage, transition_id)
    if index is None:
        return False

    latest = json.loads(storage[index])
    metadata = latest.get("__metadata__", {})
    metadata["comments"] = build_signature_summary(verified_context)
    metadata["esignature"] = _build_esignature_metadata(verified_context, action)
    latest["__metadata__"] = metadata
    storage[index] = json.dumps(latest)
    return True


def _build_signature_record(obj, verified_context, action):
    record = {
        "object_uid": api.get_uid(obj),
        "object_path": verified_context.get("object_path") or "/".join(obj.getPhysicalPath()),
        "portal_type": getattr(obj, "portal_type", None),
        "transition_id": verified_context.get("transition_id") or action,
        "signature_type": verified_context.get("signature_type") or "verification",
        "meaning": verified_context.get("meaning"),
        "reason": verified_context.get("reason"),
        "initiator_userid": verified_context.get("initiator_user_id") or get_user_id(),
        "signer_userid": verified_context.get("user_id") or get_user_id(),
        "primary_signer_userid": verified_context.get("primary_signer_user_id")
        or verified_context.get("user_id")
        or get_user_id(),
        "require_countersign": bool(verified_context.get("require_countersign")),
        "countersigner_userid": verified_context.get("countersigner_user_id"),
        "auth_backend_id": verified_context.get("auth_backend_id"),
        "countersign_auth_backend_id": verified_context.get("countersign_auth_backend_id"),
        "status": verified_context.get("status") or "applied",
        "auditlog_summary": build_signature_summary(verified_context),
    }
    # 允许调用方预先生成 signature_id。业务模块（如库存领用申请）需要先把
    # 签名 ID 写进自己的业务流水，再落签名记录，否则两边 ID 对不上。
    signature_id = verified_context.get("signature_id")
    if signature_id:
        record["signature_id"] = signature_id
    return record


def _append_signature_audit_snapshot(obj, verified_context, action, audit_action=None):
    """为电子签名单独追加一条审计快照，便于在 Audit Log 中直接查看。"""
    signer_userid = verified_context.get("user_id") or get_user_id()
    # 这里单独追加一条 snapshot，而不是只改最后一条记录，
    # 目的是让审计轨迹中出现一条独立的电子签名日志。
    snapshot = take_snapshot(
        obj,
        store=False,
        action=audit_action or "electronic_signature_{}".format(
            verified_context.get("transition_id") or action
        ),
        actor=signer_userid,
        comments=build_signature_summary(verified_context),
        esignature=_build_esignature_metadata(verified_context, action),
    )
    snapshot.update({
        "Electronic Signature Initiator": (
            verified_context.get("initiator_user_id") or signer_userid
        ),
        "Electronic Signature Signer": signer_userid,
        "Electronic Signature Countersign Required": (
            "Yes" if verified_context.get("require_countersign") else "No"
        ),
        "Electronic Signature Countersigner": (
            verified_context.get("countersigner_user_id") or ""
        ),
        "Electronic Signature Status": verified_context.get("status") or "applied",
        "Electronic Signature Transition": verified_context.get("transition_id") or action,
        "Electronic Signature Type": verified_context.get("signature_type") or "verification",
        "Electronic Signature Meaning": verified_context.get("meaning") or "",
        "Electronic Signature Reason": verified_context.get("reason") or "",
        "Electronic Signature Description": build_signature_summary(verified_context),
    })
    get_snapshot_storage(obj).append(json.dumps(snapshot))


def _schedule_snapshot_enrichment(obj, verified_context, action):
    """Enrich the transition's audit entry, but not until commit time.

    We are inside an IActionSucceededEvent handler and we run *before*
    senaite's ObjectTransitionedEventHandler, so the entry we want to enrich
    does not exist yet.  Deferring to a before-commit hook lets it be written
    first; by then `_find_transition_snapshot_index` can locate it.

    Deferring is only safe because the lookup goes by identity (the entry whose
    action is this transition) rather than by position.  A hook that still
    wrote to storage[-1] would merely be betting that nothing else appends in
    the meantime.

    The hook must never raise: an exception from a before-commit hook aborts
    the whole transaction, which would undo a transition that legitimately
    succeeded.  A failure here costs the structured dict for the audit UI, not
    the signature itself -- the readable summary already reached the entry
    through DCWorkflow.
    """
    def hook():
        try:
            if not _enrich_transition_snapshot(obj, verified_context, action):
                logger.warning(
                    "esignature: no audit entry found for transition '{}' on "
                    "{}; signature summary is still in the workflow comment"
                    .format(verified_context.get("transition_id") or action,
                            api.get_id(obj)))
        except Exception as error:  # noqa: BLE001 - must not abort the txn
            logger.error(
                "esignature: could not enrich the audit entry of {}: {}"
                .format(api.get_id(obj), error))

    transaction.get().addBeforeCommitHook(hook)


def record_pending_countersign(context, verified_context, action):
    """记录第一人已签、等待第二人复核的状态和审计轨迹。"""
    portal = api.get_portal()
    store = SignatureRecordStore(portal)
    data = dict(verified_context)
    data["status"] = "pending_countersign"
    record = _build_signature_record(context, data, action)
    store.save(record)
    # 仅保留业务签名记录，不再额外追加独立审计快照，避免审计追踪重复显示。
    reindex_object(context)


def record_signature(context, verified_context, action, append_audit_snapshot=True):
    """公共入口：记录一次已完成校验的电子签名。

    与 ``on_action_succeeded`` 的区别：后者只服务于"工作流动作已成功"这条链路
    （由 ``IActionSucceededEvent`` 触发）。库存领用这类**非工作流动作**也需要
    同等的签名留痕，因此把"落库 + 独立审计快照"的逻辑抽成公共函数复用。

    :param context: 被签名的对象（签名记录与审计快照都挂在这个对象上）
    :param verified_context: ``services.context.build_verified_signature_context``
        的返回值（或等价字典）
    :param action: 逻辑动作名，会写进记录的 ``transition_id`` 与审计动作名
    :param append_audit_snapshot: 是否额外追加一条独立电子签名审计快照
    :returns: 已落库的签名记录（``PersistentMapping``）
    """
    portal = api.get_portal()
    store = SignatureRecordStore(portal)
    data = dict(verified_context or {})
    record = _build_signature_record(context, data, action)
    stored = store.save(record)
    # 审计快照底层直接调用 IAnnotations(obj)，对不支持快照的对象会抛异常。
    # 这里必须先判定，否则业务侧（如库存领用）会整单回滚。
    if append_audit_snapshot and supports_snapshots(context):
        # 审计快照辅助函数读取的是"已验证上下文"的键名
        # （user_id / initiator_user_id / countersigner_user_id ...），
        # 而落库记录用的是另一套键名（signer_userid / initiator_userid ...）。
        # 这里必须传原始上下文，否则快照里的签名人字段会全部为空。
        _append_signature_audit_snapshot(context, data, action)
    reindex_object(context)
    return stored


def on_action_succeeded(context, event):
    """Persist the signature record and enrich the latest audit snapshot."""
    # 本订阅器是 for="*" 的进程级注册，所有站点都会调到，而它会往站点写签名
    # 记录和审计快照。未装本 addon 的站点直接不参与。详见 siteinstall。
    if not is_installed_in_current_site():
        return

    action = getattr(event, "action", None)
    if not action:
        return

    user_id = get_user_id()
    policy = SignaturePolicyResolver().resolve(context, action, user_id=user_id)
    if not policy.get("signature_required"):
        return

    verified_context = get_verified_signature_context()
    if not verified_context:
        return

    if not is_verified_signature_context_valid(context, action, user_id):
        clear_verified_signature_context()
        return

    portal = api.get_portal()
    store = SignatureRecordStore(portal)
    record = _build_signature_record(context, verified_context, action)
    stored = store.save(record)

    # 正式记录始终保留；若现场仍希望保留 metadata 摘要，则补到该 transition
    # 自己的那条审计项上。
    #
    # 注意传的是 verified_context 而不是 stored：SignatureRecord 用的是
    # initiator_userid / signer_userid（无下划线），而 build_signature_summary
    # 读的是 initiator_user_id / user_id，键名对不上会全部回落成 "unknown"。
    if policy.get("auditlog_summary_enabled", True):
        _schedule_snapshot_enrichment(context, verified_context, action)
    reindex_object(context)

    # 一次签名可覆盖多个对象：此处只销掉当前对象，全部完成后上下文才作废。
    # 过去这里无条件清空，导致批次里第 2 个对象的 guard 必然失败。
    consume_verified_signature_context(context)
