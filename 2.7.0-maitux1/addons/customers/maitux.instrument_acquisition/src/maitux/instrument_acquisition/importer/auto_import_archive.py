# -*- coding: utf-8 -*-
"""自动导入（目录 → `@@auto_import_results`）的失败归档

SENAITE 原生的 `AutoImportResultsView.import_results()` 跑完 importer 之后会
**无条件**把文件名写进 `imported.csv`（`write_imported_file`），于是：

- 解析失败 / 落位被闸门拦下 / 正文里没有 WorkSheet 编号的文件**永远不会重试**
  （下次跑自动导入时按"已导入"跳过）；
- 目录里只留一条 `logs.log`，人得自己看出"这份没进去"。

本项目要的是"**失败移入 `failed/` 子目录、不记账、可重投**"，所以这里对
`write_imported_file` 加一层**极薄的包装**，只介入我们自己的失败：

1. 本插件的导入器（`importer/instrumentacquisition.py`）每次跑完把结果记进
   **本模块的线程局部**（`remember_outcome`）；
2. 包装器发现"刚跑完的正是这份文件、且失败了" → **不写 `imported.csv`**、
   把文件移到 `<folder>/failed/<name>`（重名加时间戳前缀，不覆盖旧归档），
   并按 error 记日志（会进 `AutoImportLog` 与目录里的 `logs.log`）；
3. **不是**我们的适配器处理的文件（别的仪器接口）→ 原样调用原生实现，行为不变。

★ 只包装一个方法、只介入"我们自己的失败"，不复制原生流程；
★ 重投：把文件从 `failed/` 拿回目录即可（`imported.csv` 里没有它）。
  重跑时值若相同会走 `MATCH`（幂等），不会覆盖。
★ 本模块**顶层不 import senaite/bika**（单测按文件路径加载）。
"""

import logging
import os
import threading
import time

logger = logging.getLogger("maitux.instrument_acquisition")

#: 失败文件归档的子目录名（相对自动导入目录）
FAILED_DIRNAME = u"failed"

#: 线程局部：当前文件跑完之后的结论（由我们的导入器写入、由包装器取走）
_STATE = threading.local()

#: 幂等标记（避免重复包装）
PATCH_FLAG = "_maitux_auto_import_archive_patched"


def _norm(path):
    """归一化路径（用于把"适配器的结论"与"包装器看到的文件"对上）"""
    if not path:
        return u""
    try:
        return os.path.normcase(os.path.abspath(path))
    except Exception:
        return u"%s" % path


def remember_outcome(path, filename, success, message=u""):
    """记下"这份文件的导入结论"（线程局部，只保留最近一次）"""
    _STATE.outcome = {
        u"path": _norm(path),
        u"filename": filename,
        u"success": bool(success),
        u"message": message or u"",
    }


def clear_outcome():
    """清掉结论（每份文件开跑前调一次，避免上一份的结论串到下一份）"""
    _STATE.outcome = None


def take_outcome(path):
    """取走**这份文件**的结论；路径不符或没有结论 → `None`

    ★ 路径必须逐字对上：包装器是全局生效的，而目录里可能有别的仪器接口的
    文件在同一轮里被处理（同一文件名出现在两个目录时更要靠路径区分）。
    """
    outcome = getattr(_STATE, "outcome", None)
    if not outcome:
        return None
    if outcome.get(u"path") != _norm(path):
        return None
    _STATE.outcome = None
    return outcome


def failed_folder(folder):
    """失败归档目录（`<folder>/failed`）"""
    return os.path.join(folder, FAILED_DIRNAME)


def failed_target(folder, filename):
    """失败归档的目标路径；重名时加时间戳前缀（**不覆盖**已有归档）"""
    target = os.path.join(failed_folder(folder), filename)
    if not os.path.exists(target):
        return target
    stamp = time.strftime(u"%Y%m%d-%H%M%S")
    return os.path.join(failed_folder(folder), u"%s_%s" % (stamp, filename))


