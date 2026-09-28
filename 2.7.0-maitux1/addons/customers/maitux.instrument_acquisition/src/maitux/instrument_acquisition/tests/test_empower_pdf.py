# -*- coding: utf-8 -*-
"""Empower 报告解析测试（纯单元测试，不依赖 Zope / 不依赖 PDF 文件）

几何 fixture 全部按 `doc/仪器采集/报告样张` 实测坐标缩小重排（见 `empower_pdf` 模块
docstring 的"关键几何事实"），因此**不需要把 PDF 提交进仓库**也能回归：

- 样品信息块：左标签右值，两列并排，标签与值有 <1pt 的 y 抖动
- 峰表：表头列锚点 + 数据行右对齐（与锚点有最多 ~16pt 偏差）
- 页脚行（`Report Method ID: 2067`）会被误认成 RT 列 → 必须排除

★ 与 `test_phase1_targets.py` 同样按文件路径加载模块，避免触发包级
`__init__` 引入 bika.lims 等 Zope 依赖。
"""

import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVICES = os.path.join(_HERE, "..", "services")


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


_empower = _load_source(
    "maitux_empower_pdf_test", os.path.join(_SERVICES, "empower_pdf.py"))
_pdf_text = _load_source(
    "maitux_pdf_text_test", os.path.join(_SERVICES, "pdf_text.py"))


def item(x, y, text):
    return {"x": x, "y": y, "text": text, "size": 7.98}


def page(index, items):
    return {"index": index, "items": items, "text": u""}


def sample_info_block(y0, sample_name, vial, injection_no, sample_type=u"Unknown",
                      sample_set_name=u"WS-003_S1919_IP_LC013_01"):
    """按实测几何造一个样品信息块（左列 x=41/131，右列 x=290/386）"""
    return [
        item(175.44, y0 + 20.16, u"S A M P L E      I N F O R M A T I O N"),
        item(41.04, y0, u"Sample Name:"),
        item(131.04, y0, sample_name),
        item(41.04, y0 - 12.24, u"Sample Type:"),
        item(131.04, y0 - 12.24, sample_type),
        item(290.40, y0 - 12.24, u"Acquired By:"),
        item(386.16, y0 - 12.24, u"mavis.zhang"),
        # 值比标签低 0.48pt：真实报告就这样
        item(41.04, y0 - 24.0, u"Vial:"),
        item(131.04, y0 - 23.52, vial),
        item(290.88, y0 - 24.48, u"Sample Set Name:"),
        item(386.88, y0 - 23.52, sample_set_name),
        item(41.04, y0 - 36.0, u"Injection #:"),
        item(131.04, y0 - 36.0, injection_no),
        item(41.04, y0 - 48.24, u"Date Acquired:"),
        item(131.04, y0 - 48.24, u"Tuesday, May 12, 2026 9:34:17 PM CST"),
    ]


def peaks_table(y0, rows, columns=None):
    """造一个峰表：表头（含 Purity 分组）+ 数据行（右对齐、缺格留空）"""
    columns = columns or [
        (u"Peak Name", 54.48), (u"RT(min)", 109.20), (u"Area", 160.32),
        (u"% Area", 200.40), (u"Height", 243.12), (u"USP s/n", 280.08),
        (u"Resolution", 321.60), (u"Tailing", 373.92),
    ]
    items = []
    for label, x in columns:
        items.append(item(x, y0, label))
    items.append(item(411.36, y0 + 6.24, u"Purity"))
    items.append(item(412.32, y0 - 6.24, u"Angle"))
    items.append(item(457.20, y0 + 6.24, u"Purity"))
    items.append(item(449.28, y0 - 6.24, u"Threshold"))
    y = y0 - 24.48
    for row in rows:
        # row = (peak_no, rt, area, pct_area, height, sn, resolution, tailing)
        values = [
            (38.64, row[0]), (109.20, row[1]), (160.32, row[2]),
            (207.12, row[3]), (256.56, row[4]), (291.60, row[5]),
            (334.32, row[6]), (380.16, row[7]),
        ]
        for x, value in values:
            if value in (None, u""):
                continue
            items.append(item(x, y, u"%s" % value))
        y -= 18.48
    return items


FOOTER = [
    item(31.92, 94.32, u"Reported by User:  Mavis Zhang (mavis.zhang)"),
    item(31.92, 80.40, u"Report Method:  The Report of S1908 IP"),
    item(31.92, 66.72, u"Report Method ID: 2067"),
    item(113.28, 66.72, u"2067"),
    item(31.92, 53.04, u"Page: 4 of 12"),
]


