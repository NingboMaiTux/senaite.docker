# -*- coding: utf-8 -*-
u"""S6 的触发入口：兜底补录视图。

复用 S5 那套：Manager 权限、默认 dry_run、纯文本输出、同样的内容进日志。
权限也复用 `MAITUX: Backfill Audit Journal` —— 补录和回填是同一类动作
（往审计表写历史行），没必要再拆一个权限、再加一次 profile 升级。
"""

import logging

from .. import replay
from .backfill_view import _as_bool, _as_int

logger = logging.getLogger("maitux.auditjournal")


class ReplayView(object):
    u"""`/<site>/@@audit-journal-replay`

    参数：
      dry_run=0        真写库（缺省是 1，只解析统计）
      batch_size=500   每批灌多少行
      path=/...        指定兜底文件（缺省用 journal.FALLBACK_PATH）。
                       ★ 指定了 path = **核查模式**，不归档、不改动该文件
      archive=1        强制归档（即使指定了 path）
    """

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        form = self.request.form or {}
        dry_run = _as_bool(form.get("dry_run"), True)
        batch_size = _as_int(form.get("batch_size"),
                             replay.DEFAULT_BATCH_SIZE)
        path = form.get("path") or None
        if isinstance(path, bytes):
            path = path.decode("utf-8", "replace")

        lines = []

        def progress(message):
            lines.append(message)

        logger.warning(u"auditjournal: 补录被触发 dry_run=%s batch_size=%s "
                       "path=%s", dry_run, batch_size, path)
        # archive 缺省跟随 path：指定了 path 就是核查模式，不归档。
        # 显式 archive=1 才强制归档。
        archive = None
        if form.get("archive") is not None:
            archive = _as_bool(form.get("archive"), True)
        stats = replay.replay_fallback(
            self.context, dry_run=dry_run, batch_size=batch_size,
            path=path, progress=progress, archive=archive)

        header = [
            u"maitux.auditjournal — 兜底补录（S6）",
            u"=" * 60,
            u"模式        : %s" % (u"演练（dry_run，不写库不归档）"
                                   if stats["dry_run"] else u"真写库"),
            u"兜底文件    : %s" % stats["path"],
            u"",
            u"文件行数    : %d" % stats["lines"],
            u"解析成功    : %d" % stats["parsed"],
            u"写入        : %d 行" % stats["written"],
            u"跳过        : %d 行（已存在，唯一索引挡下）" % stats["skipped"],
            u"损坏        : %d 行（永远写不进去，已单独留存）" % stats["corrupt"],
            u"DSN 反查不到: %d 行（**未写入**，留在文件里）" % stats["unresolved"],
            u"写库失败    : %d 行" % stats["failed"],
            u"归档        : %s" % (stats["archived_to"] or u"（未归档）"),
            u"耗时        : %.2fs" % stats.get("elapsed", 0.0),
            u"",
            u"-- 过程 " + u"-" * 52,
        ]
        if stats["dry_run"]:
            header.insert(4, u"★ 这是演练。真写库请加 ?dry_run=0")

        body = u"\n".join(header + lines) + u"\n"
        self.request.response.setHeader("Content-Type",
                                        "text/plain; charset=utf-8")
        return body.encode("utf-8")
