# -*- coding: utf-8 -*-
u"""S5：把 ZODB 里已有的历史快照灌进流水表。

**为什么能做到高保真**：快照自带完整元数据（`bika/lims/api/snapshot.py`
的 `get_object_metadata`）——`actor` / `roles` / `action` / `review_state` /
`snapshot_created` / `remote_address` 全都存着。所以回填出来的行与实时记录
的行**字段完全一样**，不是降级版本。

★ 三条硬约束，写之前先看清楚：

1. **绝不能用 `bin/instance run` 跑**（CLAUDE.md §10）。那会起第二个 Zope
   进程，两个一起撞容器 1024MB 上限被 SIGKILL，**把正在跑的实例一起干掉**。
   本模块只经由 `browser/backfill_view.py` 那个受权限保护的视图，在实例
   进程内执行。

2. **必须分批，且每批独立提交。** 本机数据量太小（快照千级），一次性
   全 load 也跑得过去，**恰恰因此测不出规模问题**。生产库跑一两年后几万条
   快照，一次遍历就可能撞内存上限 —— 那时候是"回填工具自己在生产上跑挂"。
   每批之间调 `cacheGC()` 让 ZODB 缓存能被回收，是分批的真正意义所在
   （光切片不回收缓存，内存照样一路涨）。

3. **重跑必须不产生重复行。** 靠唯一索引
   `(site_path, uid, snapshot_ver)` + `db.insert_rows()` 的
   `ON CONFLICT DO NOTHING`。每批独立提交带来的另一个好处：中途被打断，
   已完成的批次留在库里，重跑时它们变成 skipped，从断点继续。

★ 行映射**刻意复用 `journal._build_row`**（同包私有函数）。不另写一套是
  因为两套映射一定会漂开 —— 而漂开的症状是"回填的行和实时的行字段不一致"，
  这种问题很难被发现。回填传显式 `version`，实时不传，区别只在这一个参数。

★★ 回填能重建什么、**不能**重建什么（2026-09-01 实测确认）★★

  能重建：当前仍存在的对象的**全部**历史快照。字段与实时记录完全一致。

  **不能重建：已删除对象留下的孤儿行。**
  对象一删，它的快照随 annotation 一起消失，**那段历史此刻只存在于流水表里**。
  所以 Runbook §5.1 原来那句「权威记录在 SENAITE 对象里，流水表只是索引」
  **对孤儿行不成立** —— 对孤儿行而言，流水表就是唯一的权威记录。

  实测：`/Care` 回填候选 725 行，但表里有 727 行。多出的 2 行是一个被删掉的
  Analysis（`/Care/clients/client-1/S-0002/Clos`，create + initialize），
  正是技术设计 §5.3 方案 D 说的孤儿行。**任何重建都拿不回它们。**

  **后果**：先 `TRUNCATE` 再回填 = 永久销毁孤儿行，而且**销毁得静默** ——
  重建报告照样显示"错误 0"。所以：
    * 回填**只增不删**，本模块永远不发 DELETE / TRUNCATE；
    * 表损坏时的首选恢复手段是**整库备份恢复**（Runbook §5.3），不是重建；
    * 重建只用于"补历史"，不能当作"恢复"。
"""

import logging
import time

from . import db
from . import journal

logger = logging.getLogger("maitux.auditjournal")

#: 每批处理多少个**对象**（不是行）。200 是这么定的：一个对象平均几条快照，
#: 200 个对象约几百到上千行，与 `insert_rows` 的 `page_size=200` 同量级；
#: 同时 200 个被唤醒的 ZODB 对象占用远低于容器上限，每批 cacheGC 后能回落。
DEFAULT_BATCH_SIZE = 200

#: senaite.core 自己的审计日志 catalog。
#: ★ **不要拿它当"可审计对象全集"** —— 2026-09-01 实测它只有 173 个对象，
#:   而下面五个加起来 547（未去重）。它更像是"启用审计日志之后被记录过的
#:   那一批"，不是全集。第一版设计成"优先用它、有它就不扫别的"，
#:   结果只会回填三分之一，且看不出少了。
#:   现在它只是清单里的**普通一员**，靠路径去重与其它 catalog 合并。
AUDITLOG_CATALOG = "senaite_catalog_auditlog"

