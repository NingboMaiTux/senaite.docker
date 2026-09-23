# -*- coding: utf-8 -*-
from bika.lims import api
from Products.Five.browser import BrowserView

from maitux.stock.browser.stockusagerequest import format_datetime
from maitux.stock.usageapproval import BATCH_AUDIT_APPROVED
from maitux.stock.usageapproval import BATCH_AUDIT_REJECTED
from maitux.stock.usageapproval import check_approver
from maitux.stock.usageapproval import find_pending_requests_for_batch
from maitux.stock.i18n import translate_stock


# 审计快照 action -> 英文 msgid（渲染时用 translate_stock 按语言翻译）
AUDIT_ACTION_LABELS = {
    u"create": u"Created",
    BATCH_AUDIT_APPROVED: u"Usage approved",
    BATCH_AUDIT_REJECTED: u"Usage rejected",
    u"expire": u"Expired",
    u"destroy": u"Destroyed",
    u"edit": u"Edited",
}


class StockBatchView(BrowserView):
    def review_state(self):
        return api.get_review_status(self.context) or ""

    def current_user_id(self):
        user = api.get_current_user()
        return user.getId() if user else u""

    def pending_requests(self):
        """该批次上等待审核的领用申请。"""
        return find_pending_requests_for_batch(self.context)

    def reviewable_request(self):
        """当前用户可以审核的那条（非申请人 + 有审批角色），否则 None。"""
        for request in self.pending_requests():
            if not check_approver(request, self.current_user_id()):
                return request
        return None

    def pending_request_items(self):
        """给模板用的展示数据。"""
        rows = []
        reviewable = self.reviewable_request()
        for request in self.pending_requests():
            rows.append({
                "url": api.get_url(request),
                "request_id": api.safe_unicode(
                    getattr(request, "request_id", "") or api.get_title(request)),
                "applicant": api.safe_unicode(
                    getattr(request, "applicant_fullname", "")
                    or getattr(request, "applicant", "") or u""),
                "purpose": api.safe_unicode(getattr(request, "purpose", "") or u""),
                "request_date": api.safe_unicode(
                    getattr(request, "request_date", "") or u""),
                "can_review": reviewable is not None and request == reviewable,
            })
        return rows

    def as_title(self, uid):
        if not uid:
            return ""
        if isinstance(uid, (list, tuple)):
            uid = uid[0] if uid else ""
            if not uid:
                return ""
        uid = api.safe_unicode(uid)
        parts = uid.splitlines()
        uid = parts[0] if parts else ""
        obj = api.get_object_by_uid(uid, default=None) if uid else None
        # 中文注释：统一返回 unicode，避免中文标题以 utf8 字节串进入模板
        return api.safe_unicode(api.get_title(obj)) if obj else u""

    def usage_records(self):
        return getattr(self.context, "usage_records", []) or []

    def audit_trail(self):
        """批次的审计追踪（最新在前）。

        数据来自对象自身的快照存储（``bika.lims.api.snapshot``），
        所以不依赖审计目录是否索引了这个对象。
        """
        rows = []
        try:
            from bika.lims.api.snapshot import get_snapshot_metadata
            from bika.lims.api.snapshot import get_snapshots
        except ImportError:
            return rows
        try:
            snapshots = list(get_snapshots(self.context) or [])
        except Exception:
            return rows

        for snapshot in reversed(snapshots):
            metadata = get_snapshot_metadata(snapshot) or {}
            action = api.safe_unicode(metadata.get("action") or u"")
            actor = api.safe_unicode(metadata.get("actor") or u"")
            roles = metadata.get("roles") or []
            if not isinstance(roles, (list, tuple)):
                roles = [roles]
            rows.append({
                "action": action,
                "action_label": translate_stock(
                    AUDIT_ACTION_LABELS.get(action, action)),
                "modified": format_datetime(metadata.get("modified")),
                "actor": actor,
                "actor_fullname": api.safe_unicode(
                    api.get_user_fullname(actor) or u""),
                "roles": u", ".join(api.safe_unicode(role) for role in roles),
                "comments": api.safe_unicode(metadata.get("comments") or u""),
                "amount_after": api.safe_unicode(
                    snapshot.get("current_amount") or u""),
                "request": api.safe_unicode(snapshot.get(u"Usage Request") or u""),
                "remote_address": api.safe_unicode(
                    metadata.get("remote_address") or u""),
            })
        return rows

    def auditlog_url(self):
        """标准审计追踪页面（带字段 diff，内容更全）。"""
        return u"{}/@@auditlog".format(api.get_url(self.context))

    def operation_label(self, op):
        # 英文 msgid，渲染时按当前语言翻译（见 maitux/stock/i18n.py）
        mapping = {
            u"create": u"Created",
            u"consume": u"Consumed",
            u"expire": u"Expired",
            u"return": u"Returned",
            u"destroy": u"Destroyed",
            u"split": u"Split",
            u"adjust": u"Adjusted",
            u"stocktake": u"Stock take",
        }
        value = mapping.get(api.safe_unicode(op), api.safe_unicode(op))
        return translate_stock(value)
