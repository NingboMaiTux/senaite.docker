# -*- coding: utf-8 -*-
"""自动导入失败归档测试（纯文件系统 + 假的原生视图，不依赖 Zope）

覆盖 `importer/auto_import_archive.py`：

- 线程局部的"结论"握手：只认**路径逐字相同**的那份文件（不串到别的仪器目录）
- 失败 → 文件移入 `<folder>/failed/`、**不写** `imported.csv`（可重投）
- 成功 / 不是我们的文件 → 原样交回原生实现
- 归档不覆盖旧归档（重名加时间戳）

★ 按文件路径加载模块，`patch_auto_import()` 内部是延迟导入，测试里用假模块替换
`senaite.core.exportimport.auto_import_results`。
"""

import os
import shutil
import sys
import tempfile
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_IMPORTER = os.path.join(_HERE, "..", "importer")


def _load_source(name, path):
    try:
        import imp
        return imp.load_source(name, path)
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


_archive = _load_source(
    "maitux_auto_import_archive_test",
    os.path.join(_IMPORTER, "auto_import_archive.py"))

_FAKE_MODULE = "senaite.core.exportimport.auto_import_results"


class FakeAutoImportView(object):
    """假的原生视图：只记录"原实现有没有被调用"与日志"""

    #: 模拟原生 `__call__` 在日志含中文时崩（py2 `str.join(unicode)`）
    raise_on_call = False

    def __init__(self):
        self.logs = []
        self.levels = []
        self.recorded = []

    def log(self, msg, instrument=None, interface=None, level="info"):
        # ★ 与原生一致：`self.logs` 存的是**格式化后的 str（可能已 utf-8 编码）**
        self.logs.append((u"%s" % msg).encode("utf-8"))
        self.levels.append(level)

    def write_imported_file(self, folder, filename):
        """原生实现：把文件名写进 imported.csv（用 list 代替文件即可）"""
        self.recorded.append(filename)

    def __call__(self):
        self.log(u"报告导入：找不到 WorkSheet")
        if self.raise_on_call:
            raise UnicodeDecodeError("ascii", b"\xe6", 0, 1, "boom")
        return u"ok"


def _install_fake_core(view_class):
    """把整条父包链与目标模块都塞进 sys.modules（延迟导入才找得到）"""
    saved = {}
    names = ["senaite", "senaite.core", "senaite.core.exportimport",
             _FAKE_MODULE]
    for name in names:
        saved[name] = sys.modules.get(name)
        sys.modules[name] = types.ModuleType(name)
    sys.modules[_FAKE_MODULE].AutoImportResultsView = view_class
    return saved


def _restore(saved):
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class ResetOutcomeMixin(object):

    def setUp(self):
        _archive.clear_outcome()
        self.tmpdir = tempfile.mkdtemp(prefix="maitux-archive-")

    def tearDown(self):
        _archive.clear_outcome()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_file(self, name, content=u"pdf-bytes"):
        path = os.path.join(self.tmpdir, name)
        with open(path, "wb") as handle:
            handle.write(content.encode("utf-8") if isinstance(
                content, type(u"")) else content)
        return path


class OutcomeHandshakeTest(ResetOutcomeMixin, unittest.TestCase):
    """结论握手：路径必须逐字对上，取走即清空"""

    def test_take_returns_only_for_same_path(self):
        path = os.path.join(self.tmpdir, "a.pdf")
        _archive.remember_outcome(path, u"a.pdf", False, u"boom")
        self.assertIsNone(_archive.take_outcome(
            os.path.join(self.tmpdir, "b.pdf")))
        outcome = _archive.take_outcome(path)
        self.assertIsNotNone(outcome)
        self.assertFalse(outcome[u"success"])
        self.assertEqual(outcome[u"message"], u"boom")

    def test_take_clears_the_record(self):
        path = os.path.join(self.tmpdir, "a.pdf")
        _archive.remember_outcome(path, u"a.pdf", True)
        self.assertIsNotNone(_archive.take_outcome(path))
        self.assertIsNone(_archive.take_outcome(path))

    def test_relative_and_absolute_paths_match(self):
        """原生传的是拼出来的绝对路径，记的是同一串 —— 归一化后必须相等"""
        path = os.path.join(self.tmpdir, "a.pdf")
        _archive.remember_outcome(path, u"a.pdf", True)
        self.assertIsNotNone(_archive.take_outcome(path))


class ArchiveFailedFileTest(ResetOutcomeMixin, unittest.TestCase):

    def test_moves_file_into_failed_folder(self):
        self.write_file("report.pdf")
        archived, note = _archive.archive_failed_file(self.tmpdir, u"report.pdf")
        self.assertTrue(archived)
        self.assertEqual(os.path.dirname(archived),
                         _archive.failed_folder(self.tmpdir))
        self.assertEqual(os.path.basename(archived), u"report.pdf")
        self.assertFalse(os.path.exists(
            os.path.join(self.tmpdir, "report.pdf")))
        self.assertTrue(os.path.exists(archived))
        self.assertTrue(note)

    def test_missing_source_is_reported(self):
        archived, note = _archive.archive_failed_file(self.tmpdir, u"nope.pdf")
        self.assertIsNone(archived)
        self.assertIn(u"不存在", note)

    def test_existing_archive_is_not_overwritten(self):
        self.write_file("report.pdf")
        first, _note = _archive.archive_failed_file(self.tmpdir, u"report.pdf")
        self.write_file("report.pdf")
        second, _note = _archive.archive_failed_file(self.tmpdir, u"report.pdf")
        self.assertNotEqual(first, second)
        self.assertTrue(os.path.exists(first))
        self.assertTrue(os.path.exists(second))

    def test_creates_failed_folder_on_demand(self):
        self.write_file("report.pdf")
        self.assertFalse(os.path.isdir(_archive.failed_folder(self.tmpdir)))
        _archive.archive_failed_file(self.tmpdir, u"report.pdf")
        self.assertTrue(os.path.isdir(_archive.failed_folder(self.tmpdir)))


