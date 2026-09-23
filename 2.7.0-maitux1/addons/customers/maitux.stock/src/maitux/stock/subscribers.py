# -*- coding: utf-8 -*-
from decimal import Decimal

import transaction
from bika.lims import api
from senaite.core.api import dtime
from senaite.core.interfaces import INumberGenerator
from senaite.core import logger
from Products.CMFCore.WorkflowCore import WorkflowException
from zope.component import getUtility

from maitux.stock.interfaces import IStockUsageRequest
from maitux.stock.expiryreminder import default_expiry_from_stock
from maitux.stock.stockbatchexpiry import REVIEW_STATE_ACTIVE
from maitux.stock.stockbatchexpiry import expire_batch
from maitux.stock.stockbatchexpiry import is_due_for_expiry
from maitux.stock.stockbatchexpiry import set_status_value
from maitux.stock.usageapproval import BATCH_AUDIT_REJECTED
from maitux.stock.usageapproval import append_batch_audit_snapshot
from maitux.stock.usageapproval import deduct_request_lines
from maitux.stock.usageapproval import get_request_applicant


def _first_uid(value):
    if not value:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    value = api.safe_unicode(value)
    parts = value.splitlines()
    return parts[0] if parts else ""


def _get_next_batch_index(stock_number):
    """使用 Core 的带锁持久化计数器生成批次序号，保证并发安全"""
    key = "stockbatch-{}".format(stock_number)
    generator = getUtility(INumberGenerator)
    next_index = generator.get_number(key)
    if next_index in (None, ""):
        raise ValueError("Failed to generate batch index for '{}'".format(stock_number))
    return next_index


def stockbatch_added(stockbatch, event):
    if getattr(stockbatch, "portal_type", None) != "StockBatch":
        return

    now = dtime.now()
    user = api.get_current_user()
    user_id = user.getId() if user else ""

    if not getattr(stockbatch, "created_by", None):
        stockbatch.created_by = user_id
    if not getattr(stockbatch, "created_date", None):
        stockbatch.created_date = now
    set_status_value(stockbatch, REVIEW_STATE_ACTIVE)

    stock_uid = _first_uid(getattr(stockbatch, "stock", None))
    stock = api.get_object_by_uid(stock_uid, default=None) if stock_uid else None
    stock_number = getattr(stock, "number", None) if stock else None
    stock_number = api.safe_unicode(stock_number) if stock_number else u""

    if stock_number and not getattr(stockbatch, "batch_id", None):
        # 批次编号是核心业务字段，生成失败时直接抛错，避免落库空编号。
        idx = _get_next_batch_index(stock_number)
        stockbatch.batch_id = u"{}/{}".format(stock_number, idx)
        stockbatch.title = stockbatch.batch_id
        logger.info("Generated StockBatch batch_id '%s'", stockbatch.batch_id)

    if not getattr(stockbatch, "usage_records", None):
        qty = getattr(stockbatch, "current_amount", None)
        try:
            qty = Decimal(qty) if qty is not None else Decimal("0.00")
        except Exception:
            qty = Decimal("0.00")
        # Auto-populate from selected Stock's quantity if not provided
        try:
            if qty == Decimal("0.00"):
                stock_uid = _first_uid(getattr(stockbatch, "stock", None))
                stock = api.get_object_by_uid(stock_uid, default=None) if stock_uid else None
                if stock:
                    sval = getattr(stock, "quantity", None)
                    if sval is not None:
                        sval = Decimal(sval)
                        stockbatch.current_amount = sval
                        qty = sval
        except Exception:
            pass
        # Set target quantity at creation
        try:
            if not getattr(stockbatch, "target_quantity", None):
                stockbatch.target_quantity = qty
        except Exception:
            pass
        stockbatch.usage_records = [{
            "operation_type": u"create",
            "operator": api.safe_unicode(user_id),
            "operation_date": now,
            "quantity": qty,
            "remarks": u"",
            "from_batch": u"",
        }]

    # 到期日默认值：物料（Stock）上的到期日是"批次默认到期日 / 参考有效期"，
    # 新建批次时预填；批次自己填了就以批次的为准（权威数据永远在批次上）。
    try:
        if default_expiry_from_stock(stockbatch, stock=stock):
            logger.info("Applied default expiry date to StockBatch '%s'",
                        api.get_uid(stockbatch))
    except Exception:
        logger.exception(
            "Failed to apply default expiry date to StockBatch '%s'",
            api.get_uid(stockbatch),
        )

    try:
        stockbatch.reindexObject()
    except Exception:
        pass

    # 新建时如果有效期已经过去，立即补齐过期状态，避免落库后仍显示为可用。
    if is_due_for_expiry(stockbatch, now=now):
        try:
            expire_batch(
                stockbatch,
                now=now,
                operator=api.safe_unicode(user_id),
                remarks=u"Auto expired on create",
                reindex=True,
            )
        except Exception:
            logger.exception(
                "Failed to auto-expire StockBatch '%s' on create",
                api.get_uid(stockbatch),
            )


