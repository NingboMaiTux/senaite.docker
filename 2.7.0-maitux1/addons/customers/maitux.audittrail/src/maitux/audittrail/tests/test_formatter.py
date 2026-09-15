# -*- coding: utf-8 -*-
"""Calculation Interim Fields 格式化测试"""

import imp
import os
import unittest


FORMATTER_SOURCE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), os.pardir, "browser", "formatter.py"))


def load_formatter_module():
    """兼容 Python 2.7 的模块加载方式"""
    return imp.load_source("maitux_audittrail_formatter_test", FORMATTER_SOURCE)


class TestInterimFieldsFormatter(unittest.TestCase):
    """确保 Interim Fields 可以渲染成可读结构"""

    def test_render_interim_fields_html_contains_key_columns(self):
        """应把关键字段渲染成表格，而不是原始 JSON 串"""
        module = load_formatter_module()
        html = module.render_interim_fields_html([
            {
                "keyword": "CA_RF",
                "title": u"Ca_Rf",
                "result_type": "calculated",
                "value": "1.0",
                "formula": "[CA_SampleWeight] / [CA_SampleVolume]",
                "unit": "%",
                "choices": "",
                "allow_empty": False,
                "report": True,
                "hidden": False,
                "wide": True,
            }
        ])

        self.assertIn(u"关键字", html)
        self.assertIn(u"字段标题", html)
        self.assertIn(u"公式", html)
        self.assertIn(u"CA_RF", html)
        self.assertIn(u"Ca_Rf", html)
        self.assertIn(u"[CA_SampleWeight] / [CA_SampleVolume]", html)
        self.assertNotIn(u'["keyword"', html)

    def test_render_interim_fields_html_handles_empty_value(self):
        """空值也要返回可读提示，避免界面空白"""
        module = load_formatter_module()
        html = module.render_interim_fields_html([])

        self.assertIn(u"未设置", html)

    def test_render_interim_fields_html_accepts_pair_list_rows(self):
        """兼容审计 diff 中可能出现的键值对列表结构"""
        module = load_formatter_module()
        html = module.render_interim_fields_html([
            [
                ["allow_empty", "True"],
                ["apply_wide", "True"],
                ["choices", ""],
                ["formula", "<NO_VALUE>"],
                ["hidden", "False"],
                ["keyword", "NM"],
                ["report", "True"],
                ["result_type", "numeric"],
                ["title", "Nett Mass"],
                ["unit", "g"],
                ["value", "0"],
            ]
        ])

        self.assertIn(u"NM", html)
        self.assertIn(u"Nett Mass", html)
        self.assertIn(u"全局应用", html)


class TestDefaultValueFormatter(unittest.TestCase):
    """多选类型的默认值是 JSON 串，中文不能露成 \\uXXXX"""

    def test_json_list_value_is_decoded(self):
        """json.dumps 的 ensure_ascii 转义必须解回中文"""
        module = load_formatter_module()
        value = module.format_default_value(
            u'["\\u672a\\u77e5\\u6742\\u8d28", "Z7"]')

        self.assertEqual(value, u"未知杂质、Z7")
        self.assertNotIn(u"\\u672a", value)

    def test_real_list_value_is_joined(self):
        """快照里已经是列表时也要拼成可读文本"""
        module = load_formatter_module()

        self.assertEqual(
            module.format_default_value([u"未知杂质", u"Z7"]), u"未知杂质、Z7")

    def test_plain_value_is_untouched(self):
        """普通标量原样返回，不要被当成 JSON 处理"""
        module = load_formatter_module()

        self.assertEqual(module.format_default_value("0.5"), u"0.5")
        self.assertEqual(module.format_default_value(None), u"")

    def test_broken_json_falls_back_to_raw_text(self):
        """解析失败必须原样返回 —— 审计记录不允许因为格式化而丢失"""
        module = load_formatter_module()
        raw = u'["未闭合'

        self.assertEqual(module.format_default_value(raw), raw)


WORKSHEET_LAYOUT = [
    {
        "position": 1,
        "type": "a",
        "container_uid": "c0nta1ner0000000000000000000000a",
        "analysis_uid": "ana1ys1s0000000000000000000000b",
    },
    {
        "position": 1,
        "type": "d",
        "container_uid": "c0nta1ner0000000000000000000000a",
        "analysis_uid": "ana1ys1s0000000000000000000000c",
    },
]

