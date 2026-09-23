# -*- coding: utf-8 -*-
"""领用申请 / 审批的领域逻辑。

这里的函数刻意保持"少依赖 Zope 运行时"，便于用桩化单测覆盖；
与 Zope 强耦合的部分（guard 适配器、浏览器视图）分别在 guards.py 和 browser/ 下。
"""
import json
from decimal import Decimal

from DateTime import DateTime
from bika.lims import api
from senaite.core.api import dtime

from maitux.stock.config import CONSUME_COUNTERSIGN_ROLES
from maitux.stock.stockbatchexpiry import get_operation_block_message
from maitux.stock.stockbatchexpiry import is_due_for_expiry


def to_decimal(value, default=Decimal("0.00")):
    """安全转 Decimal。"""
    try:
        return Decimal(value) if value is not None else default
    except Exception:
        return default


def first_uid(value):
    """UIDReference 字段可能是 列表 / 多行文本，统一取第一个 UID。"""
    if not value:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    value = api.safe_unicode(value)
    parts = value.splitlines()
    return parts[0].strip() if parts else ""


def get_batch_stock(batch):
    """批次的库存主数据（Stock）；无关联返回 None。"""
    stock_uid = first_uid(getattr(batch, "stock", "") or "")
    if not stock_uid:
        return None
    return api.get_object_by_uid(stock_uid, default=None)


def get_batch_unit(batch):
    unit_uid = first_uid(getattr(batch, "unit", "") or "")
    if not unit_uid:
        return None
    return api.get_object_by_uid(unit_uid, default=None)


def stock_requires_signature(stock):
    """该库存是否勾选了"领用需双人电子签名"。"""
    if stock is None:
        return False
    return bool(getattr(stock, "consume_requires_countersign", False))


def batch_requires_signature(batch):
    return stock_requires_signature(get_batch_stock(batch))


def any_batch_requires_signature(batches):
    """所选批次里只要有一个属于"需签名"的库存，就必须走申请流程。"""
    for batch in batches or []:
        if batch_requires_signature(batch):
            return True
    return False


# ---------------------------------------------------------------------------
# 审批人
# ---------------------------------------------------------------------------
def get_approval_roles():
    """允许审批领用申请的角色白名单（空 = 不限制角色）。"""
    return list(CONSUME_COUNTERSIGN_ROLES)


def get_user_roles(user_id, context=None):
    """取用户在指定上下文中的角色集合。"""
    user = api.get_user(user_id)
    if user is None:
        return set()
    if context is None:
        context = api.get_portal()
    try:
        return set(user.getRolesInContext(context) or [])
    except Exception:
        return set()


def has_approval_role(user_id, context=None):
    """用户是否具备审批角色的任一。"""
    allowed = set(get_approval_roles())
    if not allowed:
        return True
    return bool(get_user_roles(user_id, context=context) & allowed)


def get_request_applicant(request):
    """申请单的申请人 user id。"""
    applicant = api.safe_unicode(getattr(request, "applicant", "") or "").strip()
    if applicant:
        return applicant
    try:
        return api.safe_unicode(request.Creator() or "").strip()
    except Exception:
        return u""


def is_applicant(request, user_id):
    """是否为同一人（把 None/空值都视为"不是"）。"""
    applicant = get_request_applicant(request)
    user_id = api.safe_unicode(user_id or "").strip()
    if not applicant or not user_id:
        return False
    return applicant == user_id


def check_approver(request, user_id):
    """审核资格校验，返回错误提示（通过则返回空串）。

    需求硬约束：**审核人不能是申请人本人**；此外还须具备审批角色。
    """
    user_id = api.safe_unicode(user_id or "").strip()
    if not user_id:
        return u"无法确定当前用户。"
    if is_applicant(request, user_id):
        return u"审核人不能是申请人本人。"
    if not has_approval_role(user_id, context=request):
        return u"当前用户不具备审批角色，需要其中之一：{}。".format(
            u"、".join(sorted(get_approval_roles())))
    return u""