#: 扫描范围（判据②要求"扫描范围显式列出，含 Analysis"）。
#: ★ 一律不用 `portal_catalog` —— 它对 Analysis 返回 0，是本环境的已知陷阱。
#: 括号里是 2026-09-01 本机实测的对象数，供下次对照；数量级差太多就该查。
SCAN_CATALOGS = (
    # Analysis 占全部快照的 85–93%，漏了它等于没回填
    ("senaite_catalog_analysis",
     u"Analysis / DuplicateAnalysis / ReferenceAnalysis / RejectAnalysis"),
    ("senaite_catalog_sample", u"AnalysisRequest"),
    ("senaite_catalog_worksheet", u"Worksheet"),
    ("senaite_catalog_setup", u"AnalysisService / SampleType / 其余 setup 项"),
    ("senaite_catalog_client", u"Client"),
    (AUDITLOG_CATALOG, u"审计日志 catalog（补漏用，与上面重叠的靠路径去重）"),
)

#: 兼容旧名字：早期版本叫 FALLBACK_CATALOGS，probe 里还引用着
FALLBACK_CATALOGS = SCAN_CATALOGS


def _get_catalog(portal, name):
    u"""拿 catalog 工具；不存在返回 None（不同 SENAITE 版本 catalog 会变）。"""
    tool = getattr(portal, name, None)
    if tool is None:
        return None
    if not hasattr(tool, "unrestrictedSearchResults"):
        logger.warning(u"auditjournal: %s 不是可搜索的 catalog，跳过", name)
        return None
    return tool


def _catalog_size(catalog):
    u"""catalog 里索引了多少个对象。取不到返回 None（当作"未知"，不当作 0）。"""
    try:
        return int(len(catalog))
    except Exception:
        try:
            return len(catalog.unrestrictedSearchResults())
        except Exception:
            logger.exception(u"auditjournal: 数不出 catalog 大小")
            return None


def resolve_scan_plan(portal):
    u"""决定扫哪些 catalog。返回 [(catalog 名, 说明, catalog 对象)]。

    判据②要求扫描范围显式可见，所以这里把结果原样返回给调用方打印，
    不在内部悄悄决定。

    ★ **没有"首选 catalog"这回事，全部都扫、按路径去重。**（2026-09-01 定）

      早先设计成"优先用 senaite_catalog_auditlog，它是可审计对象全集，
      有它就不扫别的"。实测两处都不成立：

      1. 它只有 173 个对象，而其余五个加起来 547（未去重）——**不是全集**；
      2. 中间还错判过一版"它是空的"，那是因为无参搜索返回 0
         （见 `_iter_paths` 的注释），不是真空。

      两个错误叠加的后果是"只回填三分之一，而且报告全绿"。现在不做取舍，
      六个 catalog 全扫、靠路径 set 去重 —— 多扫的代价只是几百次
      catalog 查询，比漏掉历史便宜得多。
    """
    plan = []
    for name, desc in SCAN_CATALOGS:
        cat = _get_catalog(portal, name)
        if cat is None:
            logger.warning(u"auditjournal: catalog %s 不存在，跳过", name)
            continue
        plan.append((name, desc, cat))
    return plan


def _iter_paths(catalog, site_path):
    u"""只取路径，不持有 brain —— brain 也占内存，几万个不容忽视。

    ★★ `unrestrictedSearchResults()` **必须带查询条件**，无参调用返回 0。★★

    2026-09-01 在实例内实测六个 catalog，无一例外：

        catalog                     len   无参搜索  带path搜索
        senaite_catalog_auditlog    173      0        173
        senaite_catalog_analysis    168      0        168
        senaite_catalog_sample       47      0         47
        senaite_catalog_worksheet    16      0         16
        senaite_catalog_setup       311      0        311
        senaite_catalog_client        5      0          5

    这是 SENAITE catalog 的**通用行为**，不是某个 catalog 坏了。
    第一版写成无参调用，症状是"扫描 0 个对象、错误 0"——**全绿但什么都没干**，
    正是 R9 说的静默失败。诊断入口 `?probe=1` 就是为查清这件事加的，留着。
    """
    return [b.getPath() for b in catalog.unrestrictedSearchResults(
        path={"query": site_path, "level": 0})]


