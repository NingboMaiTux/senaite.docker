# -*- coding: utf-8 -*-
"""样品（AnalysisRequest）扩展：只读的「接收人」展示字段。

SENAITE 原生把接收人存在工作流历史里（`ReceivedBy` 计算字段），
widget 是 `ComputedWidget(visible=False)` —— 界面上看不到。
这里补一个只在 view 模式可见的展示字段，取值实时计算，不落库。

字段显隐仍走 SENAITE 原生的 Manage Sample Form Fields 配置：
`ManageSampleFieldsView.get_configuration()` 会把新出现的字段自动并入
standard_fields，所以安装后无需手工配置即可显示。
"""

from archetypes.schemaextender.field import ExtensionField
from archetypes.schemaextender.interfaces import IBrowserLayerAwareExtender
from archetypes.schemaextender.interfaces import ISchemaExtender
from bika.lims.interfaces import IAnalysisRequest
from Products.Archetypes.public import StringField
from Products.Archetypes.public import StringWidget
from zope.component import adapts
from zope.interface import implements

from INNOCARE.autoreceive import _
from INNOCARE.autoreceive.interfaces import IAutoReceiveLayer
from INNOCARE.autoreceive.utils import get_received_by_fullname


class ReceivedByNameField(ExtensionField, StringField):
    """只读展示字段：接收人全名。

    覆写 `get()`（与 `senaite.core.extender.label.ExtLabelField` 同一手法），
    值每次实时计算，不写入对象；因为 edit/add 模式不可见，
    保存链路也不会去 `set()` 它。
    """

    def get(self, instance, **kwargs):
        return get_received_by_fullname(instance)


class ARSchemaExtender(object):
    """给样品增加「接收人」展示字段"""

    adapts(IAnalysisRequest)
    implements(ISchemaExtender, IBrowserLayerAwareExtender)

    layer = IAutoReceiveLayer

    fields = [
        ReceivedByNameField(
            "ReceivedByName",
            required=False,
            schemata="default",
            widget=StringWidget(
                label=_(u"Received By"),
                description=_(u"User who received this sample"),
                visible={
                    "edit": "invisible",
                    "view": "visible",
                    "add": "invisible",
                },
                render_own_label=True,
            ),
        ),
    ]

    def __init__(self, context):
        self.context = context

    def getFields(self):
        return self.fields