class SampleInfoTest(unittest.TestCase):
    """样品信息块：标签在左、值在右，两列并排"""

    def test_pairs_value_on_the_right(self):
        items = sample_info_block(697.20, u"STD-1", u"1:A,4", u"2")
        info = _empower.parse_sample_info(items)
        self.assertEqual(info[u"Sample Name"], u"STD-1")
        self.assertEqual(info[u"Sample Type"], u"Unknown")
        self.assertEqual(info[u"Vial"], u"1:A,4")
        self.assertEqual(info[u"Sample Set Name"], u"WS-003_S1919_IP_LC013_01")
        self.assertEqual(info[u"Injection #"], u"2")
        self.assertEqual(info[u"Acquired By"], u"mavis.zhang")

    def test_right_column_label_does_not_steal_left_value(self):
        """右列标签（x≈290）不能被当左列的值"""
        items = sample_info_block(697.20, u"SYS", u"1:A,3", u"1")
        info = _empower.parse_sample_info(items)
        self.assertEqual(info[u"Sample Name"], u"SYS")
        self.assertEqual(info[u"Vial"], u"1:A,3")


class PeaksTableTest(unittest.TestCase):
    """峰表：列锚点 + 最近锚点归属 + 页脚行排除"""

    def test_maps_columns_by_x(self):
        items = peaks_table(265.20, [(1, u"4.947", u"1850", u"0.01", u"192",
                                      u"20", None, u"1.0")])
        peaks, _warn = _empower.parse_peaks(items + FOOTER)
        self.assertEqual(len(peaks), 1)
        peak = peaks[0]
        self.assertEqual(peak[u"peak_no"], 1)
        self.assertEqual(peak[u"rt"], 4.947)
        self.assertEqual(peak[u"area"], 1850.0)
        self.assertEqual(peak[u"pct_area"], 0.01)
        self.assertEqual(peak[u"height"], 192.0)
        self.assertEqual(peak[u"sn"], 20.0)
        self.assertIsNone(peak[u"resolution"])
        self.assertEqual(peak[u"tailing"], 1.0)

    def test_purity_group_header_merged(self):
        items = peaks_table(265.20, [(1, u"34.53", u"64814", u"100.00",
                                      u"4790", u"398", None, u"1.0")])
        peaks, _warn = _empower.parse_peaks(items)
        # Purity Angle / Purity Threshold 两行的 x 对齐 → 合并成一列
        self.assertIn(u"purity_angle", peaks[0])
        self.assertIn(u"purity_threshold", peaks[0])

    def test_footer_row_is_not_a_peak(self):
        """★ 踩过的坑：`Report Method ID: 2067` 的 2067 落在 RT 列锚点附近"""
        items = peaks_table(265.20, [(1, u"4.947", u"1850", u"0.01", u"192",
                                      u"20", None, u"1.0")])
        peaks, _warn = _empower.parse_peaks(items + FOOTER)
        self.assertEqual(len(peaks), 1)
        for peak in peaks:
            self.assertNotEqual(peak[u"rt"], 2067.0)

    def test_multi_peak_rows_are_separate(self):
        items = peaks_table(265.20, [
            (1, u"4.947", u"1850", u"0.01", u"192", u"20", None, u"1.0"),
            (2, u"19.988", u"1760", u"0.01", u"151", u"15", u"59.6", u"1.2"),
        ])
        peaks, _warn = _empower.parse_peaks(items)
        self.assertEqual([peak[u"peak_no"] for peak in peaks], [1, 2])
        self.assertEqual(peaks[1][u"resolution"], 59.6)

    def test_no_header_no_peaks(self):
        items = sample_info_block(697.20, u"BLANK", u"1:A,1", u"1") + FOOTER
        peaks, _warn = _empower.parse_peaks(items)
        self.assertEqual(peaks, [])


class PageAssemblyTest(unittest.TestCase):
    """多页：续页没有样品信息块时接到上一节；同身份相邻节合并"""

    def test_continuation_page_attaches_to_previous(self):
        first = page(0, sample_info_block(697.20, u"SYS", u"1:A,3", u"1") +
                     peaks_table(265.20, [(1, u"4.947", u"1850", u"0.01",
                                           u"192", u"20", None, u"1.0")]) +
                     FOOTER)
        second = page(1, peaks_table(265.20, [(8, u"36.467", u"76335",
                                              u"0.57", u"5981", u"648",
                                              u"5.6", u"1.0")]) + FOOTER)
        parsed = _empower.parse_pages([first, second])
        self.assertEqual(len(parsed["injections"]), 1)
        injection = parsed["injections"][0]
        self.assertEqual(injection["sample_name"], u"SYS")
        self.assertEqual([peak["peak_no"] for peak in injection["peaks"]], [1, 8])
        self.assertEqual(injection["page_indexes"], [0, 1])

    def test_peak_table_without_sample_info_warns(self):
        parsed = _empower.parse_pages([page(0, peaks_table(
            265.20, [(1, u"4.947", u"1850", u"0.01", u"192", u"20", None,
                     u"1.0")]))])
        self.assertEqual(parsed["injections"], [])
        self.assertTrue(any(u"no sample information" in warning
                            for warning in parsed["warnings"]))


