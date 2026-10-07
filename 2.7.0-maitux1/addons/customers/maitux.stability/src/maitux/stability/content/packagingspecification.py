# -*- coding: utf-8 -*-
from maitux.stability import stabilityMessageFactory as _
from bika.lims.interfaces import IDeactivable
from plone.supermodel import model
from senaite.core.catalog import SETUP_CATALOG
from senaite.core.content.base import Container
from senaite.core.interfaces import IMultiCatalogBehavior
from zope import schema
from zope.interface import implementer

from maitux.stability.interfaces import IPackagingSpecification


class IPackagingSpecificationSchema(model.Schema):
    title = schema.TextLine(
        title=_(u"Name"),
        required=True,
    )

    description = schema.Text(
        title=_(u"Description"),
        required=False,
    )


@implementer(
    IPackagingSpecification,
    IPackagingSpecificationSchema,
    IDeactivable,
    # ★ 见 maitux.stability.indexing 的模块说明：没有这个标记，
    #   reindexObject() 会被 senaite 的目录总闸门**静默跳过**（什么都不索引）。
    IMultiCatalogBehavior,
)
class PackagingSpecification(Container):
    _catalogs = [SETUP_CATALOG]