def probe_catalogs(portal):
    u"""诊断：把每个候选 catalog 的真实情况打出来，供人判断该扫哪些。

    ★ 为什么需要它：2026-09-01 实测到
      `senaite_catalog_auditlog` 的 `len()` 是 173、但无参
      `unrestrictedSearchResults()` 返回 0。两个数对不上，光看回填结果
      （"扫描 0 个对象、错误 0"）只会得出"一切正常"的错误结论。
      隔着权限从外面探测也没用 —— 匿名请求量到的是"匿名可见性"，不是
      catalog 内容。所以诊断必须跑在实例内、Manager 权限下。

    :return: 文本行列表
    """
    from bika.lims.api import snapshot as snapshot_api

    lines = []
    names = [n for n, _d in SCAN_CATALOGS]
    for name in names:
        cat = getattr(portal, name, None)
        if cat is None:
            lines.append(u"%-30s 不存在" % name)
            continue

        size = _catalog_size(cat)

        # 无参搜索
        try:
            bare = len(cat.unrestrictedSearchResults())
            bare_txt = u"%d" % bare
        except Exception as exc:
            bare = 0
            bare_txt = u"异常 %s" % (exc,)

        # 带 path 查询的搜索 —— 有些 catalog 无参不给结果，给条件就给
        try:
            site_path = u"/".join(portal.getPhysicalPath())
            with_path = len(cat.unrestrictedSearchResults(
                path={"query": site_path, "level": 0}))
            path_txt = u"%d" % with_path
        except Exception as exc:
            with_path = 0
            path_txt = u"异常 %s" % (exc,)

        # 直接读 catalog 内部的 path 映射 —— 绕开一切查询语义
        try:
            internal = list(cat._catalog.paths.values())
            internal_txt = u"%d" % len(internal)
        except Exception as exc:
            internal = []
            internal_txt = u"异常 %s" % (exc,)

        # 抽样看有没有快照
        sample_with_snap = 0
        sample_total = 0
        for path in internal[:20]:
            sample_total += 1
            try:
                obj = portal.unrestrictedTraverse(str(path), None)
                if obj is not None and snapshot_api.has_snapshots(obj):
                    sample_with_snap += 1
            except Exception:
                logger.exception(u"auditjournal: probe 取对象失败 %s", path)

        lines.append(
            u"%-30s len=%-8s 无参搜索=%-10s 带path搜索=%-10s "
            u"内部paths=%-8s 抽样%d个中有快照=%d"
            % (name, size, bare_txt, path_txt, internal_txt,
               sample_total, sample_with_snap))
        if internal[:3]:
            lines.append(u"%-30s 样例：%s"
                         % (u"", u", ".join(str(p) for p in internal[:3])))
    return lines


def _rows_for_object(obj):
    u"""一个对象的全部历史快照 -> 行列表。"""
    from bika.lims.api import snapshot as snapshot_api

    if not snapshot_api.has_snapshots(obj):
        return []
    rows = []
    # ★ 版本号就是快照在列表里的下标（0 起）—— S1 实测：首条快照
    #   Version 0 / Action Create，与 UI 的 Audit Log 页签一致。
    #   用 enumerate 而不是 get_snapshot_version()：后者是 list.index()，
    #   逐条调用就是 O(n²)。
    for version, snap in enumerate(snapshot_api.get_snapshots(obj)):
        rows.append(journal._build_row(obj, snap, version=version))
    return rows


def _cache_gc(portal):
    u"""每批之后回收 ZODB 对象缓存 —— 分批的意义在这里，不在切片本身。"""
    try:
        jar = getattr(portal, "_p_jar", None)
        if jar is not None:
            jar.cacheGC()
    except Exception:
        # 回收失败不该中断回填，但必须留痕（R9：不许静默吞）
        logger.exception(u"auditjournal: cacheGC 失败，继续但内存可能上涨")


