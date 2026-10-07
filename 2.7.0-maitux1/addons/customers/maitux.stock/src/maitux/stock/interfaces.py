# -*- coding: utf-8 -*-
from zope.interface import Interface

class IStockFolder(Interface):
    """Marker interface for Stock Folder
    """

class IStockItem(Interface):
    """Marker interface for Stock Items
    """


class IStock(Interface):
    """Marker interface for Stock
    """


class IStockManager(Interface):
    """Marker interface for Stock Manager
    """


class IStockSection(Interface):
    """Marker interface for Stock Section
    """


class IStockUnits(Interface):
    """Marker interface for Stock Units
    """


class IStockUnit(Interface):
    """Marker interface for Stock Unit
    """


class IStockTypes(Interface):
    """Marker interface for Stock Types
    """


class IStockType(Interface):
    """Marker interface for Stock Type
    """


class IStockPurchaseOrders(Interface):
    """Marker interface for Stock Purchase Orders
    """


class IStockPurchaseOrder(Interface):
    """Marker interface for Stock Purchase Order
    """


class IStockBatches(Interface):
    """Marker interface for Stock Batches
    """


class IStockBatch(Interface):
    """Marker interface for Stock Batch
    """


class IStockUsageRequests(Interface):
    """Marker interface for the Stock Usage Requests container

    领用申请单目录（stockmanager/usage_requests）
    """


class IStockUsageRequest(Interface):
    """Marker interface for a Stock Usage Request (领用申请单)

    需要双人电子签名的库存，领用时不再直接扣减，而是走：
        发起领用（申请人电子签名）-> 审核领用（非申请人电子签名）-> 自动扣减
    """
