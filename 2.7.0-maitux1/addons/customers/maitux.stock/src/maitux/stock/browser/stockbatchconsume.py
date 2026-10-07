# -*- coding: utf-8 -*-
"""库存批次领用页。

两种模式
--------
1. **直接领用**：所选批次的库存都没勾选"领用需电子签名"时，保持原有行为——
   校验后立即扣减库存并写流水。
2. **申请领用**：只要有一个批次属于需签名的库存，就**不允许直接扣减**，
   而是生成一张领用申请单（StockUsageRequest），并**立即提交进入"待审核"**：

       提交申请（不需要签名）-> 待审核 -> 审核人（非申请人）签名 -> 自动扣减

   注意：发起领用**不需要**申请人签名（需求口径：一次领用只有审核人一次签名）。
   扣减动作由审核通过时的 IBeforeTransitionEvent 执行（见 subscribers.py），
   不在本视图里做。
"""
from decimal import Decimal
from uuid import uuid4

import transaction
from Products.Five.browser import BrowserView
from ZODB.POSException import ConflictError
from bika.lims import api
from maitux.stock import stockMessageFactory as _
from senaite.core.api import dtime
from senaite.core import logger

from maitux.stock.config import STOCK_MANAGER_ID
from maitux.stock.config import USAGE_REQUESTS_ID
from maitux.stock.config import USAGE_REQUEST_TYPE
from maitux.stock.stockbatchexpiry import expire_batch
from maitux.stock.stockbatchexpiry import get_operation_block_message
from maitux.stock.stockbatchexpiry import is_due_for_expiry
from maitux.stock.usageapproval import any_batch_requires_signature
from maitux.stock.usageapproval import append_usage_record
from maitux.stock.usageapproval import build_line
from maitux.stock.usageapproval import get_batch_stock
from maitux.stock.usageapproval import stock_requires_signature


