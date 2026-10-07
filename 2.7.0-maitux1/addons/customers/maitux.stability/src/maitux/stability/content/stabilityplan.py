# -*- coding: utf-8 -*-
from bika.lims import api
from maitux.stability import stabilityMessageFactory as _
from maitux.stability.title import TranslatableTitleMixin
from plone.autoform import directives
from plone.namedfile.field import NamedBlobFile
from plone.supermodel import model
from senaite.core.catalog import CLIENT_CATALOG
from senaite.core.catalog import CONTACT_CATALOG
from senaite.core.catalog import SAMPLE_CATALOG
from senaite.core.catalog import SETUP_CATALOG
from senaite.core.catalog import SENAITE_CATALOG
from senaite.core.config.widgets import get_default_columns
from senaite.core.content.base import Container
from senaite.core.interfaces import IMultiCatalogBehavior
from senaite.core import logger
from senaite.core.schema import DatetimeField
from senaite.core.schema.fields import DataGridField
from senaite.core.schema.fields import DataGridRow
from senaite.core.schema import IntField
from senaite.core.schema import UIDReferenceField
from senaite.core.z3cform.widgets.uidreference import UIDReferenceWidgetFactory
from z3c.form.interfaces import IAddForm
from zope import schema
from zope.interface import implementer
from zope.schema.vocabulary import SimpleTerm
from zope.schema.vocabulary import SimpleVocabulary

from maitux.stability.interfaces import IStabilityPlan
from maitux.stability.permissions import ManageSampleAutomation
from maitux.stability.timepoints import PHARMACOPOEIA_MONTHS
from maitux.stability.z3cform.widgets.plandetails import PlanDetailsWidgetFactory
from maitux.stability.z3cform.widgets.plandetails import SafeUIDReferenceWidgetFactory


def _first_uid(value):
    """从字段值里取出一个 UID（DataGrid 里常见的是单元素列表）。"""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if not value:
        return None
    try:
        if api.is_uid(value):
            return value
        return api.get_uid(value)
    except Exception:
        return None


def _client_uid_for_filter(obj):
    """给"联系人下拉按客户过滤"解析客户 UID：对象自身 → 方案模板。

    刻意只用 ``api`` 做字段访问，不 import `maitux.stability.automation` ——
    控件钩子是在**渲染期**被调的，少一层依赖就少一类"钩子静默失效"的可能
    （实测过：方法内部那次跨模块调用没生效，返回原查询）。
    """
    if obj is None:
        return None
    uid = _first_uid(getattr(obj, "client", None))
    if uid:
        return uid
    template_uid = _first_uid(getattr(obj, "plan_template", None))
    if not template_uid:
        return None
    try:
        template = api.get_object_by_uid(template_uid, None)
    except Exception:
        template = None
    if template is None:
        return None
    return _first_uid(getattr(template, "client", None))


ORIENTATION_VOCABULARY = SimpleVocabulary((
    SimpleTerm(value=u"upright", token="upright", title=_(u"Upright")),
    SimpleTerm(value=u"inverted", token="inverted", title=_(u"Inverted")),
    SimpleTerm(value=u"horizontal", token="horizontal", title=_(u"Horizontal")),
))

DETAIL_STATUS_VOCABULARY = SimpleVocabulary((
    SimpleTerm(value=u"pending_placement", token="pending_placement", title=_(u"Pending Placement")),
    # 「已放置」：只记了库存批次，**还没有**登样 —— 2026-09-29 需求订正
    # （先放置、再登样）：放置过的行仍然可以登样。
    SimpleTerm(value=u"placed", token="placed", title=_(u"Placed")),
    SimpleTerm(value=u"active", token="active", title=_(u"Active")),
    SimpleTerm(value=u"completed", token="completed", title=_(u"Completed")),
))

# 时间点（月）词表：**药典序列**（含零点）。词表与零点语义的唯一实现在
# maitux.stability.timepoints，本处只做引用，避免两处 schema 各写一份而漂移。
MONTHS_VOCABULARY = SimpleVocabulary(tuple([
    SimpleTerm(value=month, token=str(month), title=u"%s" % month)
    for month in PHARMACOPOEIA_MONTHS
]))


