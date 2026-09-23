# -*- coding: utf-8 -*-
"""领用申请单（StockUsageRequest）。

业务链路
--------
需要电子签名的库存，领用时不再直接扣减，而是：

    1. 库存批次列表 [领用] -> 填写数量/用途 -> 生成一张领用申请单（draft）
    2. submit  发起领用：申请人在电子签名页签名        -> submitted
    3. approve 审核领用：**非申请人**签名通过后自动扣减 -> approved
       reject  驳回：非申请人签名 + 理由               -> rejected
       retract 撤回：申请人自己撤回                     -> cancelled

关键约束
--------
* 明细（lines）由领用页生成，在申请单上是**只读**的——签名之后不允许再改数量，
  否则"签了 A、批准 B"就失去意义。
* 明细里同时保存批次 UID 与批次号/库存/单位的**快照**：申请单是留档凭证，
  不能因为后续主数据改名而变样。
"""
from decimal import Decimal

from maitux.stock import stockMessageFactory as _
from plone.autoform import directives
from plone.supermodel import model
from senaite.core.content.base import Item
from senaite.core.schema.datetimefield import DatetimeField
from senaite.core.schema.fields import DataGridField
from senaite.core.schema.fields import DataGridRow
from z3c.form.interfaces import IAddForm
from zope import schema
from zope.interface import implementer

from maitux.stock.interfaces import IStockUsageRequest


class IStockUsageRequestLineSchema(model.Schema):
    """申请明细（一行 = 一个批次）。"""

    batch_uid = schema.TextLine(
        title=_(u"Batch UID"),
        required=True,
    )

    batch_id = schema.TextLine(
        title=_(u"Batch ID"),
        required=False,
    )

    stock_title = schema.TextLine(
        title=_(u"Stock"),
        required=False,
    )

    unit_title = schema.TextLine(
        title=_(u"Unit"),
        required=False,
    )

    requested_quantity = schema.Decimal(
        title=_(u"Quantity"),
        required=True,
        default=Decimal("0.00"),
    )

    remarks = schema.TextLine(
        title=_(u"Remarks"),
        required=False,
    )


class IStockUsageRequestSignatureSchema(model.Schema):
    """签名/审批留痕（一行 = 一次电子签名）。"""

    step = schema.Choice(
        title=_(u"Step"),
        values=(u"submit", u"approve", u"reject"),
        required=True,
        default=u"submit",
    )

    signer = schema.TextLine(
        title=_(u"Signer"),
        required=True,
    )

    meaning = schema.TextLine(
        title=_(u"Meaning"),
        required=False,
    )

    reason = schema.TextLine(
        title=_(u"Reason"),
        required=False,
    )

    signed_at = DatetimeField(
        title=_(u"Signed At"),
        required=False,
    )


class IStockUsageRequestSchema(model.Schema):
    model.fieldset(
        "request_details",
        label=_(u"Request"),
        fields=[
            "request_id",
            "applicant",
            "applicant_fullname",
            "purpose",
            "request_date",
            "status",
        ],
    )

    model.fieldset(
        "usage_lines",
        label=_(u"Requested Items"),
        fields=["lines"],
    )

    model.fieldset(
        "approval",
        label=_(u"Approval Trail"),
        fields=[
            "approver",
            "approver_fullname",
            "approve_date",
            "approve_comment",
            "signature_log",
        ],
    )

    directives.mode(request_id="display")
    directives.mode(IAddForm, request_id="hidden")
    request_id = schema.TextLine(
        title=_(u"Request No."),
        required=False,
        readonly=True,
    )

    directives.mode(applicant="display")
    directives.mode(IAddForm, applicant="hidden")
    applicant = schema.TextLine(
        title=_(u"Applicant"),
        required=False,
        readonly=True,
    )

    directives.mode(applicant_fullname="display")
    directives.mode(IAddForm, applicant_fullname="hidden")
    applicant_fullname = schema.TextLine(
        title=_(u"Applicant Name"),
        required=False,
        readonly=True,
    )

    purpose = schema.Text(
        title=_(u"Purpose"),
        description=_(u"Why this stock is requested; visible to the reviewer."),
        required=True,
    )

    directives.mode(request_date="display")
    directives.mode(IAddForm, request_date="hidden")
    request_date = DatetimeField(
        title=_(u"Submitted On"),
        required=False,
        readonly=True,
    )

    directives.mode(status="display")
    directives.mode(IAddForm, status="hidden")
    status = schema.Choice(
        title=_(u"Status"),
        values=(u"draft", u"submitted", u"approved", u"rejected", u"cancelled"),
        required=False,
        default=u"draft",
    )

    # 明细由领用页生成，签名后不允许再改：这里整块只读
    directives.mode(lines="display")
    directives.mode(IAddForm, lines="hidden")
    lines = DataGridField(
        title=_(u"Requested Items"),
        required=False,
        value_type=DataGridRow(schema=IStockUsageRequestLineSchema),
        default=[],
    )

    directives.mode(approver="display")
    directives.mode(IAddForm, approver="hidden")
    approver = schema.TextLine(
        title=_(u"Reviewer"),
        required=False,
        readonly=True,
    )

    directives.mode(approver_fullname="display")
    directives.mode(IAddForm, approver_fullname="hidden")
    approver_fullname = schema.TextLine(
        title=_(u"Reviewer Name"),
        required=False,
        readonly=True,
    )

    directives.mode(approve_date="display")
    directives.mode(IAddForm, approve_date="hidden")
    approve_date = DatetimeField(
        title=_(u"Reviewed On"),
        required=False,
        readonly=True,
    )

    directives.mode(approve_comment="display")
    approve_comment = schema.Text(
        title=_(u"Rejection Reason"),
        description=_(u"Filled in automatically when the request is rejected."),
        required=False,
        readonly=True,
    )

    directives.mode(signature_log="display")
    directives.mode(IAddForm, signature_log="hidden")
    signature_log = DataGridField(
        title=_(u"Signature Trail"),
        required=False,
        value_type=DataGridRow(schema=IStockUsageRequestSignatureSchema),
        default=[],
    )


@implementer(IStockUsageRequest, IStockUsageRequestSchema)
class StockUsageRequest(Item):
    _catalogs = ["portal_catalog"]

    def Title(self):
        request_id = getattr(self, "request_id", None)
        if request_id:
            return request_id
        return super(StockUsageRequest, self).Title()