def archive_failed_file(folder, filename):
    """把失败文件移进 `failed/`

    :returns: `(归档后的路径, 说明)`；第一个元素为 `None` 表示**没动文件**
        （原因见第二个元素）
    """
    source = os.path.join(folder, filename)
    if not os.path.isfile(source):
        return None, u"源文件不存在：%s" % source
    target_dir = failed_folder(folder)
    try:
        if not os.path.isdir(target_dir):
            os.makedirs(target_dir)
    except Exception as exc:
        return None, u"建 failed/ 目录失败：%s" % exc

    target = failed_target(folder, filename)
    try:
        os.rename(source, target)
    except Exception as exc:
        return None, u"移动失败文件失败：%s" % exc
    return target, u"已移入 %s" % os.path.basename(target_dir)


def as_unicode(value):
    """把（可能是 utf-8 字节串的）日志条目转成 unicode

    ★ 原生 `format_logmsg` 返回的是**编码后的 str**，与 unicode 混在一起；
    `u"%s" % str` 在 py2 会按 ascii 解码 → 中文必崩。这里显式解码。
    """
    if isinstance(value, unicode):
        return value
    if isinstance(value, str):
        for encoding in (u"utf-8", u"gbk", u"latin-1"):
            try:
                return value.decode(encoding)
            except Exception:
                continue
        return u""
    return u"%s" % (value,)


def safe_join(logs):
    """把日志条目拼成 unicode 响应（替代原生 `str.join(list)`）"""
    return u"\n".join([as_unicode(entry) for entry in (logs or [])])


def patch_auto_import():
    """包装 `AutoImportResultsView` 的两个方法（幂等）

    1. `write_imported_file`：失败文件不记账 + 移入 `failed/`（本模块的主目的）
    2. `__call__`：原生用 `str` 的 `"\\n".join(unicode logs)` 拼响应，**日志里一有
       非 ASCII 就 `UnicodeDecodeError` → 整个视图 500**（实测：本插件的中文
       落位消息一进日志，自动导入接口就报 500，而数据其实已经处理完了 ——
       定时任务会误判为"整批失败"）。这里只在原生会崩的情况下兜底成 unicode 拼接。

    :returns: `True` = 本次完成包装；`False` = 之前已经包过
    """
    from senaite.core.exportimport.auto_import_results import (
        AutoImportResultsView,
    )

    if getattr(AutoImportResultsView, PATCH_FLAG, False):
        return False

    original_write = AutoImportResultsView.write_imported_file

    def write_imported_file(self, folder, filename):
        outcome = take_outcome(os.path.join(folder, filename))
        if outcome is not None and not outcome.get(u"success"):
            archived, note = archive_failed_file(folder, filename)
            if archived:
                self.log(
                    u"Import FAILED for '{}' -> {} ; NOT recorded in "
                    u"imported.csv (re-drop the file to retry). {}"
                    .format(filename, archived, outcome.get(u"message") or u""),
                    level="error")
            else:
                self.log(
                    u"Import FAILED for '{}' and the file could not be "
                    u"archived ({}); NOT recorded in imported.csv. {}"
                    .format(filename, note, outcome.get(u"message") or u""),
                    level="error")
            return
        # 不是我们处理的文件（或没结论）→ 保持原生行为
        return original_write(self, folder, filename)

    AutoImportResultsView.write_imported_file = write_imported_file

    original_call = AutoImportResultsView.__call__

    def __call__(self):
        try:
            return original_call(self)
        except UnicodeDecodeError:
            # 日志里有非 ASCII（中文）时原生会崩，兜底成 unicode 拼接
            return safe_join(getattr(self, "logs", None))

    AutoImportResultsView.__call__ = __call__
    setattr(AutoImportResultsView, PATCH_FLAG, True)
    logger.info("maitux: auto import failure archive patch applied")
    return True


def patch_deferred(event=None):
    """ZODB 起来之后再试一次（冷启动时 senaite.core 可能还没 import 完）"""
    try:
        patch_auto_import()
    except Exception:
        import sys
        sys.stderr.write(
            "maitux: deferred auto import archive patch failed\n")