class StockBatchConsumeView(BrowserView):
    def __call__(self):
        if "form.button.cancel" in getattr(self.request, "form", {}):
            return self.request.response.redirect(api.get_url(self.context))

        if "form.button.submit" in getattr(self.request, "form", {}):
            return self.handle_submit()

        return self.index()

    # ------------------------------------------------------------------
    # 入参解析
    # ------------------------------------------------------------------
    def get_uids(self):
        uids = self.request.get("uids", "")
        if isinstance(uids, (list, tuple)):
            uids = ",".join(uids)
        uids = [u.strip() for u in api.safe_unicode(uids).split(",") if u.strip()]
        uids = filter(api.is_uid, uids)
        return list(uids)

    def get_batches(self):
        batches = []
        for uid in self.get_uids():
            obj = api.get_object_by_uid(uid, default=None)
            if not api.is_object(obj):
                continue
            if api.get_portal_type(obj) != "StockBatch":
                continue
            batches.append(obj)
        return batches

    def _first_uid(self, value):
        """兼容原有调用点（实现见 usageapproval.first_uid）。"""
        from maitux.stock.usageapproval import first_uid
        return first_uid(value)

    def get_batch_stock(self, batch):
        """批次关联的 Stock 主数据（无关联返回 None）。"""
        return get_batch_stock(batch)

    def stock_requires_countersign(self, stock):
        """该 Stock 是否勾选了"领用需电子签名"（保留旧方法名，语义见 usageapproval）。"""
        return stock_requires_signature(stock)

    def get_display_info(self, batch):
        stock = self.get_batch_stock(batch)

        unit_uid = self._first_uid(getattr(batch, "unit", "") or "")
        unit = api.get_object_by_uid(unit_uid, default=None) if unit_uid else None

        return {
            "uid": api.get_uid(batch),
            "title": api.get_title(batch),
            "batch_id": getattr(batch, "batch_id", "") or "",
            "stock_title": api.get_title(stock) if stock else "",
            "current_amount": getattr(batch, "current_amount", "") or "",
            "unit_title": api.get_title(unit) if unit else "",
            "requires_signature": self.stock_requires_countersign(stock),
        }

    def get_posted_qty(self, uid):
        key = "qty.{}".format(uid)
        raw = self.request.form.get(key, "")
        raw = api.safe_unicode(raw).strip()
        if not raw:
            return None
        try:
            return Decimal(raw)
        except Exception:
            return None

    def get_posted_remarks(self, uid):
        key = "remarks.{}".format(uid)
        raw = self.request.form.get(key, "")
        return api.safe_unicode(raw or u"").strip()

    def get_posted_purpose(self):
        """领用用途（申请模式下必填）。"""
        raw = self.request.form.get("purpose", "")
        return api.safe_unicode(raw or u"").strip()

    # ------------------------------------------------------------------
    # 需要签名 -> 生成领用申请单
    # ------------------------------------------------------------------
    def requires_signature(self, batches=None):
        """所选批次里只要有一个属于"需签名"的库存，整单就必须走申请审批。"""
        if batches is None:
            batches = self.get_batches()
        return any_batch_requires_signature(batches)

    def get_usage_requests_container(self):
        """定位领用申请单目录（stockmanager/usage_requests）。"""
        portal = api.get_portal()
        manager = portal.get(STOCK_MANAGER_ID) if portal else None
        if manager is None:
            obj = self.context
            while obj is not None:
                manager = getattr(obj, "aq_parent", None)
                if manager is not None and STOCK_MANAGER_ID in getattr(
                        manager, "objectIds", lambda: [])():
                    break
                obj = manager
        if manager is None or USAGE_REQUESTS_ID not in getattr(
                manager, "objectIds", lambda: [])():
            return None
        return manager[USAGE_REQUESTS_ID]

    def create_usage_request(self, lines, purpose):
        """创建申请单并把 id 规整成申请单号，失败返回 None。"""
        container = self.get_usage_requests_container()
        if container is None:
            logger.error(
                "Stock usage requests container '%s/%s' not found; "
                "re-run the maitux.stock profile import.",
                STOCK_MANAGER_ID, USAGE_REQUESTS_ID)
            return None

        temp_id = "sur-{}".format(uuid4().hex[:8])
        try:
            obj_id = container.invokeFactory(USAGE_REQUEST_TYPE, temp_id)
            usage_request = container[obj_id]
        except Exception:
            logger.exception("Failed to create %s", USAGE_REQUEST_TYPE)
            return None

        usage_request.purpose = api.safe_unicode(purpose)
        usage_request.lines = list(lines)
        usage_request.reindexObject()

        # 用申请单号做 id，便于审计里直接引用（例如 SUR-00001）
        request_id = api.safe_unicode(getattr(usage_request, "request_id", "") or "")
        if request_id and request_id != obj_id:
            try:
                container.manage_renameObject(obj_id, request_id)
            except Exception:
                logger.warning(
                    "Could not rename usage request '%s' to '%s'",
                    obj_id, request_id)
        return usage_request

    def build_submit_url(self, usage_request):
        """兜底提交入口（申请单详情页上的"提交审核"按钮用它）。"""
        return "{}/@@workflow_action?workflow_action_id=submit".format(
            api.get_url(usage_request))

    def submit_usage_request(self, usage_request):
        """把新建的申请单推进到"待审核"。

        中文注释：**发起领用不需要电子签名**（需求口径：只有审核人签名）。
        所以这里直接执行工作流迁移，不再跳转签名页。
        """
        workflow = api.get_tool("portal_workflow")
        if workflow is None:
            return False
        try:
            workflow.doActionFor(usage_request, "submit")
        except Exception as exc:
            logger.exception(
                "Failed to submit StockUsageRequest '%s': %s",
                getattr(usage_request, "request_id", ""), exc)
            return False
        if api.safe_unicode(api.get_review_status(usage_request) or "") != "submitted":
            logger.error(
                "StockUsageRequest '%s' did not reach state 'submitted'",
                getattr(usage_request, "request_id", ""))
            return False
        try:
            usage_request.reindexObject()
        except Exception:
            pass
        return True

    def handle_request(self, batches):
        """申请模式：校验 -> 建申请单 -> 直接提交进入"待审核"（不扣库存）。"""
        now = dtime.now()
        workflow = api.get_tool("portal_workflow")

        purpose = self.get_posted_purpose()
        errors = []
        if not purpose:
            errors.append((u"*", u"Purpose is required for a usage request."))

        updates, update_errors = self.collect_updates(
            batches, now=now, workflow=workflow)
        errors.extend(update_errors)

        if errors:
            self.request["consume_errors"] = errors
            return self.index()

        lines = [
            build_line(batch, qty, remarks)
            for batch, qty, remarks, _current in updates
        ]

        usage_request = self.create_usage_request(lines, purpose)
        if usage_request is None:
            self.request["consume_errors"] = [(
                u"*",
                u"Failed to create the usage request. Please contact the "
                u"administrator (is the stock structure installed?).",
            )]
            return self.index()

        submitted = self.submit_usage_request(usage_request)
        if not submitted:
            # 留成草稿，申请人可以在申请单上点"提交审核"重试
            self.request["consume_errors"] = [(
                u"*",
                u"The usage request was created but could not be submitted. "
                u"Please open it and submit it again.",
            )]
            return self.index()

        logger.info(
            "Created StockUsageRequest '%s' with %s line(s), now pending review.",
            getattr(usage_request, "request_id", ""), len(lines))
        self.context.plone_utils.addPortalMessage(
            _("Usage request submitted for review."), "info")
        return self.request.response.redirect(api.get_url(usage_request))

    # ------------------------------------------------------------------
    # 校验与直接扣减（不需签名的库存走这条老路径）
    # ------------------------------------------------------------------
    def collect_updates(self, batches, now=None, workflow=None):
        """校验所选批次并收集待扣减项，返回 (updates, errors)。"""
        if now is None:
            now = dtime.now()
        if workflow is None:
            workflow = api.get_tool("portal_workflow")

        errors = []
        updates = []
        for batch in batches:
            # 业务双保险：即使定时任务尚未来得及执行，到期批次也必须先转为过期。
            if is_due_for_expiry(batch, now=now):
                try:
                    expire_batch(
                        batch,
                        workflow_tool=workflow,
                        now=now,
                        operator=u"system",
                        remarks=u"Auto expired before consume",
                    )
                except Exception as exc:
                    errors.append((api.get_uid(batch), u"Failed to expire batch: {}".format(api.safe_unicode(exc))))
                    continue

            block_message = get_operation_block_message(batch, now=now)
            if block_message:
                errors.append((api.get_uid(batch), block_message))
                continue
            uid = api.get_uid(batch)
            qty = self.get_posted_qty(uid)
            if qty is None:
                errors.append((uid, u"Invalid quantity"))
                continue
            if qty <= 0:
                errors.append((uid, u"Quantity must be greater than 0"))
                continue

            current = getattr(batch, "current_amount", None)
            try:
                current = Decimal(current) if current is not None else Decimal("0.00")
            except Exception:
                current = Decimal("0.00")

            if qty > current:
                errors.append((uid, u"Quantity exceeds current amount"))
                continue

            remarks = self.get_posted_remarks(uid)
            updates.append((batch, qty, remarks, current))
        return updates, errors

    def append_usage_record(self, batch, now=None, operator=u"", qty=None,
                            remarks=u"", second_operator=u"", request_id=u""):
        """追加一条 consume 流水（实现见 usageapproval.append_usage_record）。"""
        return append_usage_record(
            batch, now=now, operator=operator, qty=qty, remarks=remarks,
            second_operator=second_operator, request_id=request_id)

    def apply_updates(self, updates, now=None):
        """原子地扣减库存并写流水（仅用于无需签名的直接领用）。"""
        if now is None:
            now = dtime.now()

        user = api.get_current_user()
        user_id = user.getId() if user else ""

        # 批量扣减必须保持原子性，任一批次失败时回滚本次请求中的全部改动。
        savepoint = transaction.savepoint()

        updated = 0
        try:
            for batch, qty, remarks, current in updates:
                if not api.security.check_permission("Modify portal content", batch):
                    raise UnauthorizedConsumeError(
                        u"No permission to modify batch '{}'".format(api.get_uid(batch))
                    )

                new_amount = current - qty
                batch.current_amount = new_amount
                batch.usage_records = self.append_usage_record(
                    batch, now=now, operator=user_id, qty=qty, remarks=remarks)
                batch.reindexObject()
                updated += 1
        except ConflictError:
            savepoint.rollback()
            logger.exception("Stock batch consume conflict, rolled back all updates")
            raise
        except Exception as exc:
            savepoint.rollback()
            logger.exception("Stock batch consume failed, rolled back all updates: %s", exc)
            self.context.plone_utils.addPortalMessage(
                _("Consume failed. All changes have been rolled back."),
                "error",
            )
            self.request["consume_errors"] = [(u"*", api.safe_unicode(exc))]
            return self.index()

        if updated == 0:
            self.context.plone_utils.addPortalMessage(_("No changes made."), "warning")
            return self.request.response.redirect(api.get_url(self.context))

        self.context.plone_utils.addPortalMessage(_("Changes saved."), "info")
        return self.request.response.redirect(api.get_url(self.context))

    def handle_submit(self):
        batches = self.get_batches()
        if not batches:
            self.context.plone_utils.addPortalMessage(_("No items selected."), "warning")
            return self.request.response.redirect(api.get_url(self.context))

        # 中文注释：需要电子签名的库存**不允许直接领用**，一律走申请审批。
        if self.requires_signature(batches):
            return self.handle_request(batches)

        now = dtime.now()
        workflow = api.get_tool("portal_workflow")
        updates, errors = self.collect_updates(batches, now=now, workflow=workflow)
        if errors:
            self.request["consume_errors"] = errors
            return self.index()
        return self.apply_updates(updates, now=now)


class UnauthorizedConsumeError(Exception):
    """批量扣减时的权限异常。"""