# ===========================================================================
# 领用申请单（StockUsageRequest）
# ===========================================================================
USAGE_REQUEST_NUMBER_KEY = "stockusage-request"
USAGE_REQUEST_ID_FORMAT = u"SUR-{:05d}"

# 迁移 -> 申请单 status 字段的镜像值（字段只用于展示，工作流才是真相）
TRANSITION_STATUS = {
    u"submit": u"submitted",
    u"approve": u"approved",
    u"reject": u"rejected",
    u"retract": u"cancelled",
    u"cancel": u"cancelled",
}


def _next_usage_request_number():
    """用 Core 的带锁持久化计数器生成申请单序号（并发安全）。"""
    generator = getUtility(INumberGenerator)
    number = generator.get_number(USAGE_REQUEST_NUMBER_KEY)
    if number in (None, ""):
        raise ValueError("Failed to generate usage request number")
    return int(number)


def _get_request_signature_context(transition_id):
    """读取 esignature 写入的"已验证签名上下文"（没签名则返回空 dict）。"""
    try:
        from maitux.esignature.services.context import (
            get_verified_signature_context,
        )
    except ImportError:
        return {}
    data = get_verified_signature_context() or {}
    if not data:
        return {}
    if api.safe_unicode(data.get("transition_id") or "") != transition_id:
        return {}
    return data


def _append_signature_log(usage_request, step, signer, context_data, now):
    """把一次电子签名的要素追加到申请单的签名留痕。

    中文注释：双人复核时签名页会同时校验两个账号，光记一个 signer 是不够的
    —— 审计追踪必须能看到"谁签的、谁复核的"。所以这里把复核人、是否要求复核、
    以及真正提交这次操作的人（登录用户）一并落库。
    """
    log = getattr(usage_request, "signature_log", None) or []
    if not isinstance(log, (list, tuple)):
        log = []
    log = [dict(row) for row in log]
    log.append({
        "step": api.safe_unicode(step),
        "signer": api.safe_unicode(signer or u""),
        "countersigner": api.safe_unicode(
            context_data.get("countersigner_user_id") or u""),
        "require_countersign": bool(context_data.get("require_countersign")),
        "executed_by": api.safe_unicode(
            context_data.get("execution_user_id") or u""),
        "meaning": api.safe_unicode(context_data.get("meaning") or u""),
        "reason": api.safe_unicode(context_data.get("reason") or u""),
        "signed_at": now,
    })
    usage_request.signature_log = log
    return context_data.get("reason") or u""


def stockusagerequest_added(usage_request, event):
    """新建申请单时补编号、申请人快照与初始状态。"""
    if getattr(usage_request, "portal_type", None) != "StockUsageRequest":
        return

    user = api.get_current_user()
    user_id = user.getId() if user else ""
    fullname = api.get_user_fullname(user) if user else u""

    if not getattr(usage_request, "request_id", None):
        usage_request.request_id = USAGE_REQUEST_ID_FORMAT.format(
            _next_usage_request_number())
        usage_request.title = usage_request.request_id
    if not getattr(usage_request, "applicant", None):
        usage_request.applicant = api.safe_unicode(user_id)
    if not getattr(usage_request, "applicant_fullname", None):
        usage_request.applicant_fullname = api.safe_unicode(
            fullname or user_id)
    if not getattr(usage_request, "status", None):
        usage_request.status = u"draft"

    try:
        usage_request.reindexObject()
    except Exception:
        pass
    logger.info("Created StockUsageRequest '%s' by '%s'",
                getattr(usage_request, "request_id", ""), user_id)


