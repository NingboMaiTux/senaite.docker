# -*- coding: utf-8 -*-
from plone.supermodel import model
from senaite.core.content.base import Container
from maitux.stock.title import TranslatableTitleMixin
from zope.interface import implementer

from maitux.stock.interfaces import IStockSection


class IStockSectionSchema(model.Schema):
    pass


@implementer(IStockSection, IStockSectionSchema)
class StockSection(TranslatableTitleMixin, Container):
    pass

