# -*- coding: utf-8 -*-
"""把对象**真的**编进它该进的目录。

★ 为什么需要这个模块（2026-09-29 真机事故：用户新建的方案"看不到"）

senaite 的 `senaite.core.catalog.catalog_multiplex_processor.CatalogMultiplexProcessor`
是所有目录索引的总闸门，它第一件事就是：

    def supports_multi_catalogs(self, obj):
        if api.is_temporary(obj):
            return False
        if api.is_dexterity_content(obj) and IMultiCatalogBehavior(obj, None) is None:
            return False
        return True

拿不到 `IMultiCatalogBehavior` 标记就**直接 return、什么都不索引**，
而且**不报错、不写日志** —— 于是 `obj.reindexObject()` 成了一个静默空操作。

本包的类型虽然在自己的 FTI 里声明了这个行为（`types/*.xml` 的
`bika.lims.interfaces.IMultiCatalogBehavior`），实测新建出来的对象
**并不提供**该标记（同 FTI 里声明的 `IAutoGenerateID` 却是生效的，
所以编号正常、编目不正常）；对照 senaite 自带的 `SampleTemplate`
是提供的 —— `IMultiCatalogBehavior.providedBy(obj)` 为 True。

后果（真机现象）：

* 方案/时间点任务 `uid_catalog` 里有、`senaite_catalog_setup` 里**没有**；
* 方案列表、"登样"看板、REST 搜索全都查不到 —— 建出来的数据像丢了；
* 而且**只在某些建法上出现**：新建方案时明细行里带时间点（生成任务发生在
  `ObjectAddedEvent` 内部）的那几次没进目录，先建空方案再补明细的那几次进了。

本模块做两件事，缺一不可：

1. `mark_indexable()`：给对象补上 `IMultiCatalogBehavior` 标记，
   让平台的常规路径（`reindexObject()`、升级脚本、表单保存）恢复作用；
2. `ensure_indexed()`：**不信** `reindexObject()` 是否被上面那道门拦掉，
   直接点名对象该进的每个目录做 `catalog_object`。

调用点是"我们自己创建/更新方案与时间点任务"的地方，见
`subscribers.py` 与 `samplegeneration.py`。
"""

from bika.lims import api
from senaite.core import logger
from senaite.core.interfaces import IMultiCatalogBehavior
from zope.interface import alsoProvides


try:  # py2 / py3 兼容（本环境是 py2.7，但这几个自检脚本会用 py3 读同一个文件）
    unicode  # noqa: F821
except NameError:                                    # pragma: no cover
    unicode = str


UID_CATALOG = "uid_catalog"

# 标题归一化的字段名（dexterity 的 `title` 与 Archetypes 的 `Title()` 都覆盖到）
TITLE_FIELDS = ("title",)


def normalize_title_encoding(obj):
    """把**字节串**标题归一成 unicode（幂等；返回是否改过）。

    ★ 为什么必须做（2026-09-30 真机）：`uid_catalog` 是 Archetypes 的老目录，它把标题
    拆成关键字存进一个 BTree；只要索引里**既有 UTF-8 字节串键、又有 unicode 键**，
    py2 在比较键时会拿 ascii 去解码字节串，于是**任何中文标题**的编目都可能抛
    `UnicodeDecodeError: 'ascii' codec can't decode byte 0xe6 in position N`。
    实测：站点上界面建的中文标题方案（字节键）与程序化建的方案（unicode 标题）
    混在一起就炸；ASCII 标题永远不会。

    归一成 unicode 后，我们这一侧不会再往那个索引里塞字节键。
    """
    if obj is None:
        return False
    changed = False
    for name in TITLE_FIELDS:
        value = getattr(obj, name, None)
        if isinstance(value, str) and not isinstance(value, unicode):
            try:
                setattr(obj, name, value.decode("utf-8"))
                changed = True
            except Exception:
                logger.exception(
                    "Failed to normalize the %r of %r to unicode", name, obj)
    if changed:
        try:
            obj._p_changed = True
        except Exception:
            pass
    return changed


# 老索引的已知故障：`uid_catalog` 的 Title 关键字索引在"字节键 + unicode 键混装"时
# 会抛 UnicodeDecodeError。它**不影响功能**（实测：`uid_catalog(UID=...)`、
# `api.get_object_by_uid()`、`senaite_catalog_setup` 三条解析路径都正常，
# 只是那个 Title 关键字索引里少一条），所以这里降级成 WARNING 说清楚，
# 不再往日志里写一整段 ERROR + traceback（GMP 场景下日志噪音会淹掉真错误）。
LEGACY_TITLE_INDEX_HINT = (
    "object %s was NOT added to the legacy 'Title' keyword index of 'uid_catalog' "
    "(mixed str/unicode keys in that index make py2 fail with UnicodeDecodeError). "
    "This does not affect UID resolution. Run "
    "tools/repair_uid_catalog_title.py to normalize that index."
)


def is_legacy_title_index_failure(catalog_id, exc):
    return (catalog_id == UID_CATALOG
            and isinstance(exc, (UnicodeDecodeError, UnicodeError)))


def mark_indexable(obj):
    """给对象补上 ``IMultiCatalogBehavior`` 标记（幂等）。

    返回本次是否真的补上了。补上之后 ``reindexObject()`` 才不是空操作。
    """
    if obj is None:
        return False
    try:
        if IMultiCatalogBehavior.providedBy(obj):
            return False
        alsoProvides(obj, IMultiCatalogBehavior)
        obj._p_changed = True
        return True
    except Exception:
        logger.exception("Failed to mark object as indexable: %r", obj)
        return False


def target_catalogs(obj):
    """对象该进的目录 id 列表（总是包含 ``uid_catalog``）。"""
    ids = []
    try:
        ids.extend([catalog.id for catalog in
                    api.get_catalogs_for(api.get_portal_type(obj))])
    except Exception:
        logger.exception(
            "Failed to resolve catalogs for portal_type %r",
            getattr(obj, "portal_type", None))
    if UID_CATALOG not in ids:
        ids.append(UID_CATALOG)
    return ids


def ensure_indexed(obj, catalogs=None):
    """把 ``obj`` 编进它该进的每个目录，返回成功的目录 id 列表。

    幂等；单个目录失败只记日志，不打断调用方（编目失败不该让业务动作失败）。
    """
    if obj is None:
        return []
    # 先把字节串标题归一成 unicode：否则 `uid_catalog` 的遗留 Title 索引会炸
    # （见 normalize_title_encoding 的说明）。
    normalize_title_encoding(obj)
    mark_indexable(obj)

    path = None
    try:
        path = api.get_path(obj)
    except Exception:
        logger.exception("Failed to resolve path of %r for cataloguing", obj)
        return []

    done = []
    for catalog_id in (catalogs or target_catalogs(obj)):
        try:
            tool = api.get_tool(catalog_id)
        except Exception:
            tool = None
        if tool is None:
            continue
        try:
            tool.catalog_object(obj, path)
            done.append(catalog_id)
        except Exception as exc:
            if is_legacy_title_index_failure(catalog_id, exc):
                # 已知的遗留索引问题：降级成 WARNING + 一句话说明（不写 traceback）
                logger.warning(LEGACY_TITLE_INDEX_HINT, path)
                continue
            logger.exception("Failed to catalog %s in %s", path, catalog_id)
    return done
