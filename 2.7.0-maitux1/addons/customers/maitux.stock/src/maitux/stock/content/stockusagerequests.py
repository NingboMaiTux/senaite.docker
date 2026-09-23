# -*- coding: utf-8 -*-
from plone.supermodel import model
from senaite.core.content.base import Container
from maitux.stock.title import TranslatableTitleMixin
from zope.interface import implementer

from maitux.stock.interfaces import IStockUsageRequests


class IStockUsageRequestsSchema(model.Schema):
    pass


@implementer(IStockUsageRequests, IStockUsageRequestsSchema)
class StockUsageRequests(TranslatableTitleMixin, Container):
    """领用申请单目录（section 型节点）。"""
