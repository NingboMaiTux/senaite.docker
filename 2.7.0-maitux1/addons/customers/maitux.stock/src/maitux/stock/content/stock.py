# -*- coding: utf-8 -*-
from decimal import Decimal

from maitux.stock import stockMessageFactory as _
from bika.lims.interfaces import IDeactivable
from plone.autoform import directives
from plone.supermodel import model
from senaite.core.catalog import SETUP_CATALOG
from senaite.core.content.base import Item
from senaite.core.schema.datetimefield import DatetimeField
from senaite.core.schema import TextLineField
from senaite.core.schema import UIDReferenceField
from senaite.core.z3cform.widgets.uidreference import UIDReferenceWidgetFactory
from z3c.form.interfaces import IFieldWidget
from z3c.form.widget import FieldWidget
from zope import schema
from zope.interface import implementer

from maitux.stock.interfaces import IStock
from maitux.stock.z3cform.widgets.datetimeseconds import DatetimeSecondsWidget


@implementer(IFieldWidget)
def StockExpiryDateWidgetFactory(field, request):
    widget = DatetimeSecondsWidget(request)
    widget.show_time = True
    return FieldWidget(field, widget)


class IStockSchema(model.Schema):
    number = TextLineField(
        title=_(u"Stock Number"),
        required=True,
    )

    directives.widget(
        "stock_type",
        UIDReferenceWidgetFactory,
        catalog=SETUP_CATALOG,
        query={
            "is_active": True,
            "sort_on": "sortable_title",
            "sort_order": "ascending",
        },
    )
    stock_type = UIDReferenceField(
        title=_(u"Stock Type"),
        allowed_types=("StockType", ),
        multi_valued=False,
        required=False,
    )

    directives.widget(
        "sample_matrix",
        UIDReferenceWidgetFactory,
        catalog=SETUP_CATALOG,
        query={
            "is_active": True,
            "sort_on": "sortable_title",
            "sort_order": "ascending",
        },
    )
    sample_matrix = UIDReferenceField(
        title=_(u"Name"),
        allowed_types=("SampleMatrix", ),
        multi_valued=False,
        required=False,
    )

    directives.widget(
        "unit",
        UIDReferenceWidgetFactory,
        catalog=SETUP_CATALOG,
        query={
            "is_active": True,
            "sort_on": "sortable_title",
            "sort_order": "ascending",
        },
    )
    unit = UIDReferenceField(
        title=_(u"Unit"),
        allowed_types=("StockUnit", ),
        multi_valued=False,
        required=False,
    )

    directives.widget(
        "location",
        UIDReferenceWidgetFactory,
        catalog=SETUP_CATALOG,
        query={
            "is_active": True,
            "sort_on": "sortable_title",
            "sort_order": "ascending",
        },
    )
    location = UIDReferenceField(
        title=_(u"Storage Location"),
        allowed_types=("InstrumentLocation", ),
        multi_valued=False,
        required=False,
    )

    directives.widget(
        "supplier",
        UIDReferenceWidgetFactory,
        catalog=SETUP_CATALOG,
        query={
            "is_active": True,
            "sort_on": "sortable_title",
            "sort_order": "ascending",
        },
    )
    supplier = UIDReferenceField(
        title=_(u"Supplier"),
        allowed_types=("Supplier", ),
        multi_valued=True,
        required=False,
    )

    quantity = schema.Decimal(
        title=_(u"Quantity"),
        required=True,
        default=Decimal("0.00"),
    )

    # 中文注释：以下字段的文案都走**本包域**（`_` = stockMessageFactory）——
    # 编辑表单的字段标题/描述是按 schema 里的 Message 自带域去查目录的，
    # 用 bikaMessageFactory（bika.lims 域）查不到本包目录，中文站会显示英文。
    directives.widget("expiry_date", StockExpiryDateWidgetFactory)
    expiry_date = DatetimeField(
        title=_(u"Batch Default Expiry Date"),
        description=_(
            u"Default expiry date proposed when creating a new batch of this "
            u"stock. It is only a convenience default: the expiry date is "
            u"stored per batch and the batch value always wins (expiry "
            u"reminders and usage reports read the batch expiry)."
        ),
        required=False,
    )

    # 中文注释：到期提醒天数（配置在物料上，作用于该物料的所有批次）。
    # 批次列表里：已过期 -> 红色行；进入"到期前 N 天"窗口 -> 黄色行。
    # 0 = 关闭提醒（只标已过期）。判定与着色见 maitux/stock/expiryreminder.py。
    expiry_reminder_days = schema.Int(
        title=_(u"Expiry Reminder (days before expiry)"),
        description=_(
            u"Number of days before a batch expiry date at which the stock "
            u"batch listing starts highlighting the row in yellow. Expired "
            u"batches are always highlighted in red. Use 0 to disable the "
            u"reminder."
        ),
        required=False,
        default=30,
        min=0,
        max=3650,
    )

    consume_requires_countersign = schema.Bool(
        title=_(u"Consume Requires Two-Person E-Signature"),
        description=_(
            u"When enabled, consuming any batch of this stock requires two "
            u"different operators to sign electronically on the same page "
            u"before the stock is deducted."
        ),
        required=False,
        default=False,
    )


@implementer(IStock, IStockSchema, IDeactivable)
class Stock(Item):
    _catalogs = ["portal_catalog"]

    def Title(self):
        number = getattr(self, "number", None)
        if number:
            return number
        return super(Stock, self).Title()