class SplitSampleNameTest(unittest.TestCase):
    """SampleName 三段式拆分（规范 §4.5）"""

    def test_recovery_specified(self):
        split = _empower.split_sample_name(u"REC-SPEC-LOQ-1")
        self.assertEqual(split["role"], u"REC-SPEC")
        self.assertEqual(split["level"], u"LOQ")
        self.assertEqual(split["idx"], u"1")

    def test_recovery_non_specific(self):
        split = _empower.split_sample_name(u"REC-NS-100-A3")
        self.assertEqual(split["role"], u"REC-NS")
        self.assertEqual(split["level"], u"100")
        self.assertEqual(split["idx"], u"A3")

    def test_role_with_digit_is_not_split(self):
        """★ `STD-1` 不能被拆成 role=STD / idx=1（规范 §4.5 的右往左规则会踩）"""
        split = _empower.split_sample_name(u"STD-1")
        self.assertEqual(split["role"], u"STD-1")
        self.assertEqual(split["segments"], [])

    def test_stability_and_degradation(self):
        self.assertEqual(_empower.split_sample_name(u"STAB-RT-100-1(T1)")["role"],
                         u"STAB-RT")
        self.assertEqual(_empower.split_sample_name(u"DEG-ACID-1")["role"],
                         u"DEG")
        self.assertEqual(_empower.split_sample_name(u"LIN-6")["role"], u"LIN")

    def test_batch_name(self):
        split = _empower.split_sample_name(
            u"ICPNB000000249-112e-P-R-1(T0)")
        self.assertTrue(split["is_batch"])
        self.assertEqual(split["role"], u"")

    def test_unknown_role_kept_whole(self):
        split = _empower.split_sample_name(u"ACC-LOQ-SPIKED-1")
        self.assertEqual(split["role"], u"ACC-LOQ-SPIKED-1")
        self.assertEqual(split["segments"], [])


class NormalizeTest(unittest.TestCase):
    """Sample Type 断行归一 / WorkSheet ID 提取"""

    def test_sample_type_line_break(self):
        self.assertEqual(_empower._normalize_sample_type(u"Unknow n"),
                         u"Unknown")
        self.assertEqual(_empower._normalize_sample_type(u"Standard"),
                         u"Standard")

    def test_worksheet_id_from_new_style_name(self):
        self.assertEqual(
            _empower._worksheet_id(u"WS-003_S1919_IP_LC013_01"), u"WS-003")

    def test_worksheet_id_from_bare_name(self):
        """2026-09-21 客户约定：Sample Set Name **只录 WorkSheet 编号**"""
        self.assertEqual(_empower._worksheet_id(u"WS-006"), u"WS-006")

    def test_worksheet_id_absent_in_old_style_name(self):
        """旧序列名是日期开头（规范 §3.1 之前）→ 没有 WorkSheet ID"""
        self.assertEqual(
            _empower._worksheet_id(u"20260512_VF_IP_LC013_01"), u"")


class GroupBySampleTest(unittest.TestCase):

    def test_orders_by_injection_no(self):
        injections = [
            {u"sample_name": u"STD-1", u"injection_no": u"6", u"peaks": []},
            {u"sample_name": u"STD-1", u"injection_no": u"2", u"peaks": []},
            {u"sample_name": u"STD-2", u"injection_no": u"1", u"peaks": []},
        ]
        grouped = dict(_empower.group_by_sample(injections))
        self.assertEqual(len(grouped[u"STD-1"]), 2)
        self.assertEqual(grouped[u"STD-1"][0][u"injection_no"], u"2")
        self.assertEqual(grouped[u"STD-1"][1][u"injection_no"], u"6")


class PdfTextStructureTest(unittest.TestCase):
    """PDF 页树解析（用极小的对象体片段，不依赖真实 PDF）"""

    def test_contents_array_and_single(self):
        array_body = b"<</Contents[23 0 R 24 0 R]/Type/Page>>"
        single_body = b"<</Contents 2 0 R/Type/Page>>"
        self.assertEqual(_pdf_text.content_refs(array_body), [23, 24])
        self.assertEqual(_pdf_text.content_refs(single_body), [2])

    def test_kids_refs(self):
        body = b"<</Count 3/Kids[20 0 R 1 0 R 4 0 R]/Type/Pages>>"
        self.assertEqual(_pdf_text.kids_refs(body), [20, 1, 4])

    def test_page_order_follows_kids(self):
        """页序必须按 /Kids，而不是对象号"""
        objects = {
            9: b"<</Count 2/Kids[20 0 R 1 0 R]/Type/Pages>>",
            20: b"<</Contents 2 0 R/Type/Page>>",
            1: b"<</Contents 5 0 R/Type/Page>>",
        }
        self.assertEqual(_pdf_text.page_order(objects), [20, 1])

    def test_pages_node_pattern_does_not_match_leaf(self):
        self.assertIsNone(_pdf_text._PAGES_NODE_RE.search(
            b"<</Contents 2 0 R/Type/Page>>"))


if __name__ == "__main__":
    unittest.main()
