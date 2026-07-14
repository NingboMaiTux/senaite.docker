# -*- coding: utf-8 -*-
from zope.interface import Interface


class ISmartSearchLayer(Interface):
    """浏览器层标记接口 —— 用于让"智慧搜索"只在启用了本插件的站点上
    加载对应的视图 / viewlet。"""
