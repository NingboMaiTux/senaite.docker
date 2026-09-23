# -*- coding: utf-8 -*-
from bika.lims.interfaces import IDoNotSupportSnapshots
from plone.supermodel import model
from senaite.core.content.base import Container
from maitux.stability.title import TranslatableTitleMixin
from senaite.core.interfaces import IHideActionsMenu
from zope.interface import implementer

from maitux.stability.interfaces import IPackagingSpecifications


class IPackagingSpecificationsSchema(model.Schema):
    pass


@implementer(
    IPackagingSpecifications,
    IPackagingSpecificationsSchema,
    IDoNotSupportSnapshots,
    IHideActionsMenu,
)
class PackagingSpecifications(TranslatableTitleMixin, Container):
    pass

