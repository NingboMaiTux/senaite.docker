# -*- coding: utf-8 -*-
u"""S6：把兜底文件里的行补录进流水表。

兜底文件由 `journal._fallback_write()` 在"PG 写不进去"时产生，每行一条 JSON。
本模块把它们读回来、灌进表、归档。

★★ 本片的核心难点：**兜底文件里的 DSN 是脱敏的。** ★★

  `_fallback_write` 只写 `mask_dsn()` 的结果（形如 `lims_db#7234f519`），
  因为完整 DSN 带明文口令，落到文件里就多一处泄露面（CLAUDE.md §8.7）。
  所以补录必须**按掩码反查真实 DSN**。

  做法：把当前进程能拿到的候选 DSN 各算一次 `mask_dsn()`，建
  `{掩码: 真实DSN}` 映射，再按行里的掩码查。

  **反查不到就不写，绝不猜。** 一客户一库形态下猜错的后果是
  **把 A 客户的审计行写进 B 客户的库** —— 那比"暂时补不上"严重得多。
  查不到的行原样留在文件里，报数给人看。

★ 归档时机：**只有整份文件都处理干净了才归档。**
  只要还有一行没写进去（DSN 反查失败 / 数据库写失败），就**不归档** ——
  Runbook §4.1 写的"补录仍失败不要删兜底文件，它是唯一的暂存"就是这个意思。
  损坏行是例外：它本来就永远写不进去，不该无限期挡住归档，
  所以按"已处理"计，但会单独报数并原样抄进归档文件旁的 `.bad` 里。
"""

import io
import json
import logging
import os
import time

from . import db
from . import journal

logger = logging.getLogger("maitux.auditjournal")

#: 一次最多灌多少行。与回填同理：文件可能很大，不能一次性全读进内存。
DEFAULT_BATCH_SIZE = 500


def _candidate_dsns(portal):
    u"""收集本进程能拿到的候选 DSN，返回 {掩码: 真实 DSN}。

    来源两处，都不含猜测成分：
      * 当前站点所在的库（`db.dsn_for(portal)`）；
      * zope.conf 里根库的 dsn。
    多库形态下若某个客户库不在其中，那一批行就反查不到 —— **这是对的**，
    补录应该在对应站点上跑，而不是在别处替它写。
    """
    mapping = {}
    for dsn in (db.dsn_for(portal), db.dsn_from_zope_conf()):
        if dsn:
            mapping.setdefault(db.mask_dsn(dsn), dsn)
    return mapping


def _parse_line(line, lineno):
    u"""一行 JSON -> (行字典, 掩码 DSN)。解析不出来返回 (None, None)。"""
    try:
        record = json.loads(line)
    except Exception:
        logger.warning(u"auditjournal: 兜底文件第 %d 行不是合法 JSON，跳过",
                       lineno)
        return None, None
    if not isinstance(record, dict):
        logger.warning(u"auditjournal: 兜底文件第 %d 行不是对象，跳过", lineno)
        return None, None
    mask = record.pop("dsn", None)
    if not mask:
        logger.warning(u"auditjournal: 兜底文件第 %d 行没有 dsn 字段，跳过",
                       lineno)
        return None, None
    # 缺必填列的行写进去也会被 NOT NULL 挡回来，提前判掉，报数更准
    for column in ("site_path", "ts", "actor", "portal_type", "uid",
                   "snapshot_ver"):
        if record.get(column) in (None, u""):
            logger.warning(u"auditjournal: 兜底文件第 %d 行缺 %s，跳过",
                           lineno, column)
            return None, None
    return record, mask


def _archive_path(path):
    u"""归档名。判据要求 `.done`；已存在就加序号，不覆盖旧的归档。"""
    target = path + ".done"
    if not os.path.exists(target):
        return target
    for n in range(2, 1000):
        candidate = u"%s.done.%d" % (path, n)
        if not os.path.exists(candidate):
            return candidate
    return u"%s.done.%d" % (path, int(time.time()))


