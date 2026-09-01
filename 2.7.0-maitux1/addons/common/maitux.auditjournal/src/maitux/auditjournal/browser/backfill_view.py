# -*- coding: utf-8 -*-
u"""S5 的触发入口：受权限保护、在实例进程内执行的回填视图。

★ 为什么必须是视图而不是脚本：`bin/instance run` 会起第二个 Zope 进程，
  两个一起撞容器 1024MB 上限被 SIGKILL，**把正在跑的实例一起干掉**
  （CLAUDE.md §10）。回填只能在已经跑着的实例进程里做。

★ 为什么默认 dry_run：回填是**写操作**，且一次可能写几万行。默认演练、
  必须显式加 `dry_run=0` 才真写，是为了让"手滑访问一下 URL"不产生后果。

★ 输出用纯文本：这是管理工具，判据要的是可读的计数（"已扫描 N 个对象、
  写入 M 行、跳过 K 行、错误 E"），纯文本最容易在命令行里核对，
  也免去一套模板。同样的内容同时进日志。
"""

import logging

from .. import backfill

logger = logging.getLogger("maitux.auditjournal")


def _as_bool(value, default):
    u"""表单里拿到的是字符串，'0' / 'false' / 'no' 都当假。

    ★ 不要写成 `unicode(value)`：表单值是字节串，用户塞个 `?dry_run=中文`
      就是 `UnicodeDecodeError`（Py2 隐式按 ASCII 解）。这里显式按 UTF-8 解、
      解不动就替换 —— 一个开关参数不值得为它抛异常，但也不能静默当成真
      （那会让"手滑"变成真写库）。
    """
    if value is None:
        return default
    if isinstance(value, bytes):
        text = value.decode("utf-8", "replace")
    else:
        text = u"%s" % (value,)
    text = text.strip().lower()
    if text in (u"0", u"false", u"no", u"off", u""):
        return False
    return True


def _as_int(value, default):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


class BackfillView(object):
    u"""`/<site>/@@audit-journal-backfill`

    参数：
      dry_run=0        真写库（缺省是 1，只演练）
      batch_size=200   每批处理多少个对象
      limit=N          调试用。每个 catalog 各取前 N 个，不是全局前 N
    """

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        form = self.request.form or {}

        # ?probe=1 —— 只做诊断，不回填。用来回答"该扫哪些 catalog"，
        # 这个问题从实例外面探测不出来（匿名请求量到的是可见性，不是内容）。
        if _as_bool(form.get("probe"), False):
            lines = backfill.probe_catalogs(self.context)
            body = u"\n".join(
                [u"maitux.auditjournal — catalog 诊断（只读，不写库）",
                 u"=" * 78, u""] + lines) + u"\n"
            self.request.response.setHeader("Content-Type",
                                            "text/plain; charset=utf-8")
            return body.encode("utf-8")

        dry_run = _as_bool(form.get("dry_run"), True)
        batch_size = _as_int(form.get("batch_size"),
                             backfill.DEFAULT_BATCH_SIZE)
        limit = _as_int(form.get("limit"), 0) or None

        lines = []

        def progress(message):
            lines.append(message)

        logger.warning(u"auditjournal: 回填被触发 dry_run=%s batch_size=%s "
                       "limit=%s", dry_run, batch_size, limit)
        stats = backfill.backfill_from_zodb(
            self.context, dry_run=dry_run, batch_size=batch_size,
            limit=limit, progress=progress)

        header = [
            u"maitux.auditjournal — ZODB 全量回填（S5）",
            u"=" * 60,
            u"模式        : %s" % (u"演练（dry_run，未写库）" if stats["dry_run"]
                                   else u"真写库"),
            u"批大小      : %d 个对象/批，共 %d 批" % (batch_size,
                                                      stats["batches"]),
            u"",
            u"已扫描      : %d 个对象" % stats["scanned"],
            u"其中有快照  : %d 个" % stats["with_snapshots"],
            u"候选行      : %d" % stats["candidates"],
            u"写入        : %d 行" % stats["written"],
            u"跳过        : %d 行（已存在，唯一索引挡下）" % stats["skipped"],
            u"错误        : %d" % stats["errors"],
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
