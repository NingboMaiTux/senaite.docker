# -*- coding: utf-8 -*-
from bika.lims.interfaces import IDoNotSupportSnapshots
from plone.supermodel import model
from senaite.core.content.base import Container
from maitux.stability.title import TranslatableTitleMixin
from senaite.core.interfaces import IHideActionsMenu
from senaite.core.interfaces import IMultiCatalogBehavior
from zope.interface import implementer

from maitux.stability.interfaces import IStabilityPlans


class IStabilityPlansSchema(model.Schema):
    pass


@implementer(
    IStabilityPlans,
    IStabilityPlansSchema,
    IDoNotSupportSnapshots,
    IHideActionsMenu,
    # ★ 见 maitux.stability.indexing 的模块说明。
    IMultiCatalogBehavior,
)
class StabilityPlans(TranslatableTitleMixin, Container):
    pass


