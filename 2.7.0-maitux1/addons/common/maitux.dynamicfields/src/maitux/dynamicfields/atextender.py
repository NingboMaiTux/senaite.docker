# -*- coding: utf-8 -*-
"""Archetypes 侧：按配置动态返回扩展字段

``archetypes.schemaextender`` 本来就是为运行时插字段设计的，把
``INNOCARE.arextension`` 里那个写死的 ``fields = [...]`` 换成按配置构造即可。

缓存说明：schemaextender 自己的缓存**挂在 request 对象上**
（``CACHE_KEY = '__archetypes_schemaextender_cache'``），跨请求不保留，
所以配置改完下一个请求就生效，没有需要显式失效的持久缓存。
本模块另外按 (portal_type, 配置版本号) 缓存字段对象，省得同一请求里
每个对象都重建一遍。

★ 本 adapter 适配所有 AT 对象，是**每请求每对象**都会走到的热路径——
``getFields()` 必须是一次字典查找，配置里没有的类型立刻返回 []。
"""
from zope.component import adapter
from zope.interface import implementer

from maitux.dynamicfields import atfields
from maitux.dynamicfields import storage

try:
    from archetypes.schemaextender.interfaces import IBrowserLayerAwareExtender
    from archetypes.schemaextender.interfaces import ISchemaExtender
    from Products.Archetypes.interfaces import IBaseObject
    HAVE_AT = True
except ImportError:  # pragma: no cover
    HAVE_AT = False
    ISchemaExtender = None
    IBaseObject = None

try:
    from senaite.core import logger
except ImportError:  # pragma: no cover
    import logging
    logger = logging.getLogger("maitux.dynamicfields")


#: {portal_type: (revision, [field, ...])}
_FIELD_CACHE = {}


def get_fields(portal_type):
    """该类型的 AT 扩展字段列表；没配过返回 []"""
    if not portal_type:
        return []
    try:
        revision = storage.get_revision()
    except Exception:
        return []

    cached = _FIELD_CACHE.get(portal_type)
    if cached is not None and cached[0] == revision:
        return cached[1]

    fields = []
    try:
        for record in storage.get_records_for_type(portal_type):
            try:
                field = atfields.build_field(record)
            except Exception:
                # 单条脏配置只跳过自己，不连累同类型的其它字段
                logger.exception(
                    "maitux.dynamicfields: skipping bad AT field %r on %s",
                    record.get("name"), portal_type)
                continue
            if field is not None:
                fields.append(field)
    except Exception:
        # NFR-1：getFields 抛异常会让该对象的每一个页面 500
        logger.exception(
            "maitux.dynamicfields: failed to build AT fields for %s",
            portal_type)
        fields = []

    _FIELD_CACHE[portal_type] = (revision, fields)
    return fields


def invalidate(portal_type=None):
    if portal_type is None:
        _FIELD_CACHE.clear()
    else:
        _FIELD_CACHE.pop(portal_type, None)


if HAVE_AT:

    @implementer(ISchemaExtender)
    @adapter(IBaseObject)
    class DynamicFieldsExtender(object):
        """给任意 AT 对象追加配置里的字段"""

        def __init__(self, context):
            self.context = context

        def getFields(self):
            portal_type = getattr(self.context, "portal_type", None)
            if not portal_type:
                return []
            return get_fields(portal_type)

else:  # pragma: no cover

    class DynamicFieldsExtender(object):
        def __init__(self, context):
            self.context = context

        def getFields(self):
            return []
