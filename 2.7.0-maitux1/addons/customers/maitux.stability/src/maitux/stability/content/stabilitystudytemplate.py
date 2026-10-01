# -*- coding: utf-8 -*-
from maitux.stability import stabilityMessageFactory as _
from bika.lims import api
from bika.lims.interfaces import IDeactivable
from plone.autoform import directives
from plone.namedfile.field import NamedBlobFile
from plone.supermodel import model
from senaite.core.catalog import CLIENT_CATALOG
from senaite.core.catalog import CONTACT_CATALOG
from senaite.core.catalog import SETUP_CATALOG
from senaite.core.config.widgets import get_default_columns
from senaite.core.content.base import Container
from senaite.core.interfaces import IMultiCatalogBehavior
from senaite.core.schema import IntField
from senaite.core.schema import UIDReferenceField
from senaite.core.z3cform.widgets.uidreference import UIDReferenceWidgetFactory
from persistent.list import PersistentList
from z3c.form.interfaces import IAddForm
from zope import schema
from zope.interface import implementer

from maitux.stability.interfaces import IStabilityPlanTemplate
from maitux.stability.permissions import ManageSampleAutomation


def _client_uid(value):
    """从字段值里取出一个 UID（单元素列表 / 字符串都容忍）。"""
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



class IStabilityStudyTemplateSchema(model.Schema):
    title = schema.TextLine(
        title=_(u"Study Name"),
        required=True,
    )

    description = schema.Text(
        title=_(u"Description"),
        required=False,
    )

    directives.mode(study_plan_id="display")
    directives.mode(IAddForm, study_plan_id="hidden")
    study_plan_id = schema.TextLine(
        title=_(u"Stability Study Plan ID"),
        required=False,
        readonly=True,
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

class IStabilityPlanTemplateSchema(IStabilityStudyTemplateSchema):
    """方案模板 schema：在"研究模板"基础上增加**样品自动化**配置。

    这三项决定"用这个模板建出来的方案，要不要按时间点自动登样、联系谁、
    样品登记到哪个客户名下"。站点级的生成时刻/提前天数/零点窗口
    在 @@stability-automation-controlpanel（见 maitux.stability.automation）。

    ⚠️ **样品模板不在本模板上**（2026-09-29 需求订正）：不同时间点要验的东西
    不一样，所以样品模板**逐个时间点维护在方案明细行上**
    （`IStabilityPlanDetailSchema.sample_template`）。
    """

    model.fieldset(
        "sample_automation",
        label=_(u"Sample Automation"),
        fields=[
            "auto_create_samples",
            "client",
            "contact",
        ],
    )

    directives.write_permission(auto_create_samples=ManageSampleAutomation)
    auto_create_samples = schema.Bool(
        title=_(u"Create samples automatically"),
        description=_(
            u"Plans created from this template inherit this switch. When it is "
            u"on, samples are created for every timepoint whose target date has "
            u"arrived; the zero point is not created but linked to an existing "
            u"sample. Needs the site wide switch to be on as well."
        ),
        default=False,
        required=False,
    )

    # 客户：本模板给出的**默认客户**（建方案时带入，方案上可改）。
    # 登样时样品登记到哪个委托方名下，以**方案上**的客户为准 ——
    # 这里只是省得每个方案都手选一次。见 maitux.stability.automation.get_client()。
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
            u"Default client for plans created from this template. The samples "
            u"are registered under the client configured on the plan."
        ),
        allowed_types=("Client",),
        multi_valued=False,
        required=False,
    )

    # ⚠️ 联系人必须查 **CONTACT_CATALOG**（`senaite_catalog_contact`）。
    #   联系人类型（Contact / LabContact / SupplierContact）只编目在联系人气目录里，
    #   查 SETUP_CATALOG 会**一个都查不到** -> 下拉框空白（阶段 1 就是这么写错的）。
    #   依据：senaite/core/catalog/__init__.py 的 CATALOG_TYPE_MAPPING
    #   `("Contact", [CONTACT_CATALOG])`；平台自己的 AR「Contact」字段也是这个目录
    #   （bika/lims/content/analysisrequest.py:168）。
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
            u"A plan may override it."
        ),
        allowed_types=("Contact",),
        multi_valued=False,
        required=False,
    )


@implementer(IStabilityPlanTemplate, IStabilityPlanTemplateSchema, IDeactivable,
             IMultiCatalogBehavior)
class StabilityPlanTemplate(Container):
    _catalogs = [SETUP_CATALOG]

    def get_widget_contact_query(self, name=None, widget=None, field=None,
                                 context=None, default=None):
        """联系人下拉**按模板客户过滤**（同 `StabilityPlan` 的同名钩子）。

        机制见 `senaite.core.z3cform.widgets.queryselect.widget.QuerySelectWidget.lookup`
        的约定：上下文上定义 `get_widget_<字段名>_<属性名>` 即可覆盖该属性。
        模板是客户/联系人的**源头**，新方案的联系人默认从这里带过去 ——
        模板上错了，之后每个新方案都跟着错。
        """
        query = dict(default or {})
        uid = _client_uid(getattr(self, "client", None))
        if uid:
            query["getParentUID"] = uid
        return query

    def _ensure_ordering(self):
        for name in ("_ordering", "_order"):
            if getattr(self, name, None) is None:
                try:
                    setattr(self, name, PersistentList())
                except Exception:
                    pass

    def __contains__(self, name):
        self._ensure_ordering()
        try:
            return super(StabilityPlanTemplate, self).__contains__(name)
        except TypeError:
            try:
                return self._getOb(name, default=None) is not None
            except Exception:
                return False