LAYOUT_TITLES = {
    "c0nta1ner0000000000000000000000a": u"AP-0001",
    "ana1ys1s0000000000000000000000b": u"Ca_Rf",
    "ana1ys1s0000000000000000000000c": u"Nett Mass",
}


def layout_uid_resolver(uid):
    """模拟视图注入的 UID → 标题解析器"""
    return LAYOUT_TITLES.get(uid, u"")


class TestWorksheetLayoutFormatter(unittest.TestCase):
    """工作表布局（layout_view）也要能可视化，而不是打印原始 JSON"""

    def test_layout_renders_as_readable_table(self):
        """布局行必须摊成表格，UID 换成标题"""
        module = load_formatter_module()
        html = module.render_worksheet_layout_html(
            WORKSHEET_LAYOUT, uid_resolver=layout_uid_resolver)

        self.assertIn(u"audit-layout-table", html)
        self.assertIn(u"位置", html)
        self.assertIn(u"类型", html)
        self.assertIn(u"样品", html)
        self.assertIn(u"分析项", html)
        # 类型单字母要翻成人话
        self.assertIn(u"常规分析", html)
        self.assertIn(u"平行样", html)
        self.assertIn(u"AP-0001", html)
        self.assertIn(u"Ca_Rf", html)

    def test_layout_no_longer_leaks_json_or_raw_uids(self):
        """页面上不该再出现裸 UID 和 JSON 键名"""
        module = load_formatter_module()
        html = module.render_worksheet_layout_html(
            WORKSHEET_LAYOUT, uid_resolver=layout_uid_resolver)

        self.assertNotIn(u"c0nta1ner", html)
        self.assertNotIn(u"ana1ys1s", html)
        self.assertNotIn(u'"position"', html)
        self.assertNotIn(u"container_uid", html)

    def test_layout_keeps_raw_uid_when_resolution_fails(self):
        """解析不出标题就回落显示裸 UID —— 审计页面不能把值吞掉"""
        module = load_formatter_module()
        html = module.render_worksheet_layout_html(
            WORKSHEET_LAYOUT, uid_resolver=lambda uid: u"")

        self.assertIn(u"c0nta1ner0000000000000000000000a", html)

    def test_layout_tolerates_missing_resolver(self):
        """不注入解析器也必须渲染得出来（纯文本降级）"""
        module = load_formatter_module()
        html = module.render_worksheet_layout_html(WORKSHEET_LAYOUT)

        self.assertIn(u"audit-layout-table", html)
        self.assertIn(u"ana1ys1s0000000000000000000000b", html)

    def test_layout_accepts_pair_list_rows(self):
        """兼容键值对列表结构（同 interim 行的两种存法）"""
        module = load_formatter_module()
        html = module.render_worksheet_layout_html([
            [["position", "2"], ["type", "c"],
             ["container_uid", "c0nta1ner0000000000000000000000a"],
             ["analysis_uid", "ana1ys1s0000000000000000000000b"]],
        ], uid_resolver=layout_uid_resolver)

        self.assertIn(u"AP-0001", html)
        self.assertIn(u"Ca_Rf", html)
        self.assertIn(u"质控", html)

    def test_layout_handles_empty_value(self):
        """空布局返回可读提示，避免界面空白"""
        module = load_formatter_module()

        self.assertIn(u"未设置", module.render_worksheet_layout_html([]))
        self.assertIn(u"未设置", module.render_worksheet_layout_html(None))

    def test_layout_escapes_input(self):
        """样品标题来自用户输入，必须转义"""
        module = load_formatter_module()
        html = module.render_worksheet_layout_html(
            WORKSHEET_LAYOUT,
            uid_resolver=lambda uid: u'<script>alert("x")</script>')

        self.assertNotIn(u"<script>", html)
        self.assertIn(u"&lt;script&gt;", html)

    def test_unknown_analysis_type_falls_back_to_raw_code(self):
        """未知 type 原样显示，不要编造文案"""
        module = load_formatter_module()
        html = module.render_worksheet_layout_html([
            {"position": 3, "type": "z", "container_uid": "", "analysis_uid": ""},
        ])

        self.assertIn(u">z<", html)

    def test_layout_detected_by_field_name(self):
        """字段名命中即按布局渲染，空列表也要给出可读提示"""
        module = load_formatter_module()

        self.assertTrue(module.is_worksheet_layout("layout_view", []))
        self.assertTrue(module.is_worksheet_layout("Layout", []))
        self.assertFalse(module.is_worksheet_layout("analyses", []))

    def test_layout_detected_by_row_shape(self):
        """字段名变了也要认出来 —— 行结构才是稳定判据"""
        module = load_formatter_module()

        self.assertTrue(module.is_worksheet_layout("whatever", WORKSHEET_LAYOUT))
        self.assertTrue(module.looks_like_layout_rows(WORKSHEET_LAYOUT))

    def test_non_layout_value_under_layout_name_is_not_hijacked(self):
        """同名字段若存了别的列表，不能硬当成布局行"""
        module = load_formatter_module()

        self.assertFalse(module.is_worksheet_layout(
            "layout_view", [{"keyword": "NM", "value": "0"}]))
        self.assertFalse(module.is_worksheet_layout("layout_view", ["a", "b"]))

    def test_interim_fields_are_not_layout_rows(self):
        """Interim Fields 不能被布局分支抢走"""
        module = load_formatter_module()
        interim = [{
            "keyword": "NM", "title": u"Nett Mass", "result_type": "numeric",
            "value": "0", "formula": "<NO_VALUE>", "unit": "g",
        }]

        self.assertFalse(module.looks_like_layout_rows(interim))
        self.assertFalse(module.is_worksheet_layout("interim_fields", interim))


