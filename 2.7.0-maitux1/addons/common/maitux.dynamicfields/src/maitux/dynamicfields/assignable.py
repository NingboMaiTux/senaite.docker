# -*- coding: utf-8 -*-
"""把动态 schema 挂到 Dexterity 对象上，全程不写 FTI

``plone:behavior`` 的 ``for`` 只决定"工厂适配器适用于哪个类型"，真正决定
behavior 在对象上启不启用的是 ``IBehaviorAssignable``。SENAITE 的那些 FTI 在
senaite.core 里改不了，而本包又拿不到 profile 去调 ``enable_behavior``——所以
按 INNOCARE.labid 的同一套路注册一个 ``IBehaviorAssignable``：先枚举 FTI 上已
登记的 behavior，再追加本包的动态 schema。

★ 已知边界：别的 add-on 若为**更具体的接口**注册了自己的 IBehaviorAssignable
（INNOCARE.labid 就是 ``@adapter(ILaboratory)``），zope 会挑更具体的那个，
本包在该类型上会被**整个旁路掉**。配置页用 ``is_assignable_active()`` 实测并
给出告警，不让它静默丢字段。
"""
from plone.behavior.interfaces import IBehaviorAssignable
from plone.behavior.registration import BehaviorRegistration
from zope.component import adapter
from zope.interface import implementer

from maitux.dynamicfields import dxschema

try:
    from plone.dexterity.behavior import DexterityBehaviorAssignable
    from plone.dexterity.interfaces import IDexterityContent
except ImportError:  # pragma: no cover
    DexterityBehaviorAssignable = object
    IDexterityContent = None

try:
    from senaite.core import logger
except ImportError:  # pragma: no cover
    import logging
    logger = logging.getLogger("maitux.dynamicfields")


BEHAVIOR_TITLE = "MAITUX Dynamic Fields"
BEHAVIOR_DESCRIPTION = (
    "Custom fields configured through the Dynamic Fields control panel")


@implementer(IBehaviorAssignable)
@adapter(IDexterityContent)
class DynamicFieldsAssignable(DexterityBehaviorAssignable):
    """给任意 Dexterity 对象追加本包的动态 schema"""

    def enumerateBehaviors(self):
        for behavior in super(DynamicFieldsAssignable, self).enumerateBehaviors():
            yield behavior
        registration = self.dynamic_registration
        if registration is not None:
            yield registration

    @property
    def dynamic_registration(self):
        try:
            portal_type = getattr(self.context, "portal_type", None)
            if not portal_type:
                return None
            schema = dxschema.get_schema(portal_type)
            if schema is None:
                return None
            return BehaviorRegistration(
                title=BEHAVIOR_TITLE,
                description=BEHAVIOR_DESCRIPTION,
                interface=schema,
                # 不设 marker：动态 schema 每次重建都是新接口对象，
                # 给对象打 marker 会在数据库里留下指向已消失接口的引用
                marker=None,
                factory=dxschema.DynamicFieldsBehavior,
            )
        except Exception:
            # NFR-1：枚举 behavior 是渲染必经之路，这里抛异常等于整站白屏
            logger.exception(
                "maitux.dynamicfields: failed to build behavior registration")
            return None


def is_assignable_active(instance):
    """实测本包的 assignable 在这个对象上有没有生效

    返回 True / False / None（判定不了）。配置页用它给告警——别的 add-on 注册
    了更具体的 IBehaviorAssignable 时，本包会被静默旁路，必须让人看得见。
    """
    if instance is None:
        return None
    try:
        assignable = IBehaviorAssignable(instance, None)
    except Exception:
        return None
    if assignable is None:
        return None
    return isinstance(assignable, DynamicFieldsAssignable)
