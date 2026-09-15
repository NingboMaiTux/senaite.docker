# -*- coding: utf-8 -*-
import logging
log = logging.getLogger("INNOCARE.arextension")
log.info("LOADING AREXTENSION MODULE")
from bika.lims.interfaces import IAnalysisRequest
from zope.component import adapts
from zope.interface import implements
from archetypes.schemaextender.interfaces import IBrowserLayerAwareExtender
from archetypes.schemaextender.field import ExtensionField
from archetypes.schemaextender.interfaces import ISchemaExtender
from archetypes.schemaextender.interfaces import ISchemaModifier
from Products.Archetypes.public import StringField
from Products.Archetypes.public import DateTimeField
from Products.Archetypes.public import TextField
from Products.Archetypes.public import StringWidget
from Products.Archetypes.public import TextAreaWidget
from Products.Archetypes.public import SelectionWidget
from Products.Archetypes.public import DisplayList
from bika.lims.browser.widgets import DateTimeWidget
from bika.lims.browser.fields import UIDReferenceField
from senaite.core.browser.widgets.referencewidget import ReferenceWidget
from senaite.core.catalog import SETUP_CATALOG
from zope.publisher.interfaces.browser import IDefaultBrowserLayer

from INNOCARE.arextension import _


class IARExtensionLayer(IDefaultBrowserLayer):
    pass

class StringExtensionField(ExtensionField, StringField):
    pass

class DateTimeExtensionField(ExtensionField, DateTimeField):
    pass

class TextExtensionField(ExtensionField, TextField):
    pass

class UIDReferenceExtensionField(ExtensionField, UIDReferenceField):
    pass