class TestJsonDataFormatter(unittest.TestCase):
    """快照里的 JSON 数据要摊开显示，而不是打印原始串"""

    def test_dict_renders_as_key_value_table(self):
        module = load_formatter_module()
        html = module.render_json_html({"unit": "g", "value": "0"})

        self.assertIn(u"audit-json-table", html)
        self.assertIn(u"audit-json-key", html)
        self.assertIn(u"unit", html)
        self.assertIn(u"g", html)

    def test_list_of_dicts_renders_as_records_table(self):
        module = load_formatter_module()
        html = module.render_json_html([
            {"keyword": "NM", "value": "0"},
            {"keyword": "CA", "value": "1"},
        ])

        self.assertIn(u"audit-json-index", html)
        self.assertIn(u"keyword", html)
        self.assertIn(u"NM", html)
        self.assertIn(u"CA", html)
        self.assertNotIn(u'{"keyword"', html)

    def test_json_string_is_decoded_without_escapes(self):
        """字面 JSON 串必须解回中文，别把 \\uXXXX 摆给读者看"""
        module = load_formatter_module()
        html = module.render_json_html(
            u'[{"title": "\\u672a\\u77e5\\u6742\\u8d28"}]')

        self.assertIn(u"未知杂质", html)
        self.assertNotIn(u"\\u672a", html)

    def test_json_string_of_scalars_renders_as_list(self):
        """多选默认值这种标量数组也要摊开"""
        module = load_formatter_module()
        html = module.render_json_html(u'["\\u672a\\u77e5\\u6742\\u8d28", "Z7"]')

        self.assertIn(u"audit-json-list", html)
        self.assertIn(u"未知杂质", html)
        self.assertIn(u"Z7", html)

    def test_plain_values_are_not_json(self):
        """普通标量与普通字符串列表不该进结构化分支"""
        module = load_formatter_module()

        self.assertFalse(module.is_json_data(u"手工复核"))
        self.assertFalse(module.is_json_data(u"0.5"))
        self.assertFalse(module.is_json_data(None))
        self.assertFalse(module.is_json_data([]))
        self.assertFalse(module.is_json_data({}))
        # analyses 这类 UID 列表走原生 "; " 拼接更好读
        self.assertFalse(module.is_json_data(["uid-1", "uid-2"]))

    def test_broken_json_is_not_treated_as_json(self):
        """解析失败必须原样返回 —— 审计记录不允许因为格式化而丢失"""
        module = load_formatter_module()
        raw = u'["未闭合'

        self.assertFalse(module.is_json_data(raw))
        # 内容原样保留，只做必要的 HTML 转义
        self.assertEqual(module.render_json_html(raw), u'[&quot;未闭合')

    def test_deep_nesting_falls_back_to_raw_json(self):
        """嵌套过深退回 JSON 文本，保证任何数据都渲染得出来"""
        module = load_formatter_module()
        html = module.render_json_html(
            {"l1": {"l2": {"l3": {"l4": u"deep"}}}})

        self.assertIn(u"audit-json-raw", html)
        self.assertIn(u"deep", html)

    def test_json_values_are_escaped(self):
        module = load_formatter_module()
        html = module.render_json_html({"x": u'<script>alert("x")</script>'})

        self.assertNotIn(u"<script>", html)
        self.assertIn(u"&lt;script&gt;", html)

    def test_nested_dict_is_rendered_recursively(self):
        module = load_formatter_module()
        html = module.render_json_html({"outer": {"inner": u"值"}})

        self.assertIn(u"outer", html)
        self.assertIn(u"inner", html)
        self.assertIn(u"值", html)