# ---------------------------------------------------------------------------
# 明细
# ---------------------------------------------------------------------------
def build_line(batch, quantity, remarks=u""):
    """由批次 + 数量生成一条申请明细（含主数据快照）。"""
    unit = get_batch_unit(batch)
    stock = get_batch_stock(batch)
    return {
        "batch_uid": api.safe_unicode(api.get_uid(batch)),
        "batch_id": api.safe_unicode(getattr(batch, "batch_id", "") or ""),
        "stock_title": api.safe_unicode(api.get_title(stock) if stock else u""),
        "unit_title": api.safe_unicode(api.get_title(unit) if unit else u""),
        "requested_quantity": to_decimal(quantity),
        "remarks": api.safe_unicode(remarks or u""),
    }


def group_requested_quantity(lines):
    """把明细按批次合并数量（同一批次出现多行时要按合计校验）。"""
    totals = {}
    for line in lines or []:
        uid = api.safe_unicode(line.get("batch_uid", "") or "").strip()
        if not uid:
            continue
        totals[uid] = totals.get(uid, Decimal("0.00")) + to_decimal(
            line.get("requested_quantity"))
    return totals


def validate_lines(lines, now=None):
    """校验明细是否仍然可扣减，返回 [(label, error)]（空列表 = 通过）。

    纯校验、无副作用：过期批次只报错，不做 expire（expire 由调用方决定时机）。
    """
    if now is None:
        now = dtime.now()

    errors = []
    resolved = {}
    for line in lines or []:
        uid = api.safe_unicode(line.get("batch_uid", "") or "").strip()
        label = api.safe_unicode(line.get("batch_id") or uid) or u"(unknown)"
        quantity = to_decimal(line.get("requested_quantity"))

        if not uid:
            errors.append((label, u"Missing batch reference."))
            continue
        batch = api.get_object_by_uid(uid, default=None)
        if batch is None:
            errors.append((label, u"Batch not found."))
            continue
        if quantity <= 0:
            errors.append((label, u"Quantity must be greater than 0."))
            continue
        if is_due_for_expiry(batch, now=now):
            errors.append((label, u"Batch is expired."))
            continue
        block_message = get_operation_block_message(batch, now=now)
        if block_message:
            errors.append((label, block_message))
            continue
        resolved[uid] = batch

    # 同一批次多行 -> 按合计校验余量
    for uid, total in group_requested_quantity(lines).items():
        batch = resolved.get(uid)
        if batch is None:
            continue
        current = to_decimal(getattr(batch, "current_amount", None))
        if total > current:
            errors.append((
                api.safe_unicode(getattr(batch, "batch_id", "") or uid),
                u"Quantity exceeds the current amount (requested {}, available {}).".format(
                    total, current),
            ))
    return errors


# ---------------------------------------------------------------------------
# 待审核申请查询（审核人的入口在"批次"这一侧）
# ---------------------------------------------------------------------------
PENDING_REVIEW_STATE = u"submitted"

# 批次审计快照的 action 名（审计追踪页面按它显示中文标签，见 stockbatchview.py）
BATCH_AUDIT_APPROVED = u"stock_usage_approved"
BATCH_AUDIT_REJECTED = u"stock_usage_rejected"


def find_pending_requests():
    """返回 {batch_uid: [StockUsageRequest, ...]}。

    口径：只取处于"待审核"的申请单，把它们引用的批次 UID 展开成映射，
    这样批次列表/批次页可以直接回答"这个批次有没有等待审核的领用申请"。

    为什么不用 catalog 索引：`lines` 是对象内的 DataGrid，本身没有索引；
    而待审核的申请单数量天然很少（就是这个审批队列），一次查询 + 少量
    getObject 足够。如果将来待审核量级变大，再加一个 KeywordIndex。
    """
    catalog = api.get_tool("portal_catalog")
    if catalog is None:
        return {}

    try:
        brains = catalog(portal_type="StockUsageRequest",
                         review_state=PENDING_REVIEW_STATE)
    except Exception:
        return {}

    mapping = {}
    for brain in brains:
        try:
            request = api.get_object(brain)
        except Exception:
            continue
        if request is None:
            continue
        for line in getattr(request, "lines", None) or []:
            uid = api.safe_unicode(line.get("batch_uid", "") or "").strip()
            if uid:
                mapping.setdefault(uid, []).append(request)
    return mapping