class ARSchemaExtender(object):
    adapts(IAnalysisRequest)
    implements(ISchemaExtender, IBrowserLayerAwareExtender)
    layer = IARExtensionLayer

    fields = [
        UIDReferenceExtensionField(
            "ProjectNo",
            required=False,
            searchable=True,
            schemata="default",
            allowed_types=("Project",),
            multiValued=False,
            widget=ReferenceWidget(
                label=_(u"Project", default=u"Project"),
                # 关联项目：按项目 ID 选择
                # （说明写入注释，不在界面上显示括号备注）
                description=u"",
                catalog="portal_catalog",
                                # R12：base_query 是类级共享 dict，get_query() 会原地
                # update(query) —— 不显式给本实例一个独占 dict，下面的键
                # 就会污染整个进程里所有 ReferenceWidget。同时也让本控件
                # 免疫别处（含 senaite.core 那 63 处）泼过来的键。
                base_query={},
                query={
                    "portal_type": "Project",
                    "sort_on": "sortable_title",
                    "sort_order": "ascending",
                },
                visible={'edit': 'visible', 'view': 'visible', 'add': 'edit'},
                render_own_label=True,
            ),
        ),
        StringExtensionField(
            "MaterialCode",
            required=False,
            searchable=True,
            schemata="default",
            widget=StringWidget(
                label=_(u"Material Code"),
                description=_(u"Material Code"),
                visible={'edit': 'visible', 'view': 'visible', 'add': 'edit'},
                render_own_label=True,
            ),
        ),
        StringExtensionField(
            "MaterialName",
            required=True,
            searchable=True,
            schemata="default",
            widget=StringWidget(
                label=_(u"Material Name"),
                description=_(u"Material Name"),
                visible={'edit': 'visible', 'view': 'visible', 'add': 'edit'},
                render_own_label=True,
            ),
        ),
        StringExtensionField(
            "Strength",
            required=False,
            searchable=True,
            schemata="default",
            widget=StringWidget(
                label=_(u"Strength"),
                description=_(u"Strength / Specification"),
                visible={'edit': 'visible', 'view': 'visible', 'add': 'edit'},
                render_own_label=True,
            ),
        ),
        DateTimeExtensionField(
            "ManufactureDate",
            required=False,
            schemata="default",
            widget=DateTimeWidget(
                label=_(u"Manufacture Date"),
                description=_(u"Manufacture Date"),
                show_time=False,
                visible={'edit': 'visible', 'view': 'visible', 'add': 'edit'},
                render_own_label=True,
            ),
        ),
        StringExtensionField(
            "Quantity",
            required=False,
            searchable=True,
            schemata="default",
            widget=StringWidget(
                label=_(u"Quantity"),
                description=_(u"Quantity"),
                visible={'edit': 'visible', 'view': 'visible', 'add': 'edit'},
                render_own_label=True,
            ),
        ),
        StringExtensionField(
            "Unit",
            required=False,
            searchable=True,
            schemata="default",
            widget=StringWidget(
                label=_(u"Unit"),
                description=_(u"Unit"),
                visible={'edit': 'visible', 'view': 'visible', 'add': 'edit'},
                render_own_label=True,
            ),
        ),
        UIDReferenceExtensionField(
            "SampleStatus",
            required=False,
            searchable=True,
            schemata="default",
            allowed_types=("SampleMatrix",),
            multiValued=False,
            widget=ReferenceWidget(
                label=_(u"Sample Status", default=u"Sample Status"),
                # 样品基体：从 SampleMatrices 维护列表选择
                # （说明写入注释，不在界面上显示括号备注）
                description=u"",
                catalog=SETUP_CATALOG,
                                # R12：base_query 是类级共享 dict，get_query() 会原地
                # update(query) —— 不显式给本实例一个独占 dict，下面的键
                # 就会污染整个进程里所有 ReferenceWidget。同时也让本控件
                # 免疫别处（含 senaite.core 那 63 处）泼过来的键。
                base_query={},
                query={
                    "portal_type": "SampleMatrix",
                    "sort_on": "sortable_title",
                    "sort_order": "ascending",
                },
                visible={'edit': 'visible', 'view': 'visible', 'add': 'edit'},
                render_own_label=True,
            ),
        ),
        UIDReferenceExtensionField(
            "StorageConditions",
            required=False,
            searchable=True,
            schemata="default",
            allowed_types=("SamplePreservation", "StorageCondition", "SampleCondition"),
            multiValued=False,
            widget=ReferenceWidget(
                label=_(u"Storage Conditions", default=u"Storage Conditions"),
                # 样品基体储存条件：从 SamplePreservations 维护列表选择
                # （说明写入注释，不在界面上显示括号备注）
                description=u"",
                catalog=SETUP_CATALOG,
                                # R12：base_query 是类级共享 dict，get_query() 会原地
                # update(query) —— 不显式给本实例一个独占 dict，下面的键
                # 就会污染整个进程里所有 ReferenceWidget。同时也让本控件
                # 免疫别处（含 senaite.core 那 63 处）泼过来的键。
                base_query={},
                query={
                    "portal_type": (
                        "SamplePreservation",
                        "StorageCondition",
                        "SampleCondition",
                    ),
                    "sort_on": "sortable_title",
                    "sort_order": "ascending",
                },
                visible={'edit': 'visible', 'view': 'visible', 'add': 'edit'},
                render_own_label=True,
            ),
        ),
        UIDReferenceExtensionField(
            "SampleProperties",
            required=False,
            searchable=True,
            schemata="default",
            allowed_types=("HazardCategory",),
            multiValued=1,
            # 样品性质：多选，仅包含 both + AR only 范围
            # （说明写入注释，不在界面上显示括号备注）
            widget=ReferenceWidget(
                label=_(u"Sample Properties", default=u"Sample Properties"),
                description=u"",
                catalog=SETUP_CATALOG,
                # ★ base_query 必须显式给一个本实例独占的 dict，别用类级默认值。
                # senaite.core 的 ReferenceWidget._properties["base_query"] 是
                # 一个**类级共享的可变 dict**（Archetypes 的 _process_args 只做
                # self.__dict__.update(self._properties) 浅拷贝），而
                # referencewidget.py 的 get_query() 拿到它以后直接
                # base_query.update(query) **原地改**。
                # 于是本字段的 query 一旦渲染过一次非拷贝的原始 widget（打开任意
                # 样品的 view / base_edit 就会），下面的 usage_scope 就会永久污染
                # 整个 Zope 进程里所有 ReferenceWidget 的 base_query。
                # 后果：usage_scope 是本 addon 自己往 senaite_catalog_setup 加的
                # KeywordIndex（见 setuphandlers.ensure_setup_catalog_usage_scope_index），
                # SampleType / SampleTemplate / Client 等类型没有这个属性、不进
                # 索引，被污染后样品登记页的引用控件一个都搜不出来。
                # 传 base_query={} 后 kwargs 覆盖类级默认值，update 只改本实例。
                base_query={},
                query={
                    "portal_type": "HazardCategory",
                    "usage_scope": [u"both", u"ar", u"ar_only"],
                    "sort_on": "sortable_title",
                    "sort_order": "ascending",
                },
                visible={'edit': 'visible', 'view': 'visible', 'add': 'edit'},
                render_own_label=True,
            ),
        ),
        StringExtensionField(
            "SampleRetainer",
            required=False,
            searchable=True,
            schemata="default",
            widget=StringWidget(
                label=_(u"Sample Retainer"),
                description=_(u"Sample Retainer"),
                visible={'edit': 'visible', 'view': 'visible', 'add': 'edit'},
                render_own_label=True,
            ),
        ),
        DateTimeExtensionField(
            "RetentionTime",
            required=False,
            schemata="default",
            widget=DateTimeWidget(
                label=_(u"Retention Time"),
                description=_(u"Retention Time"),
                show_time=False,
                visible={'edit': 'visible', 'view': 'visible', 'add': 'edit'},
                render_own_label=True,
            ),
        ),
        StringExtensionField(
            "SampleRecovery",
            required=False,
            searchable=True,
            vocabulary=DisplayList([
                ("yes", u"是"),
                ("no", u"否"),
            ]),
            schemata="default",
            widget=SelectionWidget(
                format='select',
                label=_(u"Sample Recovery"),
                description=_(u"Sample Recovery Description"),
                visible={'edit': 'visible', 'view': 'visible', 'add': 'edit'},
                render_own_label=True,
            ),
        ),
        TextExtensionField(
            "SafetyPrecautions",
            required=False,
            searchable=True,
            schemata="default",
            widget=TextAreaWidget(
                label=_(u"Safety Precautions"),
                description=_(u"Safety Precautions or Comments"),
                visible={'edit': 'visible', 'view': 'visible', 'add': 'edit'},
                render_own_label=True,
            ),
        ),
    ]

    def __init__(self, context):
        self.context = context

    def getFields(self):
        return self.fields

class ARSchemaModifier(object):
    adapts(IAnalysisRequest)
    implements(ISchemaModifier, IBrowserLayerAwareExtender)
    layer = IARExtensionLayer

    def __init__(self, context):
        self.context = context

    def fiddle(self, schema):
        # 不再硬编码隐藏任何原生字段。字段显隐交由 SENAITE 原生的
        # Manage Sample Form Fields 手工配置（存 ZODB，跨容器重启持久化）。

        if "ClientReference" in schema:
            schema["ClientReference"].widget.label = _(u"Batch No")
            schema["ClientReference"].widget.description = _(u"Batch No")
        if "Contact" in schema:
            schema["Contact"].widget.label = _(u"Applicant")
            schema["Contact"].widget.description = _(u"Applicant / Contact")
        if "StorageLocation" in schema:
            schema["StorageLocation"].widget.label = _(u"Reserved Position")
            schema["StorageLocation"].widget.description = _(u"Reserved Position")
