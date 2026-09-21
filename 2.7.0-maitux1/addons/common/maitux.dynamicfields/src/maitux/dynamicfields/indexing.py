# -*- coding: utf-8 -*-
"""运行时建 / 删目录索引与 metadata 列

不走 ``catalog.xml``——本包拿不到 profile 执行时机。索引在用户于配置页勾选时
由代码创建，取消勾选或删除字段时同步摘除。

★ 回滚前必须先在配置页上逐个关闭索引开关，否则目录里会留下无人维护的死索引
（见需求文档 §8.4）。
"""
from maitux.dynamicfields import config

try:
    from bika.lims import api
except ImportError:  # pragma: no cover
    api = None

try:
    from senaite.core import logger
except ImportError:  # pragma: no cover
    import logging
    logger = logging.getLogger("maitux.dynamicfields")


#: ZCTextIndex 需要 lexicon，v1 不做；多行文本退回 FieldIndex
_INDEX_FALLBACK = {"ZCTextIndex": "FieldIndex"}


def index_type_for(record):
    index_type = config.DEFAULT_INDEX_TYPES.get(
        record.get("type"), "FieldIndex")
    return _INDEX_FALLBACK.get(index_type, index_type)


def get_catalogs(portal_type):
    """该类型的对象实际落在哪几个目录里

    ``api.get_catalogs_for()`` 要的是对象不是类型名，所以先找一个实例；
    站点里还没有该类型的对象时回落 portal_catalog。
    """
    if api is None:
        return []
    from maitux.dynamicfields import introspect
    instance = introspect._find_instance(portal_type)
    if instance is not None:
        try:
            return list(api.get_catalogs_for(instance))
        except Exception:
            pass
    try:
        return [api.get_tool("portal_catalog")]
    except Exception:
        return []


# --------------------------------------------------------------------------

def ensure_index(record):
    """按记录建 / 删索引与 metadata 列。返回操作日志（给界面显示）"""
    messages = []
    portal_type = record.get("portal_type")
    name = str(record.get("name") or "")
    if not name:
        return messages

    for catalog in get_catalogs(portal_type):
        if catalog is None:
            continue
        catalog_id = getattr(catalog, "getId", lambda: "?")()

        want_index = bool(record.get("index"))
        has_index = name in _index_names(catalog)
        if want_index and not has_index:
            if _add_index(catalog, name, index_type_for(record)):
                messages.append(u"%s：已创建索引 %s" % (catalog_id, name))
        elif not want_index and has_index:
            if _del_index(catalog, name):
                messages.append(u"%s：已移除索引 %s" % (catalog_id, name))

        want_column = bool(record.get("metadata"))
        has_column = name in _column_names(catalog)
        if want_column and not has_column:
            if _add_column(catalog, name):
                messages.append(u"%s：已创建 metadata 列 %s" % (catalog_id, name))
        elif not want_column and has_column:
            if _del_column(catalog, name):
                messages.append(u"%s：已移除 metadata 列 %s" % (catalog_id, name))

    return messages


def drop_index(record):
    """删除字段时把索引和 metadata 一并摘掉，避免留下死索引"""
    stripped = dict(record)
    stripped["index"] = False
    stripped["metadata"] = False
    return ensure_index(stripped)


def reindex(record):
    """对存量数据补索引。长任务——对象多时会明显卡住，界面上要有提示"""
    messages = []
    name = str(record.get("name") or "")
    if not name:
        return messages
    for catalog in get_catalogs(record.get("portal_type")):
        if catalog is None or name not in _index_names(catalog):
            continue
        catalog_id = getattr(catalog, "getId", lambda: "?")()
        try:
            catalog.reindexIndex(name, None)
            messages.append(u"%s：索引 %s 已重建" % (catalog_id, name))
        except Exception:
            logger.exception(
                "maitux.dynamicfields: failed to reindex %s in %s",
                name, catalog_id)
            messages.append(u"%s：索引 %s 重建失败，详见日志" % (catalog_id, name))
    return messages


def index_status(record):
    """当前索引 / metadata 的真实状态（不是配置里的意图），配置页用"""
    name = str(record.get("name") or "")
    indexed = False
    columned = False
    for catalog in get_catalogs(record.get("portal_type")):
        if catalog is None:
            continue
        if name in _index_names(catalog):
            indexed = True
        if name in _column_names(catalog):
            columned = True
    return {"indexed": indexed, "metadata": columned}


# --------------------------------------------------------------------------

def _index_names(catalog):
    try:
        return set(catalog.indexes())
    except Exception:
        return set()


def _column_names(catalog):
    try:
        return set(catalog.schema())
    except Exception:
        return set()


def _add_index(catalog, name, index_type):
    try:
        catalog.addIndex(name, index_type)
        return True
    except Exception:
        logger.exception(
            "maitux.dynamicfields: failed to add index %s (%s)",
            name, index_type)
        return False


def _del_index(catalog, name):
    try:
        catalog.delIndex(name)
        return True
    except Exception:
        logger.exception("maitux.dynamicfields: failed to drop index %s", name)
        return False


def _add_column(catalog, name):
    try:
        catalog.addColumn(name)
        return True
    except Exception:
        logger.exception("maitux.dynamicfields: failed to add column %s", name)
        return False


def _del_column(catalog, name):
    try:
        catalog.delColumn(name)
        return True
    except Exception:
        logger.exception("maitux.dynamicfields: failed to drop column %s", name)
        return False