class IStabilityPlanDetailSchema(model.Schema):
    directives.widget(
        "packaging_specification",
        SafeUIDReferenceWidgetFactory,
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
        SafeUIDReferenceWidgetFactory,
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

    # 样品模板 —— **逐个时间点维护**（2026-09-29 需求订正）。
    #
    # 为什么放在行上而不是方案模板上：**不同时间点要验的东西不一样**
    # （例如 0/3 月做全项、12 月只做稳定性指标）。登样时这一行的客户、
    # 样品类型、检验项**全部**来自这里选的样品模板；行上不再有
    # 「检验标准 / 分析套餐」两个字段（已删除）。
    #
    # 客户仍维护在方案上（方案 → 方案模板 → 本模板自身归属，见 automation.get_client）。
    directives.widget(
        "sample_template",
        SafeUIDReferenceWidgetFactory,
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

    directives.mode(analysis_request="hidden")
    # ⚠️ 样品（AnalysisRequest）编目在 **SAMPLE_CATALOG**（`senaite_catalog_sample`），
    #   不是 portal_catalog（CATALOG_TYPE_MAPPING `("AnalysisRequest", [SAMPLE_CATALOG])`）。
    #   该字段是隐藏列，界面上不渲染下拉，所以之前写错没被发现；
    #   但一旦有人把 mode 改成可编辑，就会是一个永远查不到东西的下拉 —— 先改对。
    directives.widget(
        "analysis_request",
        UIDReferenceWidgetFactory,
        catalog=SAMPLE_CATALOG,
        query={
            "sort_on": "created",
            "sort_order": "descending",
        },
        display_template="<a href='${url}'>${Title}</a>",
        columns=get_default_columns,
    )
    analysis_request = UIDReferenceField(
        title=_(u"Sample"),
        allowed_types=("AnalysisRequest",),
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
        SafeUIDReferenceWidgetFactory,
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

    directives.mode(detail_status="hidden")
    detail_status = schema.Choice(
        title=_(u"Status"),
        vocabulary=DETAIL_STATUS_VOCABULARY,
        required=True,
        default=u"pending_placement",
    )

    notes = schema.TextLine(
        title=_(u"Notes"),
        required=False,
    )

    # 行的稳定标识（界面上是隐藏列）。
    #
    # 为什么不能用行号当身份：DataGrid 允许删行与拖动排序，删掉中间一行后
    # 后面所有行的行号都会平移，而 `StabilityTimepointTask.sequence` 是照行号写的 ——
    # 按行号配对会**删错任务对象**。详见 maitux.stability.timepoints 的模块说明。
    #
    # 放在 schema 最后：列顺序决定 DataGrid 的列序，追加在末尾不会影响
    # 现有列的下标与前端 JS 的取值位置。
    directives.mode(detail_uid="hidden")
    detail_uid = schema.TextLine(
        title=_(u"Timepoint ID"),
        required=False,
    )

    # 登样审计：哪个时间点行在什么时候、被谁登的样。
    #
    # 为什么必须在 schema 里声明：DataGrid 表单**只提交 schema 里的列** ——
    # 不声明就等于每保存一次方案就丢一次（与 detail_uid / stock_batch 同一个坑，
    # 见 maitux.stability.timepoints 的模块说明与 PRESERVED_FIELDS）。
    # 两列都是隐藏列，界面上不可编辑、由登样流程写入。
    directives.mode(generated_at="hidden")
    generated_at = schema.TextLine(
        title=_(u"Generated At"),
        required=False,
    )

    directives.mode(generated_by="hidden")
    generated_by = schema.TextLine(
        title=_(u"Generated By"),
        required=False,
    )

    # 说明：原先这里有个 invariant「检验标准与检验组合二选一」——
    # 2026-09-29 需求订正后，行上不再有这两个字段（检验项一律来自该行的
    # 样品模板），所以这条 invariant 与那两个字段一起删掉了。
    # **不再有行级必填校验**：样品模板可以为空（历史数据/尚未配好），
    # 只是这样的行在登样页会被明确标注"未选择样品模板，无法登样"。


class IStabilityPlanSchema(model.Schema):
    model.fieldset(
        "plan_details",
        label=_(u"Plan Details"),
        fields=[
            "plan_details",
        ],
    )

    model.fieldset(
        "sample_automation",
        label=_(u"Sample Automation"),
        fields=[
            "auto_create_samples",
            "client",
            "contact",
        ],
    )

    # 阶段 6a：方案状态变更的留痕（只读）。
    # 单独一个 fieldset 而不是塞进默认字段组：它们是"痕迹"，不是方案配置，
    # 混在 Description/Start Time 里会被当成可以填的字段。
    # 方案**当前**状态本身是工作流状态（review_state），不在这里 ——
    # 它由方案页上的状态面板与列表页的状态列展示，见 browser/viewlets。
    model.fieldset(
        "plan_status",
        label=_(u"Plan Status"),
        fields=[
            "status_changed_at",
            "status_changed_by",
            "status_reason",
        ],
    )

    directives.write_permission(auto_create_samples=ManageSampleAutomation)
    auto_create_samples = schema.Bool(
        title=_(u"Create samples automatically"),
        description=_(
            u"Inherited from the plan template when the plan is created. "
            u"When it is on, samples are created for every timepoint whose "
            u"target date has arrived; the zero point is linked to an existing "
            u"sample instead. The site wide switch must be on as well."
        ),
        default=False,
        required=False,
    )

    # 客户：**登样时样品登记到哪个委托方名下**（需求确认：维护在方案上，登样时自动带过去）。
    #
    # 为什么必须在方案上维护：样品（AR）只能建在客户容器下、Client 还是必填字段，
    # 而批量/自动登样没有人在界面上点客户 —— 只能从配置取。放在方案上之后，
    # setup 级通用样品模板也能用（不必为每个客户各建一份模板）。
    directives.widget(
        "client",
        UIDReferenceWidgetFactory,
        catalog=CLIENT_CATALOG,
        query={
            "portal_type": "Client",
            "is_active": True,
            "sort_on": "title",
            "sort_order": "ascending",
        },
        display_template="<a href='${url}'>${Title}</a>",
        columns=get_default_columns,
    )
    client = UIDReferenceField(
        title=_(u"Client"),
        description=_(
            u"The client the samples are created for: samples are registered "
            u"under this client. Defaults to the client of the plan template."
        ),
        allowed_types=("Client",),
        multi_valued=False,
        required=False,
    )

    # ⚠️ 联系人查 **CONTACT_CATALOG**（`senaite_catalog_contact`），不是 SETUP_CATALOG：
    #   联系人类型只编目在联系人气目录里，查错目录会**一个都查不到**（下拉框空白）。
    #   见 senaite/core/catalog/__init__.py 的 CATALOG_TYPE_MAPPING
    #   与 bika/lims/content/analysisrequest.py:168（平台自己的 AR「Contact」字段）。
    directives.widget(
        "contact",
        UIDReferenceWidgetFactory,
        catalog=CONTACT_CATALOG,
        query={
            "is_active": True,
            "sort_on": "sortable_title",
            "sort_order": "ascending",
        },
        display_template="<a href='${url}'>${Title}</a>",
        columns=get_default_columns,
    )
    contact = UIDReferenceField(
        title=_(u"Contact"),
        description=_(
            u"Contact person used when samples are created automatically. "
            u"Defaults to the contact of the plan template."
        ),
        allowed_types=("Contact",),
        multi_valued=False,
        required=False,
    )

    title = schema.TextLine(
        title=_(u"Stability Study Name"),
        required=True,
    )

    description = schema.Text(
        title=_(u"Description"),
        required=False,
    )

    directives.mode(plan_id="display")
    directives.mode(IAddForm, plan_id="hidden")
    plan_id = schema.TextLine(
        title=_(u"Stability Study Plan ID"),
        required=False,
        readonly=True,
    )

    # ── 方案状态（阶段 6a）────────────────────────────────────────────────
    #
    # ★ 方案**没有** `status` 字段了：原先那个 Choice（active / inactive）是个
    #   死字段 —— 全代码库没有任何一处读它，界面上也只是只读显示。
    #   现在方案的状态是**工作流状态**（`review_state`）：
    #     in_progress / paused / terminated
    #   定义在 profiles/default/workflows/senaite_stability_plan_workflow/，
    #   绑定见 profiles/default/workflows.xml。
    #
    #   为什么用工作流而不是字段（需求确认稿 C3）：
    #     * 流转自动产生审计快照（动作名 = transition_id，原因进 comments）；
    #     * 权限可按流转配（站点后台可调）；
    #     * review_state 是现成目录索引 —— 列表状态列/状态筛选走平台原生能力。
    #   判据与流转的唯一实现在 maitux.stability.plan_status。
    #
    # 下面三个是**状态变更的留痕字段**。
    #
    # ★ 必须是 schema 字段（不能像明细行的撤销三件套那样用普通属性）：
    #   审计快照的数据来自 SuperModel(obj).to_dict()，它只遍历 **schema 字段** ——
    #   普通属性根本不会进快照，于是"暂停原因"在审计页里就永远看不到。
    #   写成 schema 字段之后，工作流流转拍的那张快照会自动带上它们
    #   （plan_status.change_plan_status 刻意**先写字段再流转**就是为了这个）。
    #
    # 三个字段都是 display（不可编辑）：它们是动作留下的痕迹，不是给人填的表单。
    directives.mode(status_changed_at="display")
    directives.mode(IAddForm, status_changed_at="hidden")
    status_changed_at = schema.TextLine(
        title=_(u"Status Changed At"),
        required=False,
        readonly=True,
    )

    directives.mode(status_changed_by="display")
    directives.mode(IAddForm, status_changed_by="hidden")
    status_changed_by = schema.TextLine(
        title=_(u"Status Changed By"),
        required=False,
        readonly=True,
    )

    directives.mode(status_reason="display")
    directives.mode(IAddForm, status_reason="hidden")
    status_reason = schema.Text(
        title=_(u"Status Change Reason"),
        required=False,
        readonly=True,
    )

    directives.widget(
        "plan_template",
        UIDReferenceWidgetFactory,
        catalog=SETUP_CATALOG,
        query={
            "portal_type": "StabilityPlanTemplate",
            "is_active": True,
            "sort_on": "sortable_title",
            "sort_order": "ascending",
        },
        display_template="<a href='${url}'>${Title}</a>",
        columns=get_default_columns,
    )
    directives.mode(plan_template="hidden")
    plan_template = UIDReferenceField(
        title=_(u"Plan Template"),
        allowed_types=("StabilityPlanTemplate",),
        multi_valued=False,
        required=True,
    )

    start_time = DatetimeField(
        title=_(u"Start Time (T0)"),
        required=True,
    )

    sample_quantity = IntField(
        title=_(u"Storage Quantity - Sampling"),
        required=False,
        default=0,
    )

    reserve_quantity = IntField(
        title=_(u"Storage Quantity - Reserve"),
        required=False,
        default=0,
    )

    directives.mode(total_quantity="display")
    directives.mode(IAddForm, total_quantity="hidden")
    total_quantity = IntField(
        title=_(u"Storage Quantity - Total"),
        required=False,
        default=0,
        readonly=True,
    )

    directives.widget(
        "unit",
        UIDReferenceWidgetFactory,
        catalog=SETUP_CATALOG,
        query={
            "portal_type": "StockUnit",
            "is_active": True,
            "sort_on": "sortable_title",
            "sort_order": "ascending",
        },
        display_template="<a href='${url}'>${Title}</a>",
        columns=get_default_columns,
    )
    unit = UIDReferenceField(
        title=_(u"Unit"),
        allowed_types=("StockUnit",),
        multi_valued=False,
        required=False,
    )

    article = NamedBlobFile(
        title=_(u"Article"),
        required=False,
    )

    directives.widget(
        "plan_details",
        PlanDetailsWidgetFactory,
        allow_insert=True,
        allow_delete=True,
        allow_reorder=True,
        auto_append=False,
    )
    plan_details = DataGridField(
        title=_(u"Plan Details"),
        required=False,
        value_type=DataGridRow(schema=IStabilityPlanDetailSchema),
        default=[],
    )


@implementer(IStabilityPlan, IStabilityPlanSchema, IMultiCatalogBehavior)
class StabilityPlan(TranslatableTitleMixin, Container):
    # ★ `IMultiCatalogBehavior` 必须显式声明（FTI 里声明了也不够，实测新建出来的
    #   对象并不提供该标记）：没有它，senaite 的目录总闸门
    #   `CatalogMultiplexProcessor.supports_multi_catalogs()` 会**静默跳过**索引，
    #   `reindexObject()` 变成空操作 —— 现象就是"方案建出来了，列表里看不到"。
    #   详见 maitux.stability.indexing 的模块说明。
    _catalogs = [SETUP_CATALOG]

    def get_widget_contact_query(self, name=None, widget=None, field=None,
                                 context=None, default=None):
        """联系人下拉**按方案客户过滤**（senaite 的 context 钩子约定）。

        机制：`senaite.core.z3cform.widgets.queryselect.widget.QuerySelectWidget.lookup`
        会先找上下文上的 `get_widget_<字段名>_<属性名>`（全小写）——
        字段名 `contact` + 属性名 `query`，所以这个方法名是它自己拼出来的。

        为什么要过滤：`Contact` 的下拉原本是"全站联系人"，
        而客户是在同一张表单里另选的 —— 站点上 5 个客户各有关联人时，
        很容易选成别家的联系人，结果是"样品挂 A 客户、联系人是 B 家的人"
        （登样那边会报 `PROBLEM_CONTACT_OTHER_CLIENT` 拦下来，
        但用户是**填完才知道**错）。

        客户还没选时返回原查询：客户与联系人在同一张表单里，
        不能因为"暂时没有客户"就把下拉清空（那样用户先选联系人就选不了）。
        """
        query = dict(default or {})
        client_uid = _client_uid_for_filter(self)
        if client_uid:
            query["getParentUID"] = client_uid
        return query

