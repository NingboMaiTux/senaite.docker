# -*- coding: utf-8 -*-
"""模板解析脚本通道测试（纯单元测试，不依赖 Zope / 不依赖 PDF 文件）

覆盖两部分：

1. `services/script_runner.py`：`.py` 脚本的进程内执行与错误语义；
2. `parsers/empower_report_parser.py`：上传到模板的那份采集脚本的
   `parse(payload)` 契约（用 `test_empower_pdf` 的几何 fixture 造 payload）。

★ 与其它测试一样按文件路径加载模块，避免触发包级 `__init__` 引入 bika.lims。
"""

import json
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVICES = os.path.join(_HERE, "..", "services")
_PARSERS = os.path.join(_HERE, "..", "parsers")


def _load_source(name, path):
    """按文件路径加载模块（py2 用 imp；py3.12+ 用 importlib.util）"""
    try:
        import imp
        return imp.load_source(name, path)
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


_script_runner = _load_source(
    "maitux_script_runner_test", os.path.join(_SERVICES, "script_runner.py"))
_empower = _load_source(
    "maitux_empower_pdf_test2", os.path.join(_SERVICES, "empower_pdf.py"))
_fixtures = _load_source(
    "maitux_empower_fixtures_test", os.path.join(_HERE, "test_empower_pdf.py"))

# 采集脚本用 `from maitux...services import empower_pdf` 拿实现，
# 这里先把已加载的同源模块挂进 sys.modules，避免真的 import 整个 addon 包。
for _package in ("maitux", "maitux.instrument_acquisition",
                 "maitux.instrument_acquisition.services"):
    sys.modules.setdefault(_package, types.ModuleType(_package))
sys.modules["maitux.instrument_acquisition.services"].empower_pdf = _empower
_bundle = _load_source(
    "maitux_empower_report_parser_test",
    os.path.join(_PARSERS, "empower_report_parser.py"))


class FakeScript(object):
    def __init__(self, filename):
        self.filename = filename


class FakeTemplate(object):
    def __init__(self, filename):
        self.script_file = FakeScript(filename) if filename else None


def synthetic_extraction():
    """按实测几何造一份带坐标的抽取产物（1 针 1 峰）"""
    items = _fixtures.sample_info_block(
        700.0, u"SYS-1", u"1", u"1", sample_type=u"Sample")
    items += _fixtures.peaks_table(600.0, [
        (1, u"2.345", u"64915", u"99.5", u"12000", u"1234", u"1.2", u"1.05"),
    ])
    return {
        u"method": u"python",
        u"note": u"",
        u"filename": u"synthetic.pdf",
        u"pages": [_fixtures.page(0, items)],
        u"text": u"",
    }


class RunPyParserTest(unittest.TestCase):
    def test_script_returning_dict_is_json_encoded(self):
        source = (
            "def parse(payload):\n"
            "    return {'kw': u'\\u91cd\\u91cf', 'x': payload['x']}\n"
        )
        parsed = json.loads(_script_runner.run_py_parser(source, {u"x": 3}))
        self.assertEqual(parsed[u"x"], 3)
        self.assertEqual(parsed[u"kw"], u"重量")

    def test_missing_parse_is_reported(self):
        out = _script_runner.run_py_parser("VALUE = 1\n", {})
        self.assertTrue(out.startswith(u"[PY script error]"))
        self.assertIn(u"parse", out)

    def test_parse_exception_is_reported(self):
        source = "def parse(payload):\n    raise ValueError('boom')\n"
        out = _script_runner.run_py_parser(source, {})
        self.assertTrue(out.startswith(u"[PY parse error]"))
        self.assertIn(u"boom", out)

    def test_empty_source_is_reported(self):
        self.assertTrue(
            _script_runner.run_py_parser(None, {}).startswith(u"[PY script"))

    def test_unicode_source_is_executed(self):
        source = u"def parse(payload):\n    return {u'name': u'\u6837\u54c1'}\n"
        parsed = json.loads(_script_runner.run_py_parser(source, {}))
        self.assertEqual(parsed[u"name"], u"样品")


class TemplateScriptKindTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(
            _script_runner.template_script_kind(
                FakeTemplate(u"empower_report_parser.py")), "py")
        self.assertEqual(
            _script_runner.template_script_kind(FakeTemplate(u"balance.JS")),
            "js")
        self.assertIsNone(
            _script_runner.template_script_kind(FakeTemplate(u"readme.txt")))
        self.assertIsNone(
            _script_runner.template_script_kind(FakeTemplate(None)))
        self.assertIsNone(_script_runner.template_script_kind(None))


class EmpowerReportParserScriptTest(unittest.TestCase):
    def test_parse_coordinate_payload(self):
        result = _bundle.parse(synthetic_extraction())
        self.assertEqual(result[u"report_type"], u"empower_pdf")
        self.assertEqual(result[u"report"][u"worksheet_id"], u"WS-003")

        self.assertEqual(len(result[u"injections"]), 1)
        injection = result[u"injections"][0]
        self.assertEqual(injection[u"sample_name"], u"SYS-1")
        self.assertEqual(injection[u"role"], u"SYS")
        self.assertEqual(len(injection[u"peaks"]), 1)
        self.assertEqual(injection[u"peaks"][0][u"area"], 64915.0)

        self.assertEqual(len(result[u"grouped"]), 1)
        group = result[u"grouped"][0]
        self.assertEqual(group[u"sample_name"], u"SYS-1")
        self.assertEqual(group[u"injection_count"], 1)
        self.assertEqual(group[u"peak_count"], 1)

    def test_text_only_payload_warns(self):
        result = _bundle.parse({u"method": u"pdftotext", u"text": u"whatever"})
        self.assertEqual(result[u"injections"], [])
        self.assertTrue(result[u"warnings"])
        self.assertIn(u"pages", result[u"warnings"][0])

    def test_non_dict_payload_warns(self):
        result = _bundle.parse(u"plain text")
        self.assertEqual(result[u"report"], {})
        self.assertTrue(result[u"warnings"])


if __name__ == "__main__":
    unittest.main()