def find_pending_requests_for_batch(batch):
    """该批次上等待审核的领用申请（按创建时间升序，先到先审）。"""
    if batch is None:
        return []
    uid = api.safe_unicode(api.get_uid(batch) or "").strip()
    if not uid:
        return []
    requests = find_pending_requests().get(uid) or []
    return sorted(requests, key=lambda item: api.get_creation_date(item) or 0)


def get_reviewable_request(batch, user_id):
    """返回当前用户**有权审核**的那条待审核申请（没有则 None）。

    这是批次列表"审核领用"按钮的显示条件：既要有待审核申请，
    又要满足"非申请人 + 具备审批角色"。
    """
    for request in find_pending_requests_for_batch(batch):
        if not check_approver(request, user_id):
            return request
    return None


def append_batch_audit_snapshot(batch, action, actor=u"", comments=u"", extra=None):
    """在批次上追加一条审计快照，并同步审计目录。

    为什么必须显式做（本仓库的两个既有约束）：
      1. StockBatch 是 Dexterity 对象，**直接改字段 + reindexObject() 不会触发
         IObjectModifiedEvent**，所以不会自动产生审计快照；
      2. StockBatch 的 ``_catalogs`` 只有 portal_catalog，审计目录
         (``senaite_catalog_auditlog``) 不会被更新，审计列表里查不到它。

    这里把两件事都补上：写快照 + reindex 审计目录。快照的 actor/roles/
    remote_address 由 take_snapshot 自动从当前请求取，正是审计需要的。

    :returns: True 表示已写入（对象不支持快照时返回 False）
    """
    if batch is None:
        return False
    try:
        from bika.lims.api.snapshot import get_storage
        from bika.lims.api.snapshot import supports_snapshots
        from bika.lims.api.snapshot import take_snapshot
        from bika.lims.subscribers.auditlog import reindex_object
    except ImportError:
        return False
    if not supports_snapshots(batch):
        return False

    # 中文注释：metadata 的 modified 默认取对象修改时间，不更新的话审计条目
    # 会显示成上一次编辑的时间。
    stamp = DateTime()
    try:
        batch.setModificationDate(stamp)
    except Exception:
        pass

    snapshot_kwargs = {
        "action": action,
        "comments": api.safe_unicode(comments or u""),
        "modified": stamp.ISO(),
    }
    # 中文注释：只有真给了 actor 才传 —— take_snapshot 的 metadata.update(kw)
    # 会用传入值覆盖自动识别的当前用户，传 None 会把 actor 抹掉。
    if actor:
        snapshot_kwargs["actor"] = api.safe_unicode(actor)

    snapshot = take_snapshot(batch, store=False, **snapshot_kwargs)
    if extra:
        snapshot.update(extra)

    try:
        get_storage(batch).append(json.dumps(snapshot))
    except Exception:
        return False
    try:
        reindex_object(batch)
    except Exception:
        pass
    return True


def append_usage_record(batch, now=None, operator=u"", qty=None, remarks=u"",
                        second_operator=u"", request_id=u""):
    """在批次流水末尾追加一条 consume 记录，返回新的流水列表。

    显式复制每条既有流水（dict(record)）：
      * DataGrid 里存的可能是 PersistentMapping，原地改 key 不一定落库；
      * 复制后整体赋值，语义最接近原有实现，风险最小。
    """
    records = getattr(batch, "usage_records", None) or []
    if not isinstance(records, (list, tuple)):
        records = []
    records = [dict(record) for record in records]
    records.append({
        "operation_type": u"consume",
        "operator": api.safe_unicode(operator),
        "operation_date": now,
        "quantity": qty,
        "remarks": remarks,
        "from_batch": u"",
        "second_operator": api.safe_unicode(second_operator),
        "request_id": api.safe_unicode(request_id),
    })
    return records