def backfill_from_zodb(portal, dry_run=True, batch_size=DEFAULT_BATCH_SIZE,
                       limit=None, progress=None):
    u"""把历史快照回填进流水表。

    :param portal: 站点根对象
    :param dry_run: True 只统计不写（判据⑥）
    :param batch_size: 每批处理多少个对象
    :param limit: 调试用。★ 是**每个 catalog 各取前 N 个**，不是全局前 N ——
        实测 limit=10 会扫到 31 个对象（六个 catalog 各取一截）。
        None = 全部
    :param progress: 可选回调 `f(unicode)`，每批一行，用于把进度同时送到
        HTTP 响应里（判据①要求"打印…且同时进日志"）
    :return: 统计 dict
    """
    started = time.time()
    stats = {
        "scanned": 0,        # 扫过的对象数
        "with_snapshots": 0,  # 其中真有快照的
        "candidates": 0,     # 构造出来的行数
        "written": 0,        # 真正插进去的
        "skipped": 0,        # 已存在被 ON CONFLICT 跳过的
        "errors": 0,
        "batches": 0,
        "dry_run": bool(dry_run),
        "catalogs": [],
    }

    def emit(msg):
        logger.warning("auditjournal: %s", msg)
        if progress is not None:
            try:
                progress(msg)
            except Exception:
                logger.exception(u"auditjournal: progress 回调失败")

    plan = resolve_scan_plan(portal)
    if not plan:
        emit(u"没有可扫描的 catalog，什么都没做 —— 请检查 SENAITE 版本")
        return stats

    for name, desc, cat in plan:
        # ★ 把对象数一起打出来。第一版只打名字，结果 catalog 是空的也看不出来，
        #   白跑一轮才发现（2026-09-01）。范围可见 ≠ 只写名字。
        size = _catalog_size(cat)
        stats["catalogs"].append({"name": name, "desc": desc, "size": size})
        emit(u"扫描范围：%s（%s 个对象）—— %s"
             % (name, u"未知" if size is None else size, desc))

    # catalog 查询必须带 path 条件，无参返回 0（见 _iter_paths 注释）
    site_path = u"/".join(portal.getPhysicalPath())

    # ★ 跨 catalog 去重：清单里多个 catalog 会索引同一个对象
    #   （比如 AnalysisRequest 同时在 sample 和 auditlog 里）。不去重的话
    #   `已扫描` 会重复计数，`跳过` 也会虚高 —— 数字失真比慢更糟，
    #   因为判据是靠这些数字判成败的。
    seen_paths = set()

    for name, _desc, catalog in plan:
        paths = [p for p in _iter_paths(catalog, site_path)
                 if p not in seen_paths]
        seen_paths.update(paths)
        if limit is not None:
            paths = paths[:limit]
        emit(u"%s：%d 个对象待处理（去重后），每批 %d"
             % (name, len(paths), batch_size))

        for start in range(0, len(paths), batch_size):
            chunk = paths[start:start + batch_size]
            stats["batches"] += 1
            batch_rows = []

            for path in chunk:
                stats["scanned"] += 1
                try:
                    obj = portal.unrestrictedTraverse(path, None)
                    if obj is None:
                        continue
                    rows = _rows_for_object(obj)
                    if not rows:
                        continue
                    stats["with_snapshots"] += 1
                    dsn = db.dsn_for(obj)
                    if not dsn:
                        stats["errors"] += 1
                        logger.error(u"auditjournal: 回填拿不到 DSN，path=%s",
                                     path)
                        continue
                    for row in rows:
                        row["_dsn"] = dsn
                    batch_rows.extend(rows)
                except Exception:
                    stats["errors"] += 1
                    # R9：不许静默吞 —— 单个对象失败不该中断整次回填，但必须留痕
                    logger.exception(u"auditjournal: 回填单个对象失败 path=%s",
                                     path)

            stats["candidates"] += len(batch_rows)

            if not dry_run and batch_rows:
                groups = {}
                for row in batch_rows:
                    groups.setdefault(row.pop("_dsn"), []).append(row)
                for dsn, group in groups.items():
                    if not db.ensure_schema(dsn):
                        stats["errors"] += len(group)
                        logger.error(u"auditjournal: 回填建表失败 dsn=%s，"
                                     u"本批 %d 行未写入",
                                     db.mask_dsn(dsn), len(group))
                        continue
                    ok, inserted = db.insert_rows(dsn, group)
                    if ok:
                        stats["written"] += inserted
                        stats["skipped"] += len(group) - inserted
                    else:
                        stats["errors"] += len(group)

            _cache_gc(portal)
            emit(u"第 %d 批完成：累计 扫描 %d / 有快照 %d / 候选行 %d / "
                 u"写入 %d / 跳过 %d / 错误 %d"
                 % (stats["batches"], stats["scanned"],
                    stats["with_snapshots"], stats["candidates"],
                    stats["written"], stats["skipped"], stats["errors"]))

    stats["elapsed"] = round(time.time() - started, 2)
    emit(u"回填结束（%s）：已扫描 %d 个对象、写入 %d 行、跳过 %d 行、错误 %d，"
         u"耗时 %.2fs"
         % (u"演练，未写库" if dry_run else u"已写库",
            stats["scanned"], stats["written"], stats["skipped"],
            stats["errors"], stats["elapsed"]))
    return stats