class PatchedWriteImportedFileTest(ResetOutcomeMixin, unittest.TestCase):

    def setUp(self):
        super(PatchedWriteImportedFileTest, self).setUp()
        self.saved = _install_fake_core(FakeAutoImportView)
        _archive.patch_auto_import()

    def tearDown(self):
        _restore(self.saved)
        super(PatchedWriteImportedFileTest, self).tearDown()

    def _patched_class(self):
        return sys.modules[_FAKE_MODULE].AutoImportResultsView

    def test_failure_is_archived_and_not_recorded(self):
        self.write_file("report.pdf")
        _archive.remember_outcome(
            os.path.join(self.tmpdir, "report.pdf"), u"report.pdf", False,
            u"找不到 WorkSheet")
        view = self._patched_class()()
        view.write_imported_file(self.tmpdir, u"report.pdf")
        # 不记账（可重投）
        self.assertEqual(view.recorded, [])
        # 文件进了 failed/
        self.assertFalse(os.path.exists(
            os.path.join(self.tmpdir, "report.pdf")))
        self.assertTrue(os.path.exists(os.path.join(
            _archive.failed_folder(self.tmpdir), u"report.pdf")))
        # 日志里能看见失败与原因
        text = _archive.safe_join(view.logs)
        self.assertIn(u"FAILED", text)
        self.assertIn(u"找不到 WorkSheet", text)
        self.assertIn(u"error", view.levels)

    def test_success_falls_through_to_core(self):
        self.write_file("report.pdf")
        _archive.remember_outcome(
            os.path.join(self.tmpdir, "report.pdf"), u"report.pdf", True,
            u"已写入 13 个目标位")
        view = self._patched_class()()
        view.write_imported_file(self.tmpdir, u"report.pdf")
        self.assertEqual(view.recorded, [u"report.pdf"])
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "report.pdf")))

    def test_unknown_file_falls_through_to_core(self):
        """别的仪器接口处理的文件 → 原生行为不变"""
        view = self._patched_class()()
        view.write_imported_file(self.tmpdir, u"other.pdf")
        self.assertEqual(view.recorded, [u"other.pdf"])

    def test_outcome_from_another_folder_does_not_leak(self):
        """同名文件在两个目录：结论按**路径**匹配，不能串"""
        other = tempfile.mkdtemp(prefix="maitux-archive-other-")
        try:
            _archive.remember_outcome(
                os.path.join(other, "report.pdf"), u"report.pdf", False,
                u"别的目录的失败")
            view = self._patched_class()()
            view.write_imported_file(self.tmpdir, u"report.pdf")
            self.assertEqual(view.recorded, [u"report.pdf"])
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_patch_is_idempotent(self):
        self.assertFalse(_archive.patch_auto_import())


class LogJoinTest(unittest.TestCase):
    """日志拼响应：原生 str.join(unicode/utf-8) 会崩，safe_join 必须都不崩"""

    def test_utf8_bytes_are_decoded(self):
        logs = [u"报告导入：找不到 WorkSheet".encode("utf-8")]
        self.assertIn(u"找不到 WorkSheet", _archive.safe_join(logs))

    def test_mixed_unicode_and_bytes(self):
        logs = [u"ASCII line", u"中文行".encode("utf-8")]
        joined = _archive.safe_join(logs)
        self.assertIn(u"ASCII line", joined)
        self.assertIn(u"中文行", joined)

    def test_empty_and_none(self):
        self.assertEqual(_archive.safe_join(None), u"")
        self.assertEqual(_archive.safe_join([]), u"")

    def test_non_string_entries_do_not_raise(self):
        self.assertIn(u"42", _archive.safe_join([42]))


class PatchedCallTest(ResetOutcomeMixin, unittest.TestCase):
    """原生 `__call__` 用 str 拼响应：日志含中文就 500 —— 包装后应能拿到日志"""

    def setUp(self):
        super(PatchedCallTest, self).setUp()
        self.saved = _install_fake_core(FakeAutoImportView)
        _archive.patch_auto_import()

    def tearDown(self):
        _restore(self.saved)
        super(PatchedCallTest, self).tearDown()

    def test_normal_response_passes_through(self):
        view = sys.modules[_FAKE_MODULE].AutoImportResultsView()
        self.assertEqual(view(), u"ok")

    def test_unicode_error_falls_back_to_joined_logs(self):
        cls = sys.modules[_FAKE_MODULE].AutoImportResultsView
        view = cls()
        view.raise_on_call = True
        result = view()
        self.assertIn(u"报告导入", result)


if __name__ == "__main__":
    unittest.main()