class TestSignatureFormatter(unittest.TestCase):
    """电子签名必须能在审计界面渲染出来（21 CFR Part 11 §11.50）"""

    def test_signature_from_structured_metadata(self):
        """优先取结构化的 metadata["esignature"]"""
        module = load_formatter_module()
        data = module.extract_signature({
            "esignature": {
                "enabled": True,
                "primary_signer_user_id": "analyst2",
                "meaning": u"批准",
                "reason": u"复核通过",
                "require_countersign": False,
                "auth_backend_id": "pas",
            },
        })

        self.assertEqual(data["signer"], u"analyst2")
        self.assertEqual(data["meaning"], u"批准")
        self.assertFalse(data["require_countersign"])

    def test_signature_falls_back_to_comments_summary(self):
        """结构化字典缺失时（策略关掉了摘要）必须能从 comments 解出来"""
        module = load_formatter_module()
        data = module.extract_signature({
            "comments": (
                u"Electronic signature; first_signer=analyst2; "
                u"second_signer=manager1; execution_user=analyst2; "
                u"countersign_required=yes; transition=verify; "
                u"signature_type=verification; meaning=Approval; "
                u"reason=eee; auth_backend=pas"
            ),
        })

        self.assertEqual(data["signer"], u"analyst2")
        self.assertEqual(data["countersigner"], u"manager1")
        self.assertEqual(data["meaning"], u"Approval")
        self.assertTrue(data["require_countersign"])

    def test_ordinary_comment_is_not_a_signature(self):
        """普通工作流备注不能被误认成签名"""
        module = load_formatter_module()

        self.assertIsNone(module.extract_signature({"comments": u"手工复核"}))
        self.assertIsNone(module.extract_signature({}))

    def test_render_signature_html_is_human_readable(self):
        """渲染结果必须是人类可读的，而不是原始字典"""
        module = load_formatter_module()
        html = module.render_signature_html({
            "signer": u"analyst2",
            "countersigner": u"",
            "meaning": u"批准",
            "reason": u"复核通过",
            "require_countersign": True,
            "auth_backend": u"pas",
        }, timestamp=u"2026-08-26 09:31")

        self.assertIn(u"签名人", html)
        self.assertIn(u"analyst2", html)
        self.assertIn(u"2026-08-26 09:31", html)
        self.assertIn(u"批准", html)
        # 要求双签但复核人还没到位，必须显式提示而不是留空
        self.assertIn(u"待复核", html)

    def test_render_signature_html_is_empty_without_signature(self):
        """无签名的行留空，不要占位符噪音"""
        module = load_formatter_module()

        self.assertEqual(module.render_signature_html(None), u"")

    def test_render_signature_html_escapes_input(self):
        """签名原因是用户输入，必须转义"""
        module = load_formatter_module()
        html = module.render_signature_html({
            "signer": u"analyst2",
            "reason": u'<script>alert("x")</script>',
        })

        self.assertNotIn(u"<script>", html)
        self.assertIn(u"&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