def replay_fallback(portal, dry_run=True, batch_size=DEFAULT_BATCH_SIZE,
                    path=None, progress=None, archive=None):
    u"""把兜底文件灌回表。

    :param dry_run: True 只解析统计，不写库也不归档
    :param path: 指定文件；缺省用 `journal.FALLBACK_PATH`
    :param archive: 是否归档。**缺省 None = 自动**：只有处理的是当前那份
        兜底文件才归档；显式传了 `path` 就不归档。

        ★ 为什么这么定（2026-09-01 实测踩到）：运维用 `path=` 指到某个
          `.done` 归档文件去核查"这些行到底进没进库"是**正常操作**，
          结果第一版把人家的归档又改了一次名，落成 `.done.done`。
          **核查动作不该改动被核查的文件。** 归档只对"活的"兜底文件有意义。
    :return: 统计 dict
    """
    started = time.time()
    explicit_path = bool(path)
    path = path or journal.FALLBACK_PATH
    if archive is None:
        archive = not explicit_path
    stats = {
        "path": path,
        "lines": 0,          # 文件总行数（空行不算）
        "parsed": 0,         # 解析成功的
        "corrupt": 0,        # 损坏/缺字段，永远写不进去
        "unresolved": 0,     # DSN 掩码反查不到
        "written": 0,
        "skipped": 0,        # 已存在，被唯一索引挡下
        "failed": 0,         # 数据库写失败
        "archived_to": None,
        "dry_run": bool(dry_run),
    }

    def emit(msg):
        logger.warning(u"auditjournal: %s", msg)
        if progress is not None:
            try:
                progress(msg)
            except Exception:
                logger.exception(u"auditjournal: progress 回调失败")

    if not os.path.exists(path):
        emit(u"兜底文件不存在：%s —— 没有需要补录的东西（这是正常状态）" % path)
        return stats

    dsn_map = _candidate_dsns(portal)
    emit(u"可反查的 DSN 掩码：%s"
         % (u"、".join(sorted(dsn_map.keys())) or u"（一个都没有）"))

    pending = []          # [(掩码, 行)]
    corrupt_lines = []    # 原样留存，写进 .bad

    def flush(rows):
        u"""按掩码分组写库。返回是否全部成功。"""
        ok_all = True
        groups = {}
        for mask, row in rows:
            groups.setdefault(mask, []).append(row)
        for mask, group in groups.items():
            dsn = dsn_map.get(mask)
            if not dsn:
                # ★ 反查不到就不写。绝不拿"另一个库"顶上（见模块注释）
                stats["unresolved"] += len(group)
                ok_all = False
                emit(u"DSN 掩码 %s 反查不到，%d 行**未写入**（请在对应站点上补录）"
                     % (mask, len(group)))
                continue
            if dry_run:
                continue
            if not db.ensure_schema(dsn):
                stats["failed"] += len(group)
                ok_all = False
                emit(u"建表失败 dsn=%s，%d 行未写入" % (db.mask_dsn(dsn),
                                                      len(group)))
                continue
            ok, inserted = db.insert_rows(dsn, group)
            if ok:
                stats["written"] += inserted
                stats["skipped"] += len(group) - inserted
            else:
                stats["failed"] += len(group)
                ok_all = False
        return ok_all

    all_ok = True
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line:
                continue
            stats["lines"] += 1
            record, mask = _parse_line(line, lineno)
            if record is None:
                # 损坏行：单独报数，其余照灌（判据④）
                stats["corrupt"] += 1
                corrupt_lines.append(raw)
                continue
            stats["parsed"] += 1
            pending.append((mask, record))
            if len(pending) >= batch_size:
                all_ok = flush(pending) and all_ok
                pending = []
                emit(u"已处理 %d 行：写入 %d / 跳过 %d / 损坏 %d / "
                     u"反查不到 %d / 失败 %d"
                     % (stats["lines"], stats["written"], stats["skipped"],
                        stats["corrupt"], stats["unresolved"], stats["failed"]))
    if pending:
        all_ok = flush(pending) and all_ok

    # ---- 归档 ----
    # 损坏行不算"没处理完"：它们永远写不进去，不该无限期挡住归档。
    # 但反查不到 / 写失败的行必须留着重来（Runbook §4.1）。
    if dry_run:
        emit(u"演练结束，未写库也未归档")
    elif not archive:
        emit(u"指定了 path，按核查模式处理：**不归档、不改动该文件**")
    elif not all_ok:
        emit(u"**不归档** —— 还有 %d 行未写入（反查不到 %d / 写失败 %d）。"
             u"兜底文件是唯一暂存，先解决问题再重跑"
             % (stats["unresolved"] + stats["failed"],
                stats["unresolved"], stats["failed"]))
    else:
        target = _archive_path(path)
        try:
            os.rename(path, target)
            stats["archived_to"] = target
            emit(u"已归档为 %s" % target)
            if corrupt_lines:
                bad = target + u".bad"
                # ★ 必须 0600，和兜底文件一样严。
                #   坏行里同样可能带业务字段（对象标题等），不该比它来源的
                #   文件更开放。2026-09-01 首次实测时这里用了 io.open 默认权限，
                #   落成 0644 —— 兜底文件是 0600，归档 rename 也保住了 0600，
                #   唯独这个副产品漏了。
                fd = os.open(bad, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                try:
                    os.write(fd, u"".join(corrupt_lines).encode("utf-8"))
                finally:
                    os.close(fd)
                emit(u"%d 行损坏，原样留在 %s（0600）供人工判断"
                     % (len(corrupt_lines), bad))
        except Exception:
            logger.exception(u"auditjournal: 归档失败 %s", path)
            emit(u"归档失败（行已写入，文件仍在原处）——"
                 u"手工改名即可，重跑也不会产生重复行")

    stats["elapsed"] = round(time.time() - started, 2)
    emit(u"补录结束（%s）：共 %d 行，写入 %d / 跳过 %d / 损坏 %d / "
         u"反查不到 %d / 失败 %d，耗时 %.2fs"
         % (u"演练" if dry_run else u"已写库", stats["lines"],
            stats["written"], stats["skipped"], stats["corrupt"],
            stats["unresolved"], stats["failed"], stats["elapsed"]))
    return stats
