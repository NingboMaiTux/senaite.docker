# -*- coding: utf-8 -*-
"""Client（委托单位）扩展：新增「自动接收」开关。

放在 Client 上而不是检测部门上，是因为本项目的业务口径就是
「按委托单位区分」：药物分析这个委托单位登样后自动接收，
其他部门 / 稳定性登样后必须先做接收。

实现沿用本项目已验证的 `archetypes.schemaextender` 模式
（与 `INNOCARE.arextension` 扩展 AR 同源）：不动 FTI、不改工作流、
已装站点无数据迁移。
"""

from archetypes.schemaextender.field import ExtensionField
from archetypes.schemaextender.interfaces import IBrowserLayerAwareExtender
from archetypes.schemaextender.interfaces import ISchemaExtender
from bika.lims.interfaces import IClient
from Products.Archetypes.public import BooleanField
from Products.Archetypes.public import BooleanWidget
from zope.component import adapts
from zope.interface import implements

from INNOCARE.autoreceive import _
from INNOCARE.autoreceive.interfaces import IAutoReceiveLayer


class BooleanExtensionField(ExtensionField, BooleanField):
    """扩展字段基类"""


class ClientSchemaExtender(object):
    """给 Client 增加「自动接收」布尔字段"""

    adapts(IClient)
    implements(ISchemaExtender, IBrowserLayerAwareExtender)

    layer = IAutoReceiveLayer

    fields = [
        BooleanExtensionField(
            "AutoReceive",
            required=False,
            schemata="default",
            default=False,
            widget=BooleanWidget(
                label=_(u"Auto Receive Samples"),
                description=_(
                    u"Checked: samples of this client are received "
                    u"automatically when they are registered (the receive "
                    u"step is skipped). Unchecked: samples stay in "
                    u"'Sample due' and must be received manually, so that "
                    u"the receiving user and time are recorded."),
                # ★ 不能加 render_own_label=True：Archetypes 的字段模板据此
                #   「交出标签渲染权」（tal:ifLabel condition="not:
                #   widget/render_own_label"），而 BooleanWidget 的模板
                #   （archetypes/widgets/boolean.pt）自己并不渲染标签 ——
                #   结果是标签与说明都不显示，页面上只剩一个孤立的勾选框。
                #   其他扩展字段用的是会自渲染标签的控件，所以那边可以传 True。
                visible={"edit": "visible", "view": "visible", "add": "edit"},
            ),
        ),
    ]

    def __init__(self, context):
        self.context = context

    def getFields(self):
        return self.fields