def deduct_request_lines(request, approver_user_id=u"",
                         countersigner_user_id=u"", now=None):
    """审核通过时执行扣减：逐行扣库存并写流水。

    :param approver_user_id: 审核人（= 第一操作员 / 实际执行审核的人）
    :param countersigner_user_id: 复核人（双人复核时的第二操作员，可空）
    :returns: 实际扣减的行数
    :raises ValueError: 任何一行校验不通过（调用方负责阻止迁移）
    """
    if now is None:
        now = dtime.now()

    lines = list(getattr(request, "lines", None) or [])
    errors = validate_lines(lines, now=now)
    if errors:
        raise ValueError(u"; ".join(
            u"{}: {}".format(label, message) for label, message in errors))

    request_id = api.safe_unicode(
        getattr(request, "request_id", "") or api.get_title(request) or u"")
    applicant = get_request_applicant(request)
    approver_user_id = api.safe_unicode(approver_user_id)
    countersigner_user_id = api.safe_unicode(countersigner_user_id)
    # 审计文案里要把"双人"体现出来：只写审核人会让人以为是一次单人审批。
    if countersigner_user_id:
        reviewer_text = u"审核人 {}（双人复核：{}）".format(
            approver_user_id, countersigner_user_id)
    else:
        reviewer_text = u"审核人 {}".format(approver_user_id)
    # 同一批次多行时按累计扣减
    applied = {}
    deducted = 0
    for line in lines:
        uid = api.safe_unicode(line.get("batch_uid", "") or "").strip()
        batch = api.get_object_by_uid(uid, default=None)
        if batch is None:
            raise ValueError(u"Batch not found: {}".format(uid))
        quantity = to_decimal(line.get("requested_quantity"))

        current = to_decimal(getattr(batch, "current_amount", None))
        new_amount = current - quantity
        if new_amount < 0:
            # 理论上已被 validate_lines 拦住，这里兜底以免扣成负数
            raise ValueError(u"Quantity exceeds the current amount for {}.".format(
                api.safe_unicode(getattr(batch, "batch_id", "") or uid)))

        batch.current_amount = new_amount
        batch.usage_records = append_usage_record(
            batch,
            now=now,
            operator=applicant,          # 领用人 = 申请人
            qty=quantity,
            remarks=api.safe_unicode(line.get("remarks") or u""),
            second_operator=approver_user_id,   # 审核人
            request_id=request_id,
        )
        # 中文注释：必须显式写审计快照 —— 见 append_batch_audit_snapshot 的说明。
        # 放在扣减与流水之后，所以快照里记的是**扣减后**的数量。
        audit_extra = {
            u"Usage Request": request_id,
            u"Applicant": applicant,
            u"Reviewer": approver_user_id,
            u"Consumed Quantity": u"{}".format(quantity),
            u"Amount Before": u"{}".format(current),
            u"Amount After": u"{}".format(new_amount),
        }
        if countersigner_user_id:
            audit_extra[u"Countersigner"] = countersigner_user_id
        append_batch_audit_snapshot(
            batch,
            action=BATCH_AUDIT_APPROVED,
            actor=approver_user_id,
            comments=u"领用申请 {} 审核通过：申请人 {}，{}；"
                     u"扣减 {} {}，库存 {} → {}".format(
                         request_id, applicant, reviewer_text,
                         quantity, api.safe_unicode(line.get("unit_title") or u""),
                         current, new_amount),
            extra=audit_extra,
        )
        batch.reindexObject()
        applied[uid] = applied.get(uid, 0) + 1
        deducted += 1
    return deducted