def _append_reject_audit(usage_request, reviewer, reason):
    """驳回时也在受影响批次上留一条审计。

    批次数量没有变化，但"这次领用申请被驳回了"是受控决定，审计追踪里应当看得到
    （否则批次的审计轨迹只有成功的那几次，看不到被拒的记录）。
    """
    request_id = api.safe_unicode(
        getattr(usage_request, "request_id", "") or api.get_title(usage_request))
    applicant = get_request_applicant(usage_request)
    reviewer = api.safe_unicode(reviewer or u"")
    reason = api.safe_unicode(reason or u"")

    for line in getattr(usage_request, "lines", None) or []:
        uid = api.safe_unicode(line.get("batch_uid", "") or "").strip()
        if not uid:
            continue
        batch = api.get_object_by_uid(uid, default=None)
        if batch is None:
            continue
        append_batch_audit_snapshot(
            batch,
            action=BATCH_AUDIT_REJECTED,
            actor=reviewer,
            comments=u"领用申请 {} 被驳回：申请人 {}，审核人 {}；原因：{}".format(
                request_id, applicant, reviewer, reason),
            extra={
                u"Usage Request": request_id,
                u"Applicant": applicant,
                u"Reviewer": reviewer,
                u"Rejected Quantity": u"{}".format(
                    line.get("requested_quantity")),
                u"Rejection Reason": reason,
            },
        )


def stockusagerequest_before_transition(usage_request, event):
    """迁移执行前：记录签名留痕；审核通过时执行扣减。

    为什么扣减放在这里而不是 IActionSucceededEvent：
    后者在"迁移已经成功"之后才触发，在里面抛异常不会回滚工作流状态，
    会留下"状态已 approved 但库存没扣"的脏数据。放在 before 阶段，
    任何失败都会阻止迁移。
    """
    if not IStockUsageRequest.providedBy(usage_request):
        return

    transition = getattr(event, "transition", None)
    transition_id = api.safe_unicode(
        getattr(transition, "id", None) or getattr(event, "action", None) or "")
    if not transition_id:
        return

    now = dtime.now()
    user = api.get_current_user()
    user_id = user.getId() if user else u""
    fullname = api.get_user_fullname(user) if user else u""

    # --- 签名留痕（只有真的走过电子签名页的迁移才有上下文） ---
    signature_context = _get_request_signature_context(transition_id)
    countersigner_user_id = u""
    if signature_context:
        signer = (signature_context.get("initiator_user_id")
                  or signature_context.get("primary_signer_user_id")
                  or user_id)
        countersigner_user_id = api.safe_unicode(
            signature_context.get("countersigner_user_id") or u"")
        reason = _append_signature_log(
            usage_request, transition_id, signer, signature_context, now)
    else:
        reason = u""
        signer = user_id

    if transition_id == u"submit":
        usage_request.request_date = now

    elif transition_id in (u"approve", u"reject"):
        usage_request.approver = api.safe_unicode(signer)
        usage_request.approver_fullname = api.safe_unicode(fullname or signer)
        usage_request.approve_date = now
        if transition_id == u"reject":
            # 复用签名页的 Reason 作为驳回原因
            usage_request.approve_comment = api.safe_unicode(reason)
            _append_reject_audit(usage_request, signer, reason)

    if transition_id == u"approve":
        # 原子扣减：任一行失败则整单回滚，并阻止迁移
        savepoint = transaction.savepoint()
        try:
            deducted = deduct_request_lines(
                usage_request,
                approver_user_id=signer,
                countersigner_user_id=countersigner_user_id,
                now=now)
        except Exception as exc:
            savepoint.rollback()
            logger.warning(
                "StockUsageRequest '%s' approve blocked: %s",
                getattr(usage_request, "request_id", ""), exc)
            raise WorkflowException(
                u"审核未执行：库存无法扣减（{}）。请驳回该申请，"
                u"或让申请人重新提交。".format(api.safe_unicode(exc)))
        logger.info("StockUsageRequest '%s' deducted %s line(s)",
                    getattr(usage_request, "request_id", ""), deducted)

    # status 字段只是 review_state 的展示镜像
    status = TRANSITION_STATUS.get(transition_id)
    if status:
        usage_request.status = status

    try:
        usage_request.reindexObject()
    except Exception:
        pass
