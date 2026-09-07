# -*- coding: utf-8 -*-
"""Worksheet 多选字段行为（仪器多选 + 库存批次多选）

实现方式与 maitux.reviewerassignment 的审核人字段一致：
- 用 plone.behavior 给 Worksheet（Dexterity 类型）追加两个 UID 引用字段；
- 通过 ZCML 注册行为、安装时用 `api.enable_behavior()` 挂到 FTI；
- 读写走 schema field 对象（与 senaite.core 内部字段同一套机制），
  因此普通 dexterity /edit 表单也能正确渲染 UID 引用部件。

字段语义（产品确认）：
- `instruments`：本工作表关联的仪器（多选）。仅作记录，不自动分配到
  工作表内每个分析（不改变每行分析自身的仪器）。
- `stock_batches`：本工作表关联的库存批次对象（多选，含已过期/销毁）。
"""

from AccessControl import ClassSecurityInfo
from plone.autoform.interfaces import IFormFieldProvider
from plone.behavior.interfaces import IBehavior
from plone.supermodel import model
from senaite.core import logger
from senaite.core.behaviors.utils import get_behavior_schema
from senaite.core.schema import UIDReferenceField
from zope.interface import implementer
from zope.interface import provider

from maitux.worksheetfields import worksheetfieldsMessageFactory as _
from maitux.worksheetfields.config import INSTRUMENT_PORTAL_TYPE
from maitux.worksheetfields.config import INSTRUMENTS_FIELD
from maitux.worksheetfields.config import STOCK_BATCHES_FIELD
from maitux.worksheetfields.config import STOCK_BATCH_PORTAL_TYPE


@provider(IFormFieldProvider)
class IWorksheetMultiSelectSchema(model.Schema):
    """Worksheet 仪器/库存批次多选字段"""

    instruments = UIDReferenceField(
        title=_(
            u"title_worksheet_multi_instruments",
            default=u"Instruments",
        ),
        description=_(
            u"description_worksheet_multi_instruments",
            default=u"Multiple instruments associated with this worksheet. "
                    u"Stored for traceability; they are not assigned "
                    u"automatically to the contained analyses.",
        ),
        allowed_types=(INSTRUMENT_PORTAL_TYPE,),
        multi_valued=True,
        required=False,
    )

    stock_batches = UIDReferenceField(
        title=_(
            u"title_worksheet_stock_batches",
            default=u"Stock Batches",
        ),
        description=_(
            u"description_worksheet_stock_batches",
            default=u"Multiple Stock Batch objects associated with this "
                    u"worksheet (from the maitux.stock module).",
        ),
        allowed_types=(STOCK_BATCH_PORTAL_TYPE,),
        multi_valued=True,
        required=False,
    )


@implementer(IBehavior, IWorksheetMultiSelectSchema)
class WorksheetMultiSelectBehaviorFactory(object):
    """行为工厂：给 Worksheet 提供多选字段访问器"""

    security = ClassSecurityInfo()

    def __init__(self, context):
        self.context = context
        self._schema = None

    @property
    def schema(self):
        """延迟获取扩展后的 schema"""
        if self._schema is None:
            self._schema = get_behavior_schema(
                self.context, IWorksheetMultiSelectSchema)
        return self._schema

    # ------------------------------------------------------------
    # Instruments (multi)
    # ------------------------------------------------------------

    def getRawInstruments(self):
        """返回原始 UID 列表"""
        field = self.schema.get(INSTRUMENTS_FIELD)
        if field is None:
            return []
        return field.get_raw(self.context) or []

    def getInstruments(self):
        """返回关联仪器对象列表"""
        field = self.schema.get(INSTRUMENTS_FIELD)
        if field is None:
            return []
        return field.get(self.context) or []

    def setInstruments(self, value):
        """写入仪器关联（接受 UID/对象/列表）"""
        field = self.schema.get(INSTRUMENTS_FIELD)
        if field is None:
            return
        field.set(self.context, value)
        logger.info(
            "Worksheet %s instruments set to %r",
            self.context.getId(), self.getRawInstruments())

    instruments = property(getInstruments, setInstruments)
    raw_instruments = property(getRawInstruments, setInstruments)

    # ------------------------------------------------------------
    # Stock Batches (multi)
    # ------------------------------------------------------------

    def getRawStockBatches(self):
        """返回原始 UID 列表"""
        field = self.schema.get(STOCK_BATCHES_FIELD)
        if field is None:
            return []
        return field.get_raw(self.context) or []

    def getStockBatches(self):
        """返回关联库存批次对象列表"""
        field = self.schema.get(STOCK_BATCHES_FIELD)
        if field is None:
            return []
        return field.get(self.context) or []

    def setStockBatches(self, value):
        """写入库存批次关联（接受 UID/对象/列表）"""
        field = self.schema.get(STOCK_BATCHES_FIELD)
        if field is None:
            return
        field.set(self.context, value)
        logger.info(
            "Worksheet %s stock batches set to %r",
            self.context.getId(), self.getRawStockBatches())

    stock_batches = property(getStockBatches, setStockBatches)
    raw_stock_batches = property(getRawStockBatches, setStockBatches)


# ====================================================================
# 便捷读写函数（供视图/API 使用；ws 可为 Worksheet 或行为实例）
# ====================================================================

def _get_field(context, name):
    """按字段名取得 worksheet 扩展 schema 中的 field 对象"""
    schema = get_behavior_schema(context, IWorksheetMultiSelectSchema)
    return schema.get(name)


def get_worksheet_instruments(context):
    """返回关联仪器 UID 列表"""
    try:
        return _get_field(context, INSTRUMENTS_FIELD).get_raw(context) or []
    except Exception:
        return []


def get_worksheet_instrument_objects(context):
    """返回关联仪器对象列表"""
    try:
        return _get_field(context, INSTRUMENTS_FIELD).get(context) or []
    except Exception:
        return []


def set_worksheet_instruments(context, values):
    """写入仪器 UID/对象列表"""
    _get_field(context, INSTRUMENTS_FIELD).set(context, values)


def get_worksheet_stock_batches(context):
    """返回关联库存批次 UID 列表"""
    try:
        return _get_field(context, STOCK_BATCHES_FIELD).get_raw(context) or []
    except Exception:
        return []


def get_worksheet_stock_batch_objects(context):
    """返回关联库存批次对象列表"""
    try:
        return _get_field(context, STOCK_BATCHES_FIELD).get(context) or []
    except Exception:
        return []


def set_worksheet_stock_batches(context, values):
    """写入库存批次 UID/对象列表"""
    _get_field(context, STOCK_BATCHES_FIELD).set(context, values)
