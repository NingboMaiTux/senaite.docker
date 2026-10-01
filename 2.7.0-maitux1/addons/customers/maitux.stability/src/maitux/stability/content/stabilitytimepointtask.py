# -*- coding: utf-8 -*-
from maitux.stability import stabilityMessageFactory as _
from maitux.stability.title import TranslatableTitleMixin
from plone.autoform import directives
from plone.supermodel import model
from senaite.core.catalog import SETUP_CATALOG
from senaite.core.catalog import SENAITE_CATALOG
from senaite.core.config.widgets import get_default_columns
from senaite.core.content.base import Item
from senaite.core.interfaces import IMultiCatalogBehavior
from senaite.core.schema import DatetimeField
from senaite.core.schema import UIDReferenceField
from senaite.core.z3cform.widgets.uidreference import UIDReferenceWidgetFactory
from z3c.form.interfaces import IAddForm
from zope import schema
from zope.interface import implementer
from zope.schema.vocabulary import SimpleTerm
from zope.schema.vocabulary import SimpleVocabulary

from maitux.stability.interfaces import IStabilityTimepointTask
from maitux.stability.timepoints import PHARMACOPOEIA_MONTHS


ORIENTATION_VOCABULARY = SimpleVocabulary((
    SimpleTerm(value=u"upright", token="upright", title=_(u"Upright")),
    SimpleTerm(value=u"inverted", token="inverted", title=_(u"Inverted")),
    SimpleTerm(value=u"horizontal", token="horizontal", title=_(u"Horizontal")),
))

DETAIL_STATUS_VOCABULARY = SimpleVocabulary((
    SimpleTerm(value=u"pending_placement", token="pending_placement", title=_(u"Pending Placement")),
    # 「已放置」：只记了库存批次，还没有登样（先放置、再登样）
    SimpleTerm(value=u"placed", token="placed", title=_(u"Placed")),
    SimpleTerm(value=u"active", token="active", title=_(u"Active")),
    SimpleTerm(value=u"completed", token="completed", title=_(u"Completed")),
))

# 时间点（月）词表：与方案明细共用同一份药典序列（含零点），
# 唯一实现在 maitux.stability.timepoints —— 两处词表必须一致，否则
# 明细能填 0 而任务填不了（或反过来），同步时会互相打架。
MONTHS_VOCABULARY = SimpleVocabulary(tuple([
    SimpleTerm(value=month, token=str(month), title=u"%s" % month)
    for month in PHARMACOPOEIA_MONTHS
]))


