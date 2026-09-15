# -*- coding: utf-8 -*-
"""把 Lab ID behavior 动态挂到 Laboratory 上。

``plone:behavior`` 的 ``for`` 只决定"工厂适配器适用于哪个类型"，并不会让
behavior 在对象上启用 —— 启用与否由 ``IBehaviorAssignable`` 决定，而
Laboratory 的 FTI 在 senaite.core 里（不能改）。因此这里按 senaite.core
给 Dexterity 内容追加 labels 字段的同一套路，注册一个针对 ``ILaboratory``
的 ``IBehaviorAssignable``：先枚举 FTI 已注册的 behavior，再追加 Lab ID
behavior。
"""
from plone.behavior.interfaces import IBehaviorAssignable
from plone.behavior.registration import BehaviorRegistration
from plone.dexterity.behavior import DexterityBehaviorAssignable
from zope.component import adapter
from zope.interface import implementer

from senaite.core.interfaces import ILaboratory

from INNOCARE.labid.behaviors import ILabIDSchema
from INNOCARE.labid.behaviors import LabIDSchema
from INNOCARE.labid.interfaces import ILabIDMarker

# 本 add-on 的 layer（default profile 的 browserlayer.xml 注册）。
# R14：本 adapter 指向外来内容接口（ILaboratory）且签名里没有 request，
# ZCML 无处插 layer，只能在工厂里做运行时门控。
_LAYER_ID = "INNOCARE.labid.interfaces.ILabIDLayer"


def _is_enabled():
    """当前站点是否已安装本 add-on。

    layer 已注册 => 启用；站点存在但 layer 未注册 => 未安装，保持原生行为。
    与 INNOCARE.arextension 的同类判断保持一致：无法判定（无站点/异常）时
    保守视为启用，避免运维期静默丢失字段。
    """
    try:
        from zope.component.hooks import getSite
        from plone.browserlayer import utils as layer_utils
        site = getSite()
        if site is None:
            return True
        for layer in layer_utils.registered_layers():
            if getattr(layer, "__identifier__", None) == _LAYER_ID:
                return True
        return False
    except Exception:
        return True


@implementer(IBehaviorAssignable)
@adapter(ILaboratory)
class LabIDBehaviorAssignable(DexterityBehaviorAssignable):
    """为 Laboratory 追加 Lab ID behavior
    """

    def enumerateBehaviors(self):
        for behavior in super(LabIDBehaviorAssignable, self).enumerateBehaviors():
            yield behavior
        if _is_enabled():
            yield self.labid_registration

    @property
    def labid_registration(self):
        return BehaviorRegistration(
            title="Lab ID",
            description="Adds a Lab ID field to the Laboratory",
            interface=ILabIDSchema,
            marker=ILabIDMarker,
            factory=LabIDSchema,
        )