class IStabilityTimepointTaskSchema(model.Schema):
    sequence = schema.Int(
        title=_(u"Sequence"),
        required=False,
        default=0,
        min=0,
    )
    directives.mode(sequence="hidden")
    directives.mode(IAddForm, sequence="hidden")

    directives.widget(
        "packaging_specification",
        UIDReferenceWidgetFactory,
        catalog=SETUP_CATALOG,
        query={
            "portal_type": "PackagingSpecification",
            "is_active": True,
            "sort_on": "sortable_title",
            "sort_order": "ascending",
        },
        display_template="<a href='${url}'>${Title}</a>",
        columns=get_default_columns,
    )
    packaging_specification = UIDReferenceField(
        title=_(u"Packaging Specification"),
        allowed_types=("PackagingSpecification",),
        multi_valued=False,
        required=False,
    )

    directives.widget(
        "storage_condition",
        UIDReferenceWidgetFactory,
        catalog=SETUP_CATALOG,
        query={
            "portal_type": "StorageCondition",
            "is_active": True,
            "sort_on": "sortable_title",
            "sort_order": "ascending",
        },
        display_template="<a href='${url}'>${Title}</a>",
        columns=get_default_columns,
    )
    storage_condition = UIDReferenceField(
        title=_(u"Storage Condition"),
        allowed_types=("StorageCondition",),
        multi_valued=False,
        required=False,
    )

    orientation = schema.Choice(
        title=_(u"Orientation"),
        vocabulary=ORIENTATION_VOCABULARY,
        required=False,
        default=u"upright",
    )

    timepoint_days = schema.Choice(
        title=_(u"Timepoint (Months)"),
        required=True,
        vocabulary=MONTHS_VOCABULARY,
    )

    window_days = schema.Int(
        title=_(u"Window (Days)"),
        required=False,
        default=0,
        min=0,
    )

    # 样品模板：与明细行同值（**逐个时间点维护**，2026-09-29 需求订正）。
    # 行上原有的「检验标准 / 分析套餐」已删除 —— 检验项一律来自该行选的样品模板。
    directives.widget(
        "sample_template",
        UIDReferenceWidgetFactory,
        catalog=SETUP_CATALOG,
        query={
            "portal_type": "SampleTemplate",
            "is_active": True,
            "sort_on": "sortable_title",
            "sort_order": "ascending",
        },
        display_template="<a href='${url}'>${Title}</a>",
        columns=get_default_columns,
    )
    sample_template = UIDReferenceField(
        title=_(u"Sample Template"),
        description=_(
            u"Sample type and analyses for this timepoint come from this "
            u"template: samples are created with the template's analyses."
        ),
        allowed_types=("SampleTemplate",),
        multi_valued=False,
        required=False,
    )

    inspection_quantity = schema.Int(
        title=_(u"Inspection Quantity"),
        required=False,
        default=0,
        min=0,
    )

    directives.widget(
        "batch",
        UIDReferenceWidgetFactory,
        catalog=SENAITE_CATALOG,
        query={
            "portal_type": "Batch",
            "is_active": True,
            "sort_on": "created",
            "sort_order": "descending",
        },
        display_template="<a href='${url}'>${Title}</a>",
        columns=get_default_columns,
    )
    batch = UIDReferenceField(
        title=_(u"Batch"),
        allowed_types=("Batch",),
        multi_valued=False,
        required=False,
    )

    detail_status = schema.Choice(
        title=_(u"Status"),
        vocabulary=DETAIL_STATUS_VOCABULARY,
        required=True,
        default=u"pending_placement",
    )

    directives.widget(
        "stock_batch",
        UIDReferenceWidgetFactory,
        catalog="portal_catalog",
        query={
            "portal_type": "StockBatch",
            "review_state": "active",
            "sort_on": "sortable_title",
            "sort_order": "ascending",
        },
        display_template="<a href='${url}'>${Title}</a>",
        columns=get_default_columns,
    )
    stock_batch = UIDReferenceField(
        title=_(u"Stock Batch"),
        allowed_types=("StockBatch",),
        multi_valued=False,
        required=False,
    )

    directives.mode(target_date="display")
    directives.mode(IAddForm, target_date="hidden")
    target_date = DatetimeField(
        title=_(u"Target Date"),
        required=False,
        readonly=True,
    )

    directives.mode(window_start="display")
    directives.mode(IAddForm, window_start="hidden")
    window_start = DatetimeField(
        title=_(u"Window Start"),
        required=False,
        readonly=True,
    )

    directives.mode(window_end="display")
    directives.mode(IAddForm, window_end="hidden")
    window_end = DatetimeField(
        title=_(u"Window End"),
        required=False,
        readonly=True,
    )

    notes = schema.TextLine(
        title=_(u"Notes"),
        required=False,
    )

    # 与方案明细行 ``plan_details[*].detail_uid`` 同一个值。
    #
    # 任务与明细的配对**只能**靠它：序列号 `sequence` 是照行号写的，
    # 明细删掉中间一行后所有行号都会平移，按序号配对会删错对象
    # （见 maitux.stability.timepoints 的模块说明）。
    #
    # 本功能上线前创建的任务没有这个值 —— 那种历史任务按无 id 处理，
    # 由调用方按 `sequence` 兜底配对。
    directives.mode(detail_uid="display")
    directives.mode(IAddForm, detail_uid="hidden")
    detail_uid = schema.TextLine(
        title=_(u"Timepoint ID"),
        required=False,
        readonly=True,
    )

    # ── 阶段 6c：作废三件套（与明细行上的同名键**同一个含义**）────────────
    #
    # 需求（确认稿 0.2 ③）：作废行的**时间点任务保留并同步标记为已作废**，
    # 不删除 —— 与"保留审计"的口径一致。
    #
    # ★ 为什么任务上要**加 schema 字段**，而明细行上只用非 schema 键：
    #   明细行是 DataGrid 里的 dict（加键不影响任何人），
    #   而任务是 Dexterity 对象 —— 未声明的属性写不进去（AttributeError）。
    #   这三个字段只读、不进任何表单，纯粹是"给任务盖一个已废弃的章"。
    # ★ 为什么不给任务加第五个 detail_status 值：状态词表是明细与任务**共用**的，
    #   动它就要动 8 处状态映射（确认稿 D6 明确否掉了这条路）。
    # ★ 阶段 6d：用户把这一套的说法从「作废」改成「删除 / 已废弃」（状态删除）——
    #   **字段名与数据键不改**（`voided_at/by/reason`，改了要迁移历史数据），
    #   只改用户可见的标题与说明。
    directives.mode(voided_at="display")
    directives.mode(IAddForm, voided_at="hidden")
    voided_at = schema.TextLine(
        title=_(u"Discarded at"),
        description=_(u"Set when the timepoint row was deleted "
                      u"(status deleted)."),
        required=False,
        readonly=True,
    )

    directives.mode(voided_by="display")
    directives.mode(IAddForm, voided_by="hidden")
    voided_by = schema.TextLine(
        title=_(u"Discarded by"),
        required=False,
        readonly=True,
    )

    directives.mode(void_reason="display")
    directives.mode(IAddForm, void_reason="hidden")
    void_reason = schema.Text(
        title=_(u"Discard reason"),
        description=_(u"Optional: why the timepoint row was discarded."),
        required=False,
        readonly=True,
    )

    # 说明：原先这里有个 invariant「检验标准与检验组合二选一」——
    # 2026-09-29 需求订正后，任务（与明细行）上不再有这两个字段，
    # 检验项一律来自该时间点的样品模板，所以这条 invariant 一起删掉。
    # 样品模板允许为空（历史任务可能还没补），登样页会把它标成"不可登样"。


@implementer(IStabilityTimepointTask, IStabilityTimepointTaskSchema,
             IMultiCatalogBehavior)
class StabilityTimepointTask(TranslatableTitleMixin, Item):
    # ★ `IMultiCatalogBehavior` 必须显式声明：没有它，senaite 的目录总闸门
    #   （CatalogMultiplexProcessor.supports_multi_catalogs）会**静默跳过**索引，
    #   `reindexObject()` 变成空操作 —— 现象是"任务建出来了，看板/列表看不到"。
    #   详见 maitux.stability.indexing 的模块说明。
    _catalogs = [SETUP_CATALOG]

