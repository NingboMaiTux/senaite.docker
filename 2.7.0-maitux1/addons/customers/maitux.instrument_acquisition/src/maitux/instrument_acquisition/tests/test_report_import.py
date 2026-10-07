# -*- coding: utf-8 -*-
"""报告导入落位测试（纯函数，不依赖 Zope / 不依赖 PDF）

覆盖 `services/report_import.py` 与 `services/report_targets.py`：

- 页面配置（`keyword_glossary`）→ 目标位：合法行转换 + 非法行**点名**
- 取值规则 `pick`（主峰单值 / 该针整列 RT / 分离度首峰 N/A / 峰面积 / USP s/n / 面积求和）
- 「第 N 针」维度（实测 `imp_loqN_area` = 第 N 针的 6 峰，针优先）
- 「取前 N 峰」维度（同一份报告喂 `imp_linearity` 3 值 与 `imp_linearity_shared` 6 值）
- 「目标 RT」维度（实测 `imp_rec_spec.g_area` = RT≈24.3 的指定杂质峰面积，12/12 一致）
- 「峰序号清单」维度（实测 `imp_specificity` 取 SYS 16 峰里的 3,6,7,8,15,16）
- 按列写法 `decimals`（`"5.0"` 不能被写成 `"5"`）
- 期望长度闸门（局部报告不得覆盖完整数组）
- 针序按 injection_no 升序
- 与站点现值的对比语义（MATCH / DIFF / NEW，以及"仅格式差异"）
- 形态识别（报告产物 vs 调试通道 A 的 samples 形态）

★ 按文件路径加载模块，避免触发包级 `__init__` 引入 bika.lims。
"""

import json
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVICES = os.path.join(_HERE, "..", "services")


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


_import = _load_source(
    "maitux_report_import_test", os.path.join(_SERVICES, "report_import.py"))
_targets = _load_source(
    "maitux_report_targets_test", os.path.join(_SERVICES, "report_targets.py"))


#: 页面（keyword_glossary）配置的等价物：一期 Step 1 的 4 个目标位
PAGE_ROWS = (
    {"analysis_keyword": "imp_sys_suit", "calc_keyword": "imp_std1_area",
     "zh": u"对照品 1 各针主峰面积", "acq_source_sample": "STD-1",
     "acq_pick": "main_peak.area", "acq_decimals": "", "acq_length": 6},
    {"analysis_keyword": "imp_sys_suit", "calc_keyword": "imp_std2_area",
     "zh": u"对照品 2 各针主峰面积", "acq_source_sample": "STD-2",
     "acq_pick": "main_peak.area", "acq_decimals": "", "acq_length": 2},
    {"analysis_keyword": "imp_sys_separation", "calc_keyword": "g_rt",
     "zh": u"各峰保留时间", "acq_source_sample": "SYS",
     "acq_pick": "peaks.rt", "acq_decimals": "", "acq_length": 16},
    {"analysis_keyword": "imp_sys_separation",
     "calc_keyword": "imp_sep_res_before", "zh": u"各峰分离度",
     "acq_source_sample": "SYS", "acq_pick": "peaks.resolution",
     "acq_decimals": "1", "acq_length": 16},
)


def page_targets(rows=None):
    """页面行 → 目标位定义（与 `report_targets.load_targets` 同一条路径）"""
    targets = []
    for row in (rows if rows is not None else PAGE_ROWS):
        target, problem = _targets.build_target(row)
        assert target is not None, problem
        targets.append(target)
    return targets


#: Step 2「第 N 针」组：实测 `imp_loq1_area`…`imp_loq6_area` 各 = 第 N 针的 6 峰
#: （M0 §6.3 用现值自洽性判定为"针优先"；Step 2 只读取证逐值确认）
LOQ_ROWS = (
    {"analysis_keyword": "imp_lod_loq", "calc_keyword": "imp_loq1_area",
     "acq_source_sample": "LOQ", "acq_pick": "peaks.area",
     "acq_injection": 1, "acq_length": 6},
    {"analysis_keyword": "imp_lod_loq", "calc_keyword": "imp_loq2_area",
     "acq_source_sample": "LOQ", "acq_pick": "peaks.area",
     "acq_injection": 2, "acq_length": 6},
    {"analysis_keyword": "imp_lod_loq", "calc_keyword": "lod_sn1",
     "acq_source_sample": "LOD", "acq_pick": "peaks.sn",
     "acq_injection": 1, "acq_length": 6},
)

#: Step 2「取前 N 峰」组：同一份报告（`LOQ(Line-1)` 1 针 6 峰）喂两个宽度不同的分析
LIN_ROWS = (
    {"analysis_keyword": "imp_linearity", "calc_keyword": "imp_lin_a1",
     "acq_source_sample": "LOQ(Line-1)", "acq_pick": "peaks.area",
     "acq_peaks": 3, "acq_length": 3},
    {"analysis_keyword": "imp_linearity_shared", "calc_keyword": "imp_lin_a1",
     "acq_source_sample": "LOQ(Line-1)", "acq_pick": "peaks.area",
     "acq_length": 6},
)


#: 实测 `8 Acc-spiked-STD.pdf` 的 `ACC-LOQ-SPIKED-1`：主峰在 34.45、**指定杂质 Z7 在
#: 24.38**、邻峰在 25.43（必须落在 ±0.5 min 窗口之外）。站点 `imp_rec_spec.g_area[0]` = 14781
REC_SPEC_PEAKS = (
    (13469273.0, 34.452),   # 主峰
    (21000.0, 33.700),
    (14781.0, 24.382),      # ★ 指定杂质 Z7（目标峰）
    (3000.0, 25.429),       # 邻峰：24.3±0.5 = 23.8~24.8，必须被排除
    (8116.0, 36.450),
    (1850.0, 4.947),
)

#: 「目标 RT」+「面积求和」两组：`imp_rec_spec.g_area` / `imp_rec_nonspec.g_area`
REC_ROWS = (
    {"analysis_keyword": "imp_rec_spec", "calc_keyword": "g_area",
     "acq_source_sample": "ACC-LOQ-SPIKED-1", "acq_pick": "peaks.area",
     "acq_rt": 24.3, "acq_length": 1},
    {"analysis_keyword": "imp_rec_nonspec", "calc_keyword": "g_area",
     "acq_source_sample": "Acc-200%-1", "acq_pick": "peaks.area_sum",
     "acq_length": 1},
)

#: 「峰序号清单」：实测 `imp_specificity.imp_spec_sample_sol` 取自 SYS 16 峰里的这 6 个
SPEC_ROWS = (
    {"analysis_keyword": "imp_specificity",
     "calc_keyword": "imp_spec_sample_sol", "acq_source_sample": "SYS",
     "acq_pick": "peaks.rt", "acq_peak_indexes": "3,6,7,8,15,16",
     "acq_length": 6},
)


#: 槽位行（Step 3 峰级"多列同行"）页面配置：来源取自 M0 映射表 §2.6 的实测
#: ★ RT 列**写法必须 = 3**：站点存的是报告里的 3 位小数写法（`33.700`），
#:   解析出的是 float（`33.7`）—— 不补零就会 DIFF（本条由单测抓到）
ROW_CHROM_SLOT1 = {
    "analysis_keyword": "imp_chrom", "calc_keyword": "g_rt",
    "acq_source_sample": "ACC-100%-SPIKED-1(T0)", "acq_pick": "peaks.rt",
    "acq_decimals": "3", "acq_row_key": "g_sample_id", "acq_slot": "1",
    "acq_drop_rt": "47.48",
}
ROW_STAB_SLOT1 = {
    "analysis_keyword": "imp_stability_rt", "calc_keyword": "g_rt",
    "acq_source_sample": "ACC-100%-SPIKED-1(T0)", "acq_pick": "peaks.rt",
    "acq_decimals": "3", "acq_row_key": "g_sample_id", "acq_slot": "1",
    "acq_drop_rt": "47.48",
}
ROW_DEG_SLOT_UNDEG = {
    "analysis_keyword": "imp_degradation", "calc_keyword": "g_rt",
    "acq_source_sample": "ICPNB000000249-112e-P R-1(T0)",
    "acq_pick": "peaks.rt", "acq_decimals": "3", "acq_row_key": "imp_deg_id",
    "acq_slot": u"未破坏", "acq_drop_rt": "10.12",
}
#: 一个目标列写 6 个槽位：来源与槽位两个**等长清单**（页面一行装下整组）
ROW_CHROM_ALL_SLOTS = {
    "analysis_keyword": "imp_chrom", "calc_keyword": "g_rt",
    "acq_source_sample": ("ACC-100%-SPIKED-1(T0), ACC-100%-SPIKED-2, "
                          "ACC-100%-SPIKED-3, ACC-100%-SPIKED-4, "
                          "ACC-100%-SPIKED-5, ACC-100%-SPIKED-6"),
    "acq_pick": "peaks.rt", "acq_decimals": "3",
    "acq_row_key": "g_sample_id", "acq_slot": "1, 2, 3, 4, 5, 6",
    "acq_drop_rt": "10.12,47.48,50.62",
}


#: WS-006 实测的 STD-1 六针主峰面积（也与映射表的期望长度 6 对应）
STD1_AREAS = [64915.0, 64814.0, 65152.0, 65231.0, 65339.0, 65572.0]
#: WS-006 实测的 SYS 十六峰 RT（期望长度 16）
SYS_RTS = [4.947, 19.988, 24.372, 25.429, 26.306, 33.781, 34.469, 36.467,
           39.474, 40.985, 44.508, 45.994, 47.473, 48.429, 56.271, 58.129]


def peak(area, rt=34.5, no=1, resolution=None, sn=None):
    return {"peak_no": no, "rt": rt, "area": area, "resolution": resolution,
            "sn": sn}


def peaks_from(areas, sns=None):
    """由面积列表造峰（`sns` 给了就一并带上，用于 `peaks.sn`）"""
    items = []
    for index, area in enumerate(areas):
        sn = sns[index] if sns else None
        items.append(peak(area, no=index + 1, sn=sn))
    return items


def peaks_at(pairs):
    """由 `(area, rt)` 造峰（用于「目标 RT」筛选与面积求和的用例）"""
    return [peak(area, rt=rt, no=index + 1)
            for index, (area, rt) in enumerate(pairs)]


def injection(sample_name, injection_no, peaks):
    return {
        "sample_name": sample_name,
        "injection_no": injection_no,
        "peaks": peaks,
    }


class FakeAnalysis(object):
    """假分析对象（只实现 `resolve_analysis` 用到的三个方法）"""

    def __init__(self, keyword, sample_id=None, interims=None):
        self._keyword = keyword
        self._sample_id = sample_id
        self._interims = interims or []

    def getKeyword(self):
        return self._keyword

    def getRequestID(self):
        return self._sample_id

    def getInterimFields(self):
        return list(self._interims)

    def getInterimValue(self, keyword):
        for interim in self._interims:
            if interim.get("keyword") == keyword:
                return interim.get("value")
        return None


class FakeWorksheet(object):
    """假 WorkSheet：一张单可以装多个样品的同名分析（WS-001 / WS-004 的真实形态）"""

    def __init__(self, analyses):
        self._analyses = list(analyses)

    def getAnalyses(self):
        return list(self._analyses)


def report_payload(std1, std2, sys_group=None):
    """按解析产物形态造 payload（grouped 与 injections 同源）

    :param sys_group: `SYS` 进样列表（`imp_sys_separation` 的两个目标位要它）
    """
    groups = []
    for name, injections in ((u"STD-1", std1), (u"STD-2", std2),
                             (u"SYS", sys_group)):
        if injections is None:
            continue
        groups.append({
            "sample_name": name,
            "injection_count": len(injections),
            "peak_count": sum(len(i["peaks"]) for i in injections),
            "injections": injections,
        })
    return {
        "report_type": "empower_pdf",
        "report": {"worksheet_id": "WS-007"},
        "injections": [item for _n, items in ((u"STD-1", std1), (u"STD-2", std2),
                                              (u"SYS", sys_group))
                       for item in (items or [])],
        "grouped": groups,
        "warnings": [],
    }


def grouped_payload(**groups):
    """按 `{SampleName: [injection, ...]}` 造 payload（Step 2 的 LOQ / 线性用）

    ★ 刻意支持"同一样品被拆名"的现状：`5 LOQ.pdf` = `LOQ`(5 针) +
      `LOQ(Line-1)`(1 针)，两者是 payload 里的**两个** group。
    """
    grouped = []
    for name, injections in groups.items():
        grouped.append({
            "sample_name": name,
            "injection_count": len(injections),
            "peak_count": sum(len(i["peaks"]) for i in injections),
            "injections": injections,
        })
    return {
        "report_type": "empower_pdf",
        "report": {"worksheet_id": "WS-007"},
        "injections": [item for items in groups.values() for item in items],
        "grouped": grouped,
        "warnings": [],
    }


def std1_injections(areas=None, order=None):
    """`STD-1` 六针（长度必须与映射表一致，否则会被 `expected_length` 闸门拦下）"""
    areas = list(areas) if areas is not None else list(STD1_AREAS)
    numbers = list(order) if order is not None else range(1, len(areas) + 1)
    return [injection(u"STD-1", u"%d" % number, [peak(area)])
            for number, area in zip(numbers, areas)]


def std2_injections():
    """`STD-2` 两针"""
    return [injection(u"STD-2", u"1", [peak(67470.0)]),
            injection(u"STD-2", u"2", [peak(67774.0)])]


def sys_injection(rts=None):
    """`SYS` 十六峰（首峰无前峰 → 分离度 `None`）"""
    rts = list(rts) if rts is not None else list(SYS_RTS)
    peaks = []
    for index, rt in enumerate(rts):
        peaks.append(peak(1000.0 + index, rt=rt, no=index + 1,
                          resolution=None if index == 0 else 59.6 - index))
    return injection(u"SYS", u"1", peaks)


class NormalizeNumberTest(unittest.TestCase):
    def test_integer_float_drops_decimal(self):
        self.assertEqual(_import.normalize_number(64915.0), u"64915")

    def test_decimal_kept(self):
        self.assertEqual(_import.normalize_number(34.469), u"34.469")

    def test_none_is_na(self):
        self.assertEqual(_import.normalize_number(None), u"N/A")

    def test_string_trimmed(self):
        self.assertEqual(_import.normalize_number(u" 5.0 "), u"5.0")


class FormatValueTest(unittest.TestCase):
    """按列写法格式化（实测踩过：`"5.0"` 被写成 `"5"` → 与现值 DIFF）"""

    def test_one_decimal_keeps_point_zero(self):
        self.assertEqual(_import.format_value(5.0, 1), u"5.0")

    def test_one_decimal_keeps_fraction(self):
        self.assertEqual(_import.format_value(59.6, 1), u"59.6")

    def test_default_keeps_integer_without_decimal(self):
        self.assertEqual(_import.format_value(64915.0), u"64915")

    def test_default_keeps_rt_text(self):
        self.assertEqual(_import.format_value(4.947), u"4.947")

    def test_none_is_na(self):
        self.assertEqual(_import.format_value(None, 1), u"N/A")

    def test_non_numeric_text_falls_back(self):
        self.assertEqual(_import.format_value(u"---", 1), u"---")


class MainPeakTest(unittest.TestCase):
    def test_picks_largest_area(self):
        item = injection(u"SYS", u"1", [
            peak(1850.0, no=1), peak(12954593.0, rt=34.469, no=7),
            peak(62306.0, rt=58.129, no=16),
        ])
        self.assertEqual(_import.main_peak(item)["area"], 12954593.0)

    def test_no_peaks_returns_none(self):
        self.assertIsNone(_import.main_peak(injection(u"BLANK", u"1", [])))


class IsReportPayloadTest(unittest.TestCase):
    def test_empower_payload(self):
        self.assertTrue(_import.is_report_payload(
            report_payload([injection(u"STD-1", u"1", [peak(1.0)])], [])))

    def test_channel_a_payload_is_not_report(self):
        self.assertFalse(_import.is_report_payload({
            "samples": [{"sample_id": "AAP260920001", "assignments": []}]}))

    def test_non_dict(self):
        self.assertFalse(_import.is_report_payload(u"plain text"))


class PickValuesTest(unittest.TestCase):
    """取值规则（`pick`）：单值 vs 该针整列"""

    def test_main_peak_area_is_single_value(self):
        item = injection(u"STD-1", u"1", [
            peak(64915.0, no=1), peak(1850.0, no=2)])
        self.assertEqual(_import.pick_values(item, _targets.PICK_MAIN_PEAK_AREA),
                         [64915.0])

    def test_peaks_rt_returns_all_peaks_in_order(self):
        item = injection(u"SYS", u"1", [
            peak(1850.0, rt=4.947, no=1), peak(12954593.0, rt=34.469, no=7)])
        self.assertEqual(_import.pick_values(item, _targets.PICK_PEAKS_RT),
                         [4.947, 34.469])

    def test_peaks_resolution_keeps_first_peak_none(self):
        item = injection(u"SYS", u"1", [
            peak(1850.0, no=1), peak(12954593.0, no=2, resolution=59.6)])
        self.assertEqual(
            _import.pick_values(item, _targets.PICK_PEAKS_RESOLUTION),
            [None, 59.6])

    def test_peaks_sn_returns_all_peaks_in_order(self):
        item = injection(u"LOD", u"1", peaks_from(
            [1000.0, 2000.0], sns=[7.0, 8.0]))
        self.assertEqual(_import.pick_values(item, _targets.PICK_PEAKS_SN),
                         [7.0, 8.0])

    def test_peaks_area_returns_all_peaks_in_order(self):
        item = injection(u"LOQ", u"1", peaks_from([7672.0, 6688.0]))
        self.assertEqual(_import.pick_values(item, _targets.PICK_PEAKS_AREA),
                         [7672.0, 6688.0])

    def test_peaks_limit_takes_only_first_n(self):
        item = injection(u"LOQ(Line-1)", u"1", peaks_from(
            [7968.0, 6653.0, 6267.0, 7693.0, 4317.0, 5686.0]))
        self.assertEqual(
            _import.pick_values(item, _targets.PICK_PEAKS_AREA, 3),
            [7968.0, 6653.0, 6267.0])
        self.assertEqual(
            _import.pick_values(item, _targets.PICK_PEAKS_AREA, 6),
            [7968.0, 6653.0, 6267.0, 7693.0, 4317.0, 5686.0])

    def test_missing_cell_is_none(self):
        item = injection(u"LOD", u"1", [peak(1.0)])
        self.assertEqual(_import.pick_values(item, _targets.PICK_PEAKS_SN),
                         [None])

    def test_no_peaks_returns_empty(self):
        item = injection(u"BLANK", u"1", [])
        self.assertEqual(_import.pick_values(item, _targets.PICK_PEAKS_RT), [])

    def test_peaks_name_returns_all_names_in_order(self):
        item = injection(u"SYS", u"1", [
            dict(peak(1850.0, no=1), name=u"Z7"),
            dict(peak(12954593.0, no=2), name=u"主成分")])
        self.assertEqual(_import.pick_values(item, _targets.PICK_PEAKS_NAME),
                         [u"Z7", u"主成分"])

    def test_peaks_name_blank_becomes_unknown_impurity(self):
        # ★ 客户口径：Peak Name 只会是"采集名称"或"空白"；空白 = 未命名杂质。
        #   必须**占位**（不能跳过），否则峰级数组会错位/被长度闸门拒绝。
        item = injection(u"SYS", u"1", [
            dict(peak(1850.0, no=1), name=u"Z7"),
            dict(peak(12954593.0, no=2), name=u""),
            peak(3000.0, no=3)])
        self.assertEqual(
            _import.pick_values(item, _targets.PICK_PEAKS_NAME),
            [u"Z7", _targets.UNKNOWN_IMPURITY, _targets.UNKNOWN_IMPURITY])

    def test_peaks_name_keeps_length_for_expected_length_gate(self):
        # 空白峰占位后长度与报告峰数一致 → 「期望长度」闸门不误拒
        item = injection(u"SYS", u"1", [
            dict(peak(1850.0, no=1), name=u""),
            dict(peak(12954593.0, no=2), name=u"")])
        self.assertEqual(
            len(_import.pick_values(item, _targets.PICK_PEAKS_NAME)), 2)

    def test_peaks_name_is_not_numeric_normalized(self):
        # 名称类不走数值归一：不能把峰名变成 N/A 或去 .0
        item = injection(u"SYS", u"1", [dict(peak(1850.0, no=1), name=u"1")])
        self.assertEqual(_import.pick_values(item, _targets.PICK_PEAKS_NAME),
                         [u"1"])

    def test_peaks_name_respects_peak_filters(self):
        item = injection(u"SYS", u"1", [
            dict(peak(1850.0, rt=4.947, no=1), name=u"A"),
            dict(peak(12954593.0, rt=34.469, no=2), name=u"B"),
            dict(peak(3000.0, rt=36.450, no=3), name=u"C")])
        self.assertEqual(
            _import.pick_values(item, _targets.PICK_PEAKS_NAME, 2),
            [u"A", u"B"])
        self.assertEqual(
            _import.pick_values(item, _targets.PICK_PEAKS_NAME, rt=34.469),
            [u"B"])

    def test_unknown_rule_returns_empty(self):
        item = injection(u"SYS", u"1", [peak(1.0)])
        self.assertEqual(_import.pick_values(item, u"nonsense"), [])

    def test_area_sum_of_all_peaks(self):
        item = injection(u"Acc-200%-1", u"1", peaks_at(
            [(18739.0, 34.304), (1000.0, 33.7)]))
        self.assertEqual(_import.pick_values(item, _targets.PICK_PEAKS_AREA_SUM),
                         [19739.0])

    def test_area_sum_without_peaks_returns_empty(self):
        item = injection(u"Acc-200%-1", u"1", [])
        self.assertEqual(_import.pick_values(item, _targets.PICK_PEAKS_AREA_SUM),
                         [])

    def test_area_sum_rejects_peak_without_area(self):
        """缺面积的峰不进求和（当成 0 会得到一个"看着合理"的错值）"""
        item = injection(u"Acc-200%-1", u"1", [
            peak(18739.0), dict(peak(1.0), area=None)])
        self.assertEqual(_import.pick_values(item, _targets.PICK_PEAKS_AREA_SUM),
                         [])

    def test_rt_window_keeps_only_the_target_peak(self):
        """实测：RT≈24.3 的指定杂质峰（±0.5 窗口内只有它）"""
        item = injection(u"ACC-LOQ-SPIKED-1", u"1", peaks_at(REC_SPEC_PEAKS))
        self.assertEqual(
            _import.pick_values(item, _targets.PICK_PEAKS_AREA, rt=24.3),
            [14781.0])

    def test_rt_window_without_match_returns_empty(self):
        """窗口内没有峰 → 空（不做"取最近的峰"兜底猜测）"""
        item = injection(u"ACC-LOQ-SPIKED-1", u"1", peaks_at(REC_SPEC_PEAKS))
        self.assertEqual(
            _import.pick_values(item, _targets.PICK_PEAKS_AREA, rt=50.0), [])

    def test_main_peak_respects_the_rt_window(self):
        item = injection(u"ACC-LOQ-SPIKED-1", u"1", peaks_at(REC_SPEC_PEAKS))
        self.assertEqual(
            _import.pick_values(item, _targets.PICK_MAIN_PEAK_AREA, rt=34.4),
            [13469273.0])


class SelectPeaksTest(unittest.TestCase):
    """峰维度筛选：序号 → RT 窗口 → 取前 N 峰（顺序有意固定）"""

    PEAKS = peaks_at(REC_SPEC_PEAKS)

    def test_no_filter_keeps_all(self):
        self.assertEqual(len(_import.select_peaks(self.PEAKS)), 6)

    def test_peak_indexes_use_report_order(self):
        selected = _import.select_peaks(self.PEAKS, peak_indexes=(3, 6))
        self.assertEqual([peak["area"] for peak in selected],
                         [14781.0, 1850.0])

    def test_peak_indexes_out_of_range_yields_empty(self):
        self.assertEqual(
            _import.select_peaks(self.PEAKS, peak_indexes=(99,)), [])

    def test_rt_window_excludes_missing_rt(self):
        peaks = [peak(1.0, rt=None), peak(2.0, rt=24.3)]
        self.assertEqual(
            _import.select_peaks(peaks, rt=24.3), [peaks[1]])

    def test_rt_window_boundaries_are_inclusive(self):
        peaks = peaks_at([(1.0, 23.8), (2.0, 24.8), (3.0, 25.0)])
        selected = _import.select_peaks(peaks, rt=24.3)
        self.assertEqual([peak["area"] for peak in selected], [1.0, 2.0])

    def test_peaks_limit_takes_last_step(self):
        selected = _import.select_peaks(self.PEAKS, peaks_limit=2)
        self.assertEqual([peak["area"] for peak in selected],
                         [13469273.0, 21000.0])

    def test_indexes_then_limit(self):
        selected = _import.select_peaks(self.PEAKS, peak_indexes=(3, 4, 5),
                                        peaks_limit=2)
        self.assertEqual([peak["area"] for peak in selected],
                         [14781.0, 3000.0])


class SelectInjectionsTest(unittest.TestCase):
    """「第 N 针」维度（实测：`imp_loqN_area` = 第 N 针的 6 峰）"""

    def setUp(self):
        self.injections = [injection(u"LOQ", u"%d" % no, [peak(1.0)])
                           for no in (1, 2, 3)]

    def test_none_keeps_all_injections(self):
        self.assertEqual(len(_import.select_injections(self.injections)),
                         3)

    def test_zero_keeps_all_injections(self):
        self.assertEqual(len(_import.select_injections(self.injections, 0)), 3)

    def test_nth_injection_only(self):
        selected = _import.select_injections(self.injections, 2)
        self.assertEqual([item["injection_no"] for item in selected], [u"2"])

    def test_missing_injection_yields_empty(self):
        self.assertEqual(_import.select_injections(self.injections, 6), [])


class ResolveAnalysisTest(unittest.TestCase):
    """分析定位：**唯一命中才落位**，命中多个一律点名拒绝

    实测依据：WS-004 一张 WorkSheet 装 2 个样品、各自都有 `Ca`/`Mg`；
    WS-001 装 3 个样品、同样各有 `Ca`/`Mg`。早期"取第一个命中"会**静默写错样品**。
    """

    def setUp(self):
        self.ca_a = FakeAnalysis(u"Ca", u"BH2O260828001")
        self.ca_b = FakeAnalysis(u"Ca", u"BH2O260828002")
        self.mg_a = FakeAnalysis(u"Mg", u"BH2O260828001")
        self.worksheet = FakeWorksheet([self.ca_a, self.mg_a, self.ca_b])

    def test_find_analyses_returns_all_matches(self):
        self.assertEqual(_import.find_analyses(self.worksheet, u"Ca"),
                         [self.ca_a, self.ca_b])

    def test_single_match_is_used(self):
        """只有唯一命中时照用（WS-006 单样品路径 —— 必须零变化）"""
        only = FakeAnalysis(u"Mg", u"BH2O260828002")
        worksheet = FakeWorksheet([only, FakeAnalysis(u"Ca", u"BH2O260828001")])
        analysis, status, message = _import.resolve_analysis(worksheet, u"Mg")
        self.assertIs(analysis, only)
        self.assertEqual(status, u"")
        self.assertEqual(message, u"")

    def test_missing_keyword(self):
        analysis, status, message = _import.resolve_analysis(self.worksheet, u"Nope")
        self.assertIsNone(analysis)
        self.assertEqual(status, u"MISSING_ANALYSIS")
        self.assertEqual(message, u"")

    def test_ambiguous_without_sample_id_is_rejected_with_candidates(self):
        analysis, status, message = _import.resolve_analysis(self.worksheet, u"Ca")
        self.assertIsNone(analysis)
        self.assertEqual(status, u"AMBIGUOUS_ANALYSIS")
        self.assertIn(u"BH2O260828001", message)
        self.assertIn(u"BH2O260828002", message)
        self.assertIn(u"命中 2 个分析", message)

    def test_sample_id_narrows_to_exactly_one(self):
        analysis, status, message = _import.resolve_analysis(
            self.worksheet, u"Ca", sample_id=u"BH2O260828002")
        self.assertIs(analysis, self.ca_b)
        self.assertEqual(status, u"")
        self.assertEqual(message, u"")

    def test_sample_id_not_in_candidates_is_rejected(self):
        analysis, status, message = _import.resolve_analysis(
            self.worksheet, u"Ca", sample_id=u"OTHER")
        self.assertIsNone(analysis)
        self.assertEqual(status, u"AMBIGUOUS_ANALYSIS")
        self.assertIn(u"剩 0 个", message)

    def test_duplicate_on_the_same_sample_is_still_rejected(self):
        """同一样品上有两个同名分析（复检）→ 给 sample_id 也仍然拒绝"""
        worksheet = FakeWorksheet([FakeAnalysis(u"Ca", u"S-1"),
                                   FakeAnalysis(u"Ca", u"S-1")])
        analysis, status, message = _import.resolve_analysis(
            worksheet, u"Ca", sample_id=u"S-1")
        self.assertIsNone(analysis)
        self.assertEqual(status, u"AMBIGUOUS_ANALYSIS")
        self.assertIn(u"剩 2 个", message)

    def test_unknown_sample_is_named_explicitly(self):
        worksheet = FakeWorksheet([FakeAnalysis(u"Ca", u"S-1"),
                                   FakeAnalysis(u"Ca", None)])
        analysis, status, message = _import.resolve_analysis(worksheet, u"Ca")
        self.assertIsNone(analysis)
        self.assertIn(u"(未知样品)", message)


class PageConfigTest(unittest.TestCase):
    """页面配置 → 目标位：合法行转换 + 非法行**点名**（不静默跳过）"""

    def test_valid_row_is_converted(self):
        target, problem = _targets.build_target(PAGE_ROWS[3])
        self.assertEqual(problem, u"")
        self.assertEqual(target[u"sample_name"], u"SYS")
        self.assertEqual(target[u"pick"], u"peaks.resolution")
        self.assertEqual(target[u"decimals"], 1)
        self.assertEqual(target[u"expected_length"], 16)
        self.assertEqual(target[u"title"], u"各峰分离度")

    def test_empty_decimals_means_raw(self):
        target, _problem = _targets.build_target(PAGE_ROWS[0])
        self.assertIsNone(target[u"decimals"])

    def test_zero_length_means_no_check(self):
        row = dict(PAGE_ROWS[0], acq_length=0)
        target, _problem = _targets.build_target(row)
        self.assertIsNone(target[u"expected_length"])

    def test_nth_injection_row_is_converted(self):
        target, problem = _targets.build_target(LOQ_ROWS[0])
        self.assertEqual(problem, u"")
        self.assertEqual(target[u"sample_name"], u"LOQ")
        self.assertEqual(target[u"pick"], u"peaks.area")
        self.assertEqual(target[u"injection"], 1)
        self.assertIsNone(target[u"peaks_limit"])

    def test_peaks_limit_row_is_converted(self):
        target, _problem = _targets.build_target(LIN_ROWS[0])
        self.assertEqual(target[u"peaks_limit"], 3)
        self.assertIsNone(target[u"injection"])

    def test_absent_injection_and_peaks_mean_all(self):
        """老配置（没有这两列）必须仍然合法，语义 = 全部针 / 全部峰"""
        target, _problem = _targets.build_target(PAGE_ROWS[0])
        self.assertIsNone(target[u"injection"])
        self.assertIsNone(target[u"peaks_limit"])

    def test_zero_injection_and_peaks_mean_all(self):
        row = dict(PAGE_ROWS[0], acq_injection=0, acq_peaks=0)
        target, _problem = _targets.build_target(row)
        self.assertIsNone(target[u"injection"])
        self.assertIsNone(target[u"peaks_limit"])

    def test_negative_injection_is_rejected(self):
        row = dict(PAGE_ROWS[0], acq_injection=-1)
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"第 N 针", problem)

    def test_negative_peaks_is_rejected(self):
        row = dict(PAGE_ROWS[0], acq_peaks=-1)
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"取前 N 峰", problem)

    def test_step2_pick_rules_are_in_the_controlled_vocabulary(self):
        for rule in (_targets.PICK_PEAKS_AREA, _targets.PICK_PEAKS_SN,
                     _targets.PICK_PEAKS_NAME):
            self.assertIn(rule, _targets.PICK_RULES)
            row = dict(PAGE_ROWS[0], acq_pick=rule)
            target, problem = _targets.build_target(row)
            self.assertIsNotNone(target, problem)

    def test_name_pick_rule_is_the_only_string_rule(self):
        # 名称类是唯一一条字符串规则；其余规则必须仍走数值语义
        self.assertEqual(_targets.NAME_PICK_RULES,
                         (_targets.PICK_PEAKS_NAME,))
        self.assertIn(_targets.PICK_PEAKS_NAME, _targets.PICK_RULES)

    def test_step2_fixture_rows_are_all_valid(self):
        self.assertEqual(len(page_targets(LOQ_ROWS)), len(LOQ_ROWS))
        self.assertEqual(len(page_targets(LIN_ROWS)), len(LIN_ROWS))

    def test_rt_and_peak_indexes_default_to_none(self):
        target, _problem = _targets.build_target(PAGE_ROWS[0])
        self.assertIsNone(target[u"rt"])
        self.assertIsNone(target[u"peak_indexes"])

    def test_rt_column_is_converted(self):
        # 来源 `ACC-LOQ-SPIKED-1` 是**改名前的现状名**，所以会带一条"不在受控
        # 角色词表"的告警（改名成 `REC-SPEC-LOQ-1` 后自动消失）—— 这里只看转换结果
        target, _problem = _targets.build_target(REC_ROWS[0])
        self.assertEqual(target[u"rt"], 24.3)

    def test_peak_indexes_are_parsed(self):
        for text, expected in ((u"3,6,7,8,15,16", (3, 6, 7, 8, 15, 16)),
                               (u"3, 6", (3, 6)),
                               (u"3，6", (3, 6)),
                               (u"6,3,3", (3, 6)),
                               (u"", None)):
            row = dict(SPEC_ROWS[0], acq_peak_indexes=text)
            target, problem = _targets.build_target(row)
            self.assertIsNotNone(target, problem)
            self.assertEqual(target[u"peak_indexes"], expected, text)

    def test_negative_rt_is_rejected(self):
        row = dict(PAGE_ROWS[0], acq_rt=-1)
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"目标 RT", problem)

    def test_non_numeric_peak_indexes_are_rejected(self):
        row = dict(SPEC_ROWS[0], acq_peak_indexes=u"3,x")
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"峰序号清单", problem)

    def test_zero_peak_index_is_rejected(self):
        """峰序号 1 起；`0` 是笔误 → 点名拒绝（不猜成 1）"""
        row = dict(SPEC_ROWS[0], acq_peak_indexes=u"0,3")
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"峰序号清单", problem)

    def test_empty_segment_in_peak_indexes_is_rejected(self):
        row = dict(SPEC_ROWS[0], acq_peak_indexes=u"3,,6")
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"峰序号清单", problem)

    def test_area_sum_rule_is_in_the_controlled_vocabulary(self):
        self.assertIn(_targets.PICK_PEAKS_AREA_SUM, _targets.PICK_RULES)
        row = dict(PAGE_ROWS[0], acq_pick=_targets.PICK_PEAKS_AREA_SUM)
        target, problem = _targets.build_target(row)
        self.assertIsNotNone(target, problem)

    def test_rec_and_spec_fixture_rows_are_all_valid(self):
        self.assertEqual(len(page_targets(REC_ROWS)), len(REC_ROWS))
        self.assertEqual(len(page_targets(SPEC_ROWS)), len(SPEC_ROWS))

    def test_missing_source_is_rejected(self):
        row = dict(PAGE_ROWS[0], acq_source_sample=u"")
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"来源", problem)

    def test_unknown_pick_is_rejected(self):
        row = dict(PAGE_ROWS[0], acq_pick=u"main_peak.areaaa")
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"取值规则", problem)

    def test_unknown_decimals_is_rejected(self):
        row = dict(PAGE_ROWS[0], acq_decimals=u"9")
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"写法", problem)

    def test_negative_length_is_rejected(self):
        row = dict(PAGE_ROWS[0], acq_length=-1)
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"期望长度", problem)

    def test_incomplete_row_key_is_rejected(self):
        row = dict(PAGE_ROWS[0], calc_keyword=u"")
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"行键", problem)

    def test_source_outside_vocabulary_warns_but_keeps_row(self):
        row = dict(PAGE_ROWS[0], acq_source_sample=u"STD_1")
        target, problem = _targets.build_target(row)
        self.assertIsNotNone(target)
        self.assertIn(u"受控角色词表", problem)

    def test_batch_sample_name_is_accepted_silently(self):
        row = dict(PAGE_ROWS[0], acq_source_sample=u"ICPNB000000572-052-P-SPL-1")
        target, problem = _targets.build_target(row)
        self.assertIsNotNone(target)
        self.assertEqual(problem, u"")

    def test_page_fixture_rows_are_all_valid(self):
        self.assertEqual(len(page_targets()), len(PAGE_ROWS))


class PlanRowsTest(unittest.TestCase):
    def test_rows_follow_target_table_order(self):
        payload = report_payload(
            # 针号故意打乱：落位必须按 injection_no 升序还原
            std1_injections(areas=[64814.0, 64915.0, 65152.0, 65231.0,
                                   65339.0, 65572.0],
                            order=[2, 1, 3, 4, 5, 6]),
            std2_injections(),
            sys_group=[sys_injection()],
        )
        rows, warnings = _import.plan_rows(payload, page_targets())
        self.assertEqual(warnings, [])
        self.assertEqual(
            [row[u"interim_keyword"] for row in rows],
            [u"imp_std1_area", u"imp_std2_area", u"g_rt",
             u"imp_sep_res_before"])

        first = rows[0]
        self.assertEqual(first[u"analysis_keyword"], u"imp_sys_suit")
        self.assertEqual(first[u"injection_count"], 6)
        self.assertEqual(first[u"value_text"],
                         u'["64915", "64814", "65152", "65231", "65339", '
                         u'"65572"]')
        self.assertEqual(rows[1][u"value_text"], u'["67470", "67774"]')

        # 该针整列：按峰序；首峰无前峰 → N/A
        g_rt = json.loads(rows[2][u"value_text"])
        self.assertEqual(len(g_rt), 16)
        self.assertEqual(g_rt[0], u"4.947")
        resolutions = json.loads(rows[3][u"value_text"])
        self.assertEqual(len(resolutions), 16)
        self.assertEqual(resolutions[0], u"N/A")
        self.assertEqual(resolutions[1], u"58.6")

    def test_missing_sample_warns_and_skips(self):
        payload = report_payload(std1_injections(), None)
        rows, warnings = _import.plan_rows(payload, page_targets())
        self.assertEqual(len(rows), 1)
        self.assertTrue(warnings)
        self.assertIn(u"STD-2", warnings[0])

    def test_injection_without_peak_rejects_whole_target(self):
        """六针里有一针无峰 → 只有 5 个值 → 长度闸门拦下整条目标位（宁缺勿错）"""
        broken = std1_injections()[:-1] + [injection(u"STD-1", u"6", [])]
        payload = report_payload(broken, std2_injections())
        rows, warnings = _import.plan_rows(payload, page_targets())
        self.assertEqual([row[u"interim_keyword"] for row in rows],
                         [u"imp_std2_area"])
        self.assertTrue(any(u"无峰" in w for w in warnings))
        self.assertTrue(
            any(u"imp_std1_area" in w and u"不符" in w for w in warnings))

    def test_partial_report_is_rejected_by_length_guard(self):
        """局部报告（实测 `1 SYS-plate.pdf` 只有 1 针 STD-1）不得覆盖完整数组"""
        payload = report_payload(
            [injection(u"STD-1", u"1", [peak(64915.0)])],
            std2_injections(),
            sys_group=[sys_injection()],
        )
        rows, warnings = _import.plan_rows(payload, page_targets())
        self.assertEqual(
            [row[u"interim_keyword"] for row in rows],
            [u"imp_std2_area", u"g_rt", u"imp_sep_res_before"])
        self.assertTrue(
            any(u"imp_std1_area" in w and u"不符" in w for w in warnings))

    def test_no_samples_yields_no_rows(self):
        rows, warnings = _import.plan_rows(report_payload(None, None),
                                           page_targets())
        self.assertEqual(rows, [])
        self.assertEqual(len(warnings), len(PAGE_ROWS))

    def test_no_targets_yields_no_rows(self):
        """页面没勾选任何目标位 → 不落位（且由调用方给出明确告警）"""
        rows, warnings = _import.plan_rows(report_payload(
            std1_injections(), std2_injections(), [sys_injection()]), [])
        self.assertEqual(rows, [])
        self.assertEqual(warnings, [])


class PlanRowsStep2Test(unittest.TestCase):
    """Step 2 的两个新维度：按第 N 针 + 每针取前 N 峰"""

    #: M0 §6.3 的轴序证据（站点现值）：第 1 针 / 第 2 针的 6 峰面积
    LOQ1_AREAS = [7672.0, 6688.0, 6296.0, 7728.0, 4199.0, 5645.0]
    LOQ2_AREAS = [7576.0, 6607.0, 6133.0, 7249.0, 4057.0, 5528.0]
    #: 实测 `lod_sn1` = 第 1 针 6 峰的 USP s/n
    LOD1_SNS = [7.0, 8.0, 7.0, 10.0, 10.0, 10.0]

    def test_nth_injection_takes_that_injection_only(self):
        payload = grouped_payload(**{
            u"LOQ": [injection(u"LOQ", u"1", peaks_from(self.LOQ1_AREAS)),
                     injection(u"LOQ", u"2", peaks_from(self.LOQ2_AREAS))],
            u"LOD": [injection(u"LOD", u"1", peaks_from(
                [1000.0] * 6, sns=self.LOD1_SNS))],
        })
        rows, warnings = _import.plan_rows(payload, page_targets(LOQ_ROWS))
        self.assertEqual(warnings, [])
        self.assertEqual(
            [row[u"interim_keyword"] for row in rows],
            [u"imp_loq1_area", u"imp_loq2_area", u"lod_sn1"])
        self.assertEqual(json.loads(rows[0][u"value_text"]),
                         [u"7672", u"6688", u"6296", u"7728", u"4199", u"5645"])
        self.assertEqual(json.loads(rows[1][u"value_text"]),
                         [u"7576", u"6607", u"6133", u"7249", u"4057", u"5528"])
        self.assertEqual(json.loads(rows[2][u"value_text"]),
                         [u"7", u"8", u"7", u"10", u"10", u"10"])

    def test_missing_injection_warns_and_skips(self):
        """报告里只有第 1 针，而页面要求第 2 针 → 点名跳过（不猜、不取别的针）"""
        payload = grouped_payload(**{
            u"LOQ": [injection(u"LOQ", u"1", peaks_from(self.LOQ1_AREAS))],
        })
        rows, warnings = _import.plan_rows(payload, page_targets(LOQ_ROWS))
        self.assertEqual([row[u"interim_keyword"] for row in rows],
                         [u"imp_loq1_area"])
        self.assertTrue(any(u"没有第 2 针" in w and u"imp_loq2_area" in w
                            for w in warnings), warnings)

    def test_peaks_limit_gives_narrower_column_than_full(self):
        """同一份报告（1 针 6 峰）→ `imp_linearity` 3 值、`_shared` 6 值"""
        payload = grouped_payload(**{
            u"LOQ(Line-1)": [injection(u"LOQ(Line-1)", u"1",
                                       peaks_from(self.LOQ1_AREAS))],
        })
        rows, warnings = _import.plan_rows(payload, page_targets(LIN_ROWS))
        self.assertEqual(warnings, [])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][u"analysis_keyword"], u"imp_linearity")
        self.assertEqual(rows[1][u"analysis_keyword"], u"imp_linearity_shared")
        narrow = json.loads(rows[0][u"value_text"])
        full = json.loads(rows[1][u"value_text"])
        self.assertEqual(len(narrow), 3)
        self.assertEqual(len(full), 6)
        self.assertEqual(narrow, full[:3])

    def test_peaks_limit_below_expected_length_is_rejected(self):
        """前 N 峰取完仍与映射表长度不符 → 长度闸门拦下（宁缺勿错）"""
        payload = grouped_payload(**{
            u"LOQ(Line-1)": [injection(u"LOQ(Line-1)", u"1",
                                       peaks_from(self.LOQ1_AREAS))],
        })
        # 映射表要 6 值，但页面把「取前 N 峰」错填成 3 → 3 != 6 → 跳过
        row = dict(LIN_ROWS[0], acq_length=6)
        rows, warnings = _import.plan_rows(payload, page_targets([row]))
        self.assertEqual(rows, [])
        self.assertTrue(any(u"imp_lin_a1" in w and u"不符" in w
                            for w in warnings), warnings)

    def test_same_interim_keyword_on_two_analyses_keeps_distinct_values(self):
        """`imp_lin_a1` 同时存在于两个分析 → 两行必须各自保留自己的值"""
        payload = grouped_payload(**{
            u"LOQ(Line-1)": [injection(u"LOQ(Line-1)", u"1",
                                       peaks_from(self.LOQ1_AREAS))],
        })
        rows, _warnings = _import.plan_rows(payload, page_targets(LIN_ROWS))
        self.assertEqual([row[u"interim_keyword"] for row in rows],
                         [u"imp_lin_a1", u"imp_lin_a1"])
        self.assertNotEqual(rows[0][u"value"], rows[1][u"value"])
        self.assertEqual(len(rows[0][u"value"]), 3)
        self.assertEqual(len(rows[1][u"value"]), 6)


class PlanRowsFilterTest(unittest.TestCase):
    """「目标 RT」/「面积求和」/「峰序号清单」三个新维度的端到端落位"""

    def test_rt_window_gives_the_specified_impurity_area(self):
        """实测 `imp_rec_spec.g_area` = 各进样里 RT≈24.3 的峰面积（12/12 一致）"""
        payload = grouped_payload(**{
            u"ACC-LOQ-SPIKED-1": [injection(u"ACC-LOQ-SPIKED-1", u"1",
                                           peaks_at(REC_SPEC_PEAKS))],
            u"Acc-200%-1": [injection(u"Acc-200%-1", u"1",
                                      peaks_at([(18739.0, 34.304)]))],
        })
        rows, warnings = _import.plan_rows(payload, page_targets(REC_ROWS))
        self.assertEqual(warnings, [])
        self.assertEqual([row[u"value"] for row in rows],
                         [[u"14781"], [u"18739"]])

    def test_area_sum_sums_every_reported_peak(self):
        payload = grouped_payload(**{
            u"ACC-LOQ-SPIKED-1": [injection(u"ACC-LOQ-SPIKED-1", u"1",
                                           peaks_at(REC_SPEC_PEAKS))],
            u"Acc-200%-1": [injection(u"Acc-200%-1", u"1", peaks_at(
                [(18739.0, 34.304), (1000.0, 33.7)]))],
        })
        rows, _warnings = _import.plan_rows(
            payload, page_targets([REC_ROWS[1]]))
        self.assertEqual(rows[0][u"value"], [u"19739"])

    def test_specificity_takes_the_six_substance_peaks(self):
        """实测 `imp_specificity.imp_spec_sample_sol` 取自 SYS 16 峰里的 3,6,7,8,15,16"""
        payload = grouped_payload(**{u"SYS": [sys_injection()]})
        rows, warnings = _import.plan_rows(payload, page_targets(SPEC_ROWS))
        self.assertEqual(warnings, [])
        self.assertEqual(
            json.loads(rows[0][u"value_text"]),
            [u"24.372", u"33.781", u"34.469", u"36.467", u"56.271", u"58.129"])

    def test_rt_window_without_match_is_skipped_not_guessed(self):
        """窗口筛完是空 → 该针无峰 → 跳过（不取别的峰凑数）"""
        payload = grouped_payload(**{
            u"ACC-LOQ-SPIKED-1": [injection(u"ACC-LOQ-SPIKED-1", u"1",
                                           peaks_at(REC_SPEC_PEAKS))],
        })
        row = dict(REC_ROWS[0], acq_rt=50.0)
        rows, warnings = _import.plan_rows(payload, page_targets([row]))
        self.assertEqual(rows, [])
        self.assertTrue(any(u"无峰" in w for w in warnings), warnings)

    def test_peak_index_missing_from_report_changes_length_and_is_rejected(self):
        """序号清单里有一个报告没有的序号 → 只剩 5 值 → 长度闸门拦下（不写半个）"""
        payload = grouped_payload(**{u"SYS": [sys_injection()]})
        row = dict(SPEC_ROWS[0], acq_peak_indexes=u"3,6,7,8,15,17")
        rows, warnings = _import.plan_rows(payload, page_targets([row]))
        self.assertEqual(rows, [])
        self.assertTrue(any(u"不符" in w for w in warnings), warnings)

    def test_extra_index_beyond_report_length_is_ignored_safely(self):
        """多写一个报告里没有的序号、但其余 6 个都在 → 6 值照写（数量对得上）"""
        payload = grouped_payload(**{u"SYS": [sys_injection()]})
        row = dict(SPEC_ROWS[0], acq_peak_indexes=u"3,6,7,8,15,16,20")
        rows, warnings = _import.plan_rows(payload, page_targets([row]))
        self.assertEqual(warnings, [])
        self.assertEqual(len(json.loads(rows[0][u"value_text"])), 6)


class ShouldWriteTest(unittest.TestCase):
    """覆盖门禁：现值与本次不同（DIFF）默认不写（自动导入无人复核）"""

    def test_match_and_new_are_always_writable(self):
        self.assertTrue(_import.should_write(u"MATCH"))
        self.assertTrue(_import.should_write(u"NEW"))
        self.assertTrue(_import.should_write(u"MATCH", allow_overwrite=False))

    def test_diff_requires_explicit_overwrite(self):
        self.assertFalse(_import.should_write(u"DIFF"))
        self.assertFalse(_import.should_write(u"DIFF", allow_overwrite=False))
        self.assertTrue(_import.should_write(u"DIFF", allow_overwrite=True))

    def test_other_statuses_are_not_writable(self):
        for status in (u"MISSING_ANALYSIS", u"MISSING_INTERIM",
                       u"AMBIGUOUS_ANALYSIS", u"SLOT_SKIPPED",
                       u"SLOT_LAYOUT_ERROR", u"WRITTEN"):
            self.assertFalse(_import.should_write(status, allow_overwrite=True),
                             status)


class FakeAttachmentFile(object):
    def __init__(self, filename):
        self.filename = filename


class FakeAttachmentField(object):
    def __init__(self, value):
        self._value = value

    def get(self, obj):
        return self._value


class FakeAttachment(object):
    """SENAITE 真实形态：`Title()` / `getId()` 是自增 id，文件名只在上传文件里

    `style` 用来模拟三种可能的字段读法（基线差异）：字段 / 属性 / 访问器。
    """

    def __init__(self, attachment_id, filename=None, title=None,
                 style=u"field"):
        self.portal_type = "Attachment"
        self._id = attachment_id
        self._title = attachment_id if title is None else title
        self._file = FakeAttachmentFile(filename)
        self._style = style

    def Title(self):
        return self._title

    def getId(self):
        return self._id

    def getField(self, name):
        if self._style != u"field" or name != "AttachmentFile":
            return None
        return FakeAttachmentField(self._file)

    @property
    def AttachmentFile(self):
        return self._file if self._style == u"attribute" else None

    def getAttachmentFile(self):
        return self._file if self._style == u"getter" else None


class FakeAttachmentHost(object):
    def __init__(self, children):
        self._children = list(children)

    def objectValues(self):
        return list(self._children)


class FindAttachmentTest(unittest.TestCase):
    """报告 PDF 去重：附件 `Title()` 是自增 id，必须再比上传文件名"""

    def test_matches_uploaded_filename(self):
        attachment = FakeAttachment(u"attachment-23", u"1 SYS.pdf")
        host = FakeAttachmentHost([attachment])
        self.assertIs(_import.find_attachment(host, u"1 SYS.pdf"), attachment)

    def test_matches_title(self):
        attachment = FakeAttachment(u"attachment-24", u"other.pdf",
                                    title=u"WS-007_1 SYS.pdf")
        host = FakeAttachmentHost([attachment])
        self.assertIs(_import.find_attachment(host, u"WS-007_1 SYS.pdf"), attachment)

    def test_matches_full_path_title(self):
        """自动导入给的 title 是**容器内全路径**，附件里存的是裸文件名"""
        attachment = FakeAttachment(u"attachment-32", u"WS-007_1 SYS.pdf")
        host = FakeAttachmentHost([attachment])
        self.assertIs(
            _import.find_attachment(host, u"/data/dcu_auto_import/WS-007_1 SYS.pdf"),
            attachment)

    def test_matches_windows_path_title(self):
        attachment = FakeAttachment(u"attachment-33", u"WS-007_1 SYS.pdf")
        host = FakeAttachmentHost([attachment])
        self.assertIs(
            _import.find_attachment(host, u"C:\\inbox\\WS-007_1 SYS.pdf"),
            attachment)

    def test_matches_when_file_read_via_attribute(self):
        attachment = FakeAttachment(u"attachment-34", u"WS-007_1 SYS.pdf",
                                    style=u"attribute")
        host = FakeAttachmentHost([attachment])
        self.assertIs(_import.find_attachment(host, u"WS-007_1 SYS.pdf"), attachment)

    def test_matches_when_file_read_via_getter(self):
        attachment = FakeAttachment(u"attachment-35", u"WS-007_1 SYS.pdf",
                                    style=u"getter")
        host = FakeAttachmentHost([attachment])
        self.assertIs(_import.find_attachment(host, u"WS-007_1 SYS.pdf"), attachment)

    def test_name_key_strips_directory(self):
        self.assertEqual(
            _import._name_key(u"/data/x/WS-007_1 SYS.pdf"), u"WS-007_1 SYS.pdf")
        self.assertEqual(
            _import._name_key(u"C:\\x\\WS-007_1 SYS.pdf"), u"WS-007_1 SYS.pdf")
        self.assertEqual(_import._name_key(u"WS-007_1 SYS.pdf"),
                         u"WS-007_1 SYS.pdf")

    def test_skips_non_attachment_children(self):
        other = FakeAttachment(u"attachment-25", u"1 SYS.pdf")
        other.portal_type = "WorksheetTemplate"
        host = FakeAttachmentHost([other])
        self.assertIsNone(_import.find_attachment(host, u"1 SYS.pdf"))

    def test_returns_none_when_name_not_found(self):
        host = FakeAttachmentHost([FakeAttachment(u"attachment-26", u"2 LOQ.pdf")])
        self.assertIsNone(_import.find_attachment(host, u"1 SYS.pdf"))

    def test_empty_name_returns_none(self):
        host = FakeAttachmentHost([FakeAttachment(u"attachment-27", u"")])
        self.assertIsNone(_import.find_attachment(host, u""))


class DescribeValueTest(unittest.TestCase):
    """告警里的现值要短（数组可达上千字符）"""

    def test_short_value_is_kept_as_is(self):
        self.assertEqual(_import.describe_value(u'["1", "2"]'), u'["1", "2"]')

    def test_long_value_is_truncated_with_length(self):
        text = u"[" + u", ".join([u'"1234"'] * 100) + u"]"
        described = _import.describe_value(text)
        self.assertLess(len(described), len(text))
        self.assertIn(u"共 %d 字符" % len(text), described)


class CompareValueTest(unittest.TestCase):
    def test_new_when_current_empty(self):
        status, _same = _import.compare_value(u"", u'["64915"]')
        self.assertEqual(status, u"NEW")

    def test_match(self):
        status, _same = _import.compare_value(
            u'["64915", "64814"]', u'["64915", "64814"]')
        self.assertEqual(status, u"MATCH")

    def test_diff_but_same_ignoring_spaces(self):
        status, same = _import.compare_value(
            u'["64915","64814"]', u'["64915", "64814"]')
        self.assertEqual(status, u"DIFF")
        self.assertTrue(same)

    def test_real_diff(self):
        status, same = _import.compare_value(
            u'["64915", "64814"]', u'["64915", "64815"]')
        self.assertEqual(status, u"DIFF")
        self.assertFalse(same)


class ParseDropRtTest(unittest.TestCase):
    """页面「排除 RT」的解析：非法必须**点名拒绝整行**（不猜）"""

    def test_parses_and_sorts(self):
        self.assertEqual(_targets.parse_drop_rt(u"47.48, 10.12"),
                         (10.12, 47.48))

    def test_empty_is_no_filter(self):
        self.assertEqual(_targets.parse_drop_rt(u""), ())

    def test_chinese_comma_and_spaces(self):
        self.assertEqual(_targets.parse_drop_rt(u"10.12，47.48"), (10.12, 47.48))

    def test_garbage_is_rejected(self):
        for text in (u"47.48,,10.12", u"47.48,a", u"0", u"-3"):
            self.assertIsNone(_targets.parse_drop_rt(text), text)

    def test_page_row_with_bad_drop_rt_is_named(self):
        row = dict(ROW_CHROM_SLOT1, acq_drop_rt=u"47.48,x")
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"排除 RT", problem)


class RowSyncPageConfigTest(unittest.TestCase):
    """行键列 / 行槽位必须成对出现；成对时进入目标位定义"""

    def test_slot_without_row_key_is_rejected(self):
        row = dict(ROW_CHROM_SLOT1)
        row.pop("acq_row_key")
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"行键列", problem)

    def test_row_key_without_slot_is_rejected(self):
        row = dict(ROW_CHROM_SLOT1)
        row.pop("acq_slot")
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"行槽位", problem)

    def test_pair_is_carried_into_target(self):
        target, _problem = _targets.build_target(ROW_CHROM_SLOT1)
        self.assertEqual(target[u"row_key"], u"g_sample_id")
        self.assertEqual(target[u"slots"], (u"1",))
        self.assertEqual(target[u"sources"], (u"ACC-100%-SPIKED-1(T0)",))
        self.assertEqual(target[u"drop_rt"], (47.48,))

    def test_multi_slot_lists_are_paired(self):
        """一个目标列要写多个槽位：两个清单按位置一一对应"""
        target, _problem = _targets.build_target(ROW_CHROM_ALL_SLOTS)
        self.assertEqual(len(target[u"slots"]), 6)
        self.assertEqual(target[u"sources"][-1], u"ACC-100%-SPIKED-6")
        self.assertEqual(target[u"slots"][-1], u"6")

    def test_unequal_lists_are_rejected(self):
        row = dict(ROW_CHROM_ALL_SLOTS)
        row["acq_slot"] = u"1,2,3"
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"不等长", problem)

    def test_empty_segment_in_slot_list_is_rejected(self):
        row = dict(ROW_CHROM_SLOT1, acq_slot=u"1,,2")
        target, problem = _targets.build_target(row)
        self.assertIsNone(target)
        self.assertIn(u"行槽位", problem)

    def test_plain_row_has_no_slot(self):
        """Step 1/2 的整列目标位不得被这套配置影响"""
        target, _problem = _targets.build_target(REC_ROWS[0])
        self.assertEqual(target[u"slots"], ())
        self.assertEqual(target[u"sources"], ())
        self.assertEqual(target[u"row_key"], u"")
        self.assertIsNone(target[u"drop_rt"])


class SelectPeaksDropRtTest(unittest.TestCase):
    """「排除 RT」维度：只剔命中者，±0.5 之外的邻峰留着"""

    def setUp(self):
        # 实测 `ACC-100%-SPIKED-1(T0)` 的形态：小峰 47.479 被站点剔掉，
        # 邻峰 45.985 / 48.419（差 1.5 / 0.94 min）必须留着
        self.peaks = peaks_at([(1609.0, 4.946), (1065.0, 47.479),
                               (1659.0, 45.985), (3288.0, 48.419),
                               (12818597.0, 34.471)])

    def test_drop_rt_removes_only_the_matched_peak(self):
        kept = _import.select_peaks(self.peaks, drop_rt=(47.48,))
        self.assertEqual([p["rt"] for p in kept],
                         [4.946, 45.985, 48.419, 34.471])

    def test_drop_rt_none_keeps_everything(self):
        kept = _import.select_peaks(self.peaks, drop_rt=None)
        self.assertEqual(len(kept), 5)

    def test_peak_without_rt_is_not_dropped(self):
        peaks = [peak(1000.0, rt=None), peak(2000.0, rt=34.5)]
        kept = _import.select_peaks(peaks, drop_rt=(34.5,))
        self.assertEqual([p["area"] for p in kept], [1000.0])

    def test_drop_rt_applies_before_peaks_limit(self):
        """先剔再截：否则"前 N 峰"会把该剔的峰算进名额"""
        kept = _import.select_peaks(self.peaks, drop_rt=(47.48,), peaks_limit=2)
        self.assertEqual([p["rt"] for p in kept], [4.946, 45.985])


class FindSlotRunsTest(unittest.TestCase):
    """行键数组里定位槽位的**连续块**"""

    def test_single_run(self):
        keys = [u"1", u"1", u"2", u"2", u"2"]
        self.assertEqual(_import.find_slot_runs(keys, u"1"), [(0, 2)])
        self.assertEqual(_import.find_slot_runs(keys, u"2"), [(2, 5)])

    def test_missing_slot(self):
        self.assertEqual(_import.find_slot_runs([u"1", u"2"], u"3"), [])

    def test_multiple_runs_are_reported(self):
        keys = [u"1", u"2", u"1"]
        self.assertEqual(_import.find_slot_runs(keys, u"1"), [(0, 1), (2, 3)])

    def test_values_are_compared_as_text(self):
        self.assertEqual(_import.find_slot_runs([1, 1, 2], u"1"), [(0, 2)])


class ReadInterimArrayTest(unittest.TestCase):
    """读数组 interim：缺失 / 非数组 → None（不可当布局用）"""

    def test_missing_keyword(self):
        analysis = FakeAnalysis(u"imp_chrom")
        self.assertIsNone(_import.read_interim_array(analysis, u"g_rt"))

    def test_json_array(self):
        analysis = FakeAnalysis(u"imp_chrom", None, [
            {"keyword": u"g_rt", "value": u'["4.946", "20.019"]'}])
        self.assertEqual(_import.read_interim_array(analysis, u"g_rt"),
                         [u"4.946", u"20.019"])

    def test_empty_value_is_empty_list(self):
        analysis = FakeAnalysis(u"imp_chrom", None, [
            {"keyword": u"g_rt", "value": u""}])
        self.assertEqual(_import.read_interim_array(analysis, u"g_rt"), [])

    def test_scalar_value_is_rejected(self):
        analysis = FakeAnalysis(u"imp_chrom", None, [
            {"keyword": u"g_rt", "value": u"4.946"}])
        self.assertIsNone(_import.read_interim_array(analysis, u"g_rt"))


class GroupPlanRowsTest(unittest.TestCase):
    """整列行与槽位行互斥；槽位行按 (分析, interim) 收在一组"""

    def _row(self, slot, interim=u"g_rt", analysis=u"imp_chrom"):
        return {u"analysis_keyword": analysis, u"interim_keyword": interim,
                u"sample_name": u"SRC", u"title": u"t", u"injection_count": 1,
                u"value": [u"1"], u"value_text": u'["1"]',
                u"row_key": u"g_sample_id", u"slot": slot}

    def test_slot_rows_share_one_unit(self):
        warnings = []
        units = _import.group_plan_rows(
            [self._row(u"1"), self._row(u"2")], warnings)
        self.assertEqual(warnings, [])
        self.assertEqual(len(units), 1)
        self.assertEqual(len(units[0][1][u"slots"]), 2)

    def test_whole_and_slot_rows_are_rejected(self):
        whole = dict(self._row(u""), slot=u"")
        warnings = []
        units = _import.group_plan_rows([whole, self._row(u"1")], warnings)
        self.assertEqual(units, [])
        self.assertTrue(any(u"互斥" in w for w in warnings), warnings)

    def test_two_whole_rows_keep_the_first(self):
        whole = dict(self._row(u""), slot=u"")
        warnings = []
        units = _import.group_plan_rows([whole, dict(whole)], warnings)
        self.assertEqual(len(units), 1)
        self.assertTrue(any(u"多个整列" in w for w in warnings), warnings)


class PlanRowsSlotTest(unittest.TestCase):
    """槽位行：一针供多个分析 + 剔除站点不存的小峰"""

    def _payload(self):
        # 实测形态：`ACC-100%-SPIKED-1(T0)` 同时供 imp_chrom 槽 1 与 imp_stability_rt 槽 1
        return grouped_payload(**{
            u"ACC-100%-SPIKED-1(T0)": [injection(
                u"ACC-100%-SPIKED-1(T0)", u"1",
                peaks_at([(1609.0, 4.946), (1065.0, 47.479),
                          (12818597.0, 34.471)]))],
            u"ICPNB000000249-112e-P R-1(T0)": [injection(
                u"ICPNB000000249-112e-P R-1(T0)", u"1",
                peaks_at([(1691.0, 4.957), (1001.0, 10.122),
                          (13068724.0, 34.469)]))],
        })

    def test_one_row_expands_into_one_plan_row_per_slot(self):
        """页面一行（两个等长清单）→ 每个槽位一行；报告缺的槽位点名告警"""
        payload = grouped_payload(**{
            u"ACC-100%-SPIKED-1(T0)": [injection(
                u"ACC-100%-SPIKED-1(T0)", u"1",
                peaks_at([(1609.0, 4.946), (1065.0, 47.479)]))],
            u"ACC-100%-SPIKED-2": [injection(
                u"ACC-100%-SPIKED-2", u"1",
                peaks_at([(1557.0, 4.940), (1038.0, 47.482)]))],
        })
        rows, warnings = _import.plan_rows(payload,
                                           page_targets((ROW_CHROM_ALL_SLOTS,)))
        self.assertEqual([row[u"slot"] for row in rows], [u"1", u"2"])
        self.assertEqual([row[u"value"] for row in rows], [[u"4.946"], [u"4.940"]])
        self.assertTrue(any(u"ACC-100%-SPIKED-6" in w for w in warnings), warnings)

    def test_slot_row_carries_slot_and_filtered_values(self):
        rows, warnings = _import.plan_rows(self._payload(),
                                           page_targets((ROW_CHROM_SLOT1,)))
        self.assertEqual(warnings, [])
        self.assertEqual(rows[0][u"slot"], u"1")
        self.assertEqual(rows[0][u"row_key"], u"g_sample_id")
        self.assertEqual(rows[0][u"value"], [u"4.946", u"34.471"])

    def test_one_injection_feeds_two_analyses(self):
        """一针多分析：同一个 SampleName 同时落 imp_chrom 与 imp_stability_rt"""
        rows, warnings = _import.plan_rows(
            self._payload(),
            page_targets((ROW_CHROM_SLOT1, ROW_STAB_SLOT1, ROW_DEG_SLOT_UNDEG)))
        self.assertEqual(warnings, [])
        pairs = [(row[u"analysis_keyword"], row[u"slot"]) for row in rows]
        self.assertEqual(pairs, [("imp_chrom", u"1"),
                                ("imp_stability_rt", u"1"),
                                ("imp_degradation", u"未破坏")])
        # imp_degradation 剔的是 RT 10.122，imp_chrom 剔的是 47.479（口径不同）
        self.assertEqual(rows[0][u"value"], [u"4.946", u"34.471"])
        self.assertEqual(rows[2][u"value"], [u"4.957", u"34.469"])


class MergeSlotRowsTest(unittest.TestCase):
    """槽位块替换：多列同行、列长闸门、不建槽"""

    #: 实测 `imp_chrom` 形态：槽 1 有 2 峰、槽 2 有 2 峰（真实是 6×14，
    #: 这里按同一结构缩小，语义完全一致）
    KEYS = [u"1", u"1", u"2", u"2"]
    CURRENT = [u"4.946", u"34.471", u"4.940", u"34.466"]

    def _analysis(self, keys=None, current=None, row_key=u"g_sample_id",
                  keyword=u"g_rt"):
        interims = []
        if keys is not None:
            interims.append({"keyword": row_key,
                             "value": json.dumps(keys, ensure_ascii=False)})
        if current is not None:
            interims.append({"keyword": keyword,
                             "value": json.dumps(current, ensure_ascii=False)})
        return FakeAnalysis(u"imp_chrom", None, interims)

    def _slot_row(self, slot, values, sample=u"SRC", row_key=u"g_sample_id"):
        return {u"analysis_keyword": u"imp_chrom", u"interim_keyword": u"g_rt",
                u"sample_name": sample, u"slot": slot, u"row_key": row_key,
                u"value": list(values), u"injection_count": 1}

    def test_replaces_only_the_slot_block(self):
        warnings = []
        merged, current, notes = _import.merge_slot_rows(
            self._analysis(self.KEYS, self.CURRENT), u"g_rt",
            [self._slot_row(u"1", [u"5.000", u"35.000"])], warnings)
        self.assertEqual(warnings, [])
        self.assertEqual(merged, [u"5.000", u"35.000", u"4.940", u"34.466"])
        self.assertEqual(current, self.CURRENT)
        self.assertTrue(notes and u"槽位 1" in notes[0])

    def test_two_slots_in_one_column(self):
        warnings = []
        merged, _current, notes = _import.merge_slot_rows(
            self._analysis(self.KEYS, self.CURRENT), u"g_rt",
            [self._slot_row(u"1", [u"5.000", u"35.000"]),
             self._slot_row(u"2", [u"6.000", u"36.000"])], warnings)
        self.assertEqual(warnings, [])
        self.assertEqual(merged, [u"5.000", u"35.000", u"6.000", u"36.000"])
        self.assertEqual(len(notes), 2)

    def test_block_length_mismatch_skips_the_slot(self):
        warnings = []
        merged, _current, notes = _import.merge_slot_rows(
            self._analysis(self.KEYS, self.CURRENT), u"g_rt",
            [self._slot_row(u"1", [u"5.000"])], warnings)
        self.assertEqual(merged, self.CURRENT)
        self.assertEqual(notes, [])
        self.assertTrue(any(u"不覆盖" in w for w in warnings), warnings)

    def test_unknown_slot_lists_the_available_ones(self):
        warnings = []
        merged, _current, _notes = _import.merge_slot_rows(
            self._analysis(self.KEYS, self.CURRENT), u"g_rt",
            [self._slot_row(u"7", [u"5.000", u"35.000"])], warnings)
        self.assertEqual(merged, self.CURRENT)
        self.assertTrue(any(u"没有槽位" in w and u"1" in w for w in warnings),
                        warnings)

    def test_split_slot_is_rejected(self):
        keys = [u"1", u"2", u"1"]
        warnings = []
        merged, _current, _notes = _import.merge_slot_rows(
            self._analysis(keys, [u"a", u"b", u"c"]), u"g_rt",
            [self._slot_row(u"1", [u"x"])], warnings)
        self.assertEqual(merged, [u"a", u"b", u"c"])
        self.assertTrue(any(u"分成" in w for w in warnings), warnings)

    def test_column_length_must_equal_row_key_length(self):
        warnings = []
        merged, _current, _notes = _import.merge_slot_rows(
            self._analysis(self.KEYS, [u"4.946", u"34.471"]), u"g_rt",
            [self._slot_row(u"1", [u"5.000", u"35.000"])], warnings)
        self.assertIsNone(merged)
        self.assertTrue(any(u"列长不一致" in w for w in warnings), warnings)

    def test_missing_row_key_column_is_rejected(self):
        warnings = []
        merged, _current, _notes = _import.merge_slot_rows(
            self._analysis(None, self.CURRENT), u"g_rt",
            [self._slot_row(u"1", [u"5.000", u"35.000"])], warnings)
        self.assertIsNone(merged)
        self.assertTrue(any(u"行键列" in w for w in warnings), warnings)

    def test_missing_target_column_is_rejected_not_created(self):
        """本期不建槽：目标列不存在 → 整组跳过（不凭顺序猜落位）"""
        warnings = []
        merged, _current, _notes = _import.merge_slot_rows(
            self._analysis(self.KEYS, None), u"g_rt",
            [self._slot_row(u"1", [u"5.000", u"35.000"])], warnings)
        self.assertIsNone(merged)
        self.assertTrue(any(u"本期不建槽" in w for w in warnings), warnings)

    def test_duplicate_slot_is_rejected(self):
        warnings = []
        merged, _current, _notes = _import.merge_slot_rows(
            self._analysis(self.KEYS, self.CURRENT), u"g_rt",
            [self._slot_row(u"1", [u"5.000", u"35.000"], u"A"),
             self._slot_row(u"1", [u"6.000", u"36.000"], u"B")], warnings)
        self.assertIsNone(merged)
        self.assertTrue(any(u"配了两次" in w for w in warnings), warnings)

    def test_two_row_key_columns_are_rejected(self):
        warnings = []
        merged, _current, _notes = _import.merge_slot_rows(
            self._analysis(self.KEYS, self.CURRENT), u"g_rt",
            [self._slot_row(u"1", [u"5.000", u"35.000"]),
             self._slot_row(u"2", [u"6.000", u"36.000"],
                            row_key=u"imp_deg_id")], warnings)
        self.assertIsNone(merged)
        self.assertTrue(any(u"多个「行键列」" in w for w in warnings), warnings)

    def test_partial_failure_keeps_the_good_slot(self):
        """一个槽位块长不符 → 只跳过它，另一个照写（宁可少写，不可错写）"""
        warnings = []
        merged, _current, notes = _import.merge_slot_rows(
            self._analysis(self.KEYS, self.CURRENT), u"g_rt",
            [self._slot_row(u"1", [u"5.000", u"35.000"]),
             self._slot_row(u"2", [u"6.000"])], warnings)
        self.assertEqual(merged, [u"5.000", u"35.000", u"4.940", u"34.466"])
        self.assertEqual(len(notes), 1)


def skeleton_row(slot, values, analysis_keyword=u"imp_chrom",
                 row_key=u"g_sample_id", sample_name=u"ACC-100%-SPIKED-1(T0)"):
    """槽位行（`plan_rows` 的产物形态），供建槽单测造输入"""
    return {
        u"analysis_keyword": analysis_keyword,
        u"interim_keyword": u"g_rt",
        u"sample_name": sample_name,
        u"title": sample_name,
        u"injection_count": 1,
        u"value": list(values),
        u"value_text": json.dumps([u"%s" % value for value in values]),
        u"row_key": row_key,
        u"slot": slot,
    }


class PlanSkeletonTest(unittest.TestCase):
    """空单自举建槽：目标列与行键列都为空时，按本次报告生成骨架

    ★ 建槽的意义：WS-007 这类"还没走到峰级那一步"的单，峰级数组全为空，
      没有骨架就无处落位（`SLOT_LAYOUT_ERROR`）。
    """

    def _analysis(self, row_key_value=u"", target_value=u"",
                  row_key=u"g_sample_id", target=u"g_rt"):
        interims = []
        if row_key_value is not None:
            interims.append({"keyword": row_key, "value": row_key_value})
        if target_value is not None:
            interims.append({"keyword": target, "value": target_value})
        return FakeAnalysis(u"imp_chrom", interims=interims)

    def test_builds_when_both_columns_are_empty(self):
        warnings = []
        keys, values, notes = _import.plan_skeleton(
            self._analysis(), u"g_rt", u"g_sample_id",
            [skeleton_row(u"1", [u"4.940", u"34.466"]),
             skeleton_row(u"2", [u"5.000"])], warnings)
        self.assertEqual(keys, [u"1", u"1", u"2"])
        self.assertEqual(values, [u"4.940", u"34.466", u"5.000"])
        self.assertEqual(len(notes), 2)
        self.assertEqual(warnings, [])

    def test_slot_order_follows_page_config(self):
        """槽位顺序 = 页面清单顺序（不是按字符串排序）"""
        keys, _values, _notes = _import.plan_skeleton(
            self._analysis(), u"g_rt", u"g_sample_id",
            [skeleton_row(u"10", [u"1.000"]),
             skeleton_row(u"2", [u"2.000"])], [])
        self.assertEqual(keys, [u"10", u"2"])

    def test_refuses_when_a_slot_has_no_values(self):
        """槽位宽度各不相同 → 缺一个槽位就无从知道它该多宽，整组不建"""
        warnings = []
        result = _import.plan_skeleton(
            self._analysis(), u"g_rt", u"g_sample_id",
            [skeleton_row(u"1", [u"4.940"]),
             skeleton_row(u"2", [])], warnings)
        self.assertIsNone(result)
        self.assertTrue(any(u"槽位 2" in item for item in warnings), warnings)

    def test_none_when_target_column_has_values(self):
        analysis = self._analysis(target_value=u'["1.000", "2.000"]')
        self.assertIsNone(_import.plan_skeleton(
            analysis, u"g_rt", u"g_sample_id",
            [skeleton_row(u"1", [u"4.940", u"34.466"])], []))

    def test_none_when_row_key_interim_is_missing(self):
        """行键列在分析上不存在 → 骨架写不出来，不建槽"""
        analysis = self._analysis(row_key_value=None)
        self.assertIsNone(_import.plan_skeleton(
            analysis, u"g_rt", u"g_sample_id",
            [skeleton_row(u"1", [u"4.940"])], []))

    def test_none_when_target_interim_is_missing(self):
        analysis = self._analysis(target_value=None)
        warnings = []
        self.assertIsNone(_import.plan_skeleton(
            analysis, u"g_rt", u"g_sample_id",
            [skeleton_row(u"1", [u"4.940"])], warnings))
        self.assertEqual(warnings, [])


class PlanEmptyColumnTest(unittest.TestCase):
    """空列补值：行键列**有值**、目标列为空时，按现有骨架补出目标列

    ★ 实测场景（WS-007）：`g_sample_id` 有 84 值、`imp_name` 是空数组。
      旧版 `plan_skeleton()` 因"行键列已有值"直接返回 None，
      而 `merge_slot_rows()` 又因"目标列 0 值 ≠ 行键列 84 值"整组拒绝
      ⇒ 两条路径都不接（`SLOT_LAYOUT_ERROR`）。
    """

    def _analysis(self, row_key_value, target_value=u"",
                  row_key=u"g_sample_id", target=u"imp_name"):
        interims = []
        if row_key_value is not None:
            interims.append({"keyword": row_key, "value": row_key_value})
        if target_value is not None:
            interims.append({"keyword": target, "value": target_value})
        return FakeAnalysis(u"imp_chrom", interims=interims)

    def test_fills_empty_column_using_existing_skeleton(self):
        """骨架在、目标列空 → 按骨架块长补值，长度与行键列一致"""
        analysis = self._analysis(u'["1", "1", "2", "2", "2"]')
        warnings = []
        keys, values, notes = _import.plan_skeleton(
            analysis, u"imp_name", u"g_sample_id",
            [skeleton_row(u"1", [u"未知杂质", u"未知杂质"]),
             skeleton_row(u"2", [u"未知杂质", u"未知杂质", u"未知杂质"])],
            warnings)
        self.assertEqual(keys, [u"1", u"1", u"2", u"2", u"2"])
        self.assertEqual(values, [u"未知杂质"] * 5)
        self.assertEqual(len(notes), 2)
        self.assertEqual(warnings, [])

    def test_uncovered_slots_stay_empty_not_row_key(self):
        """未覆盖槽位保持空串，**绝不**用行键值去占位

        ★ #1 修复：旧实现用 `merged = list(keys_now)` 复制行键，行键 `"2"` 这类
          结构标识会漏进名称/数值列（实测脏数据风险）。现在目标列骨架是等长空串列表。
        """
        analysis = self._analysis(u'["1", "1", "2", "2"]')
        keys, values, notes = _import.plan_skeleton(
            analysis, u"imp_name", u"g_sample_id",
            [skeleton_row(u"1", [u"未知杂质", u"未知杂质"])], [])
        self.assertEqual(keys, [u"1", u"1", u"2", u"2"])
        # 槽位 2 未被本次报告覆盖 → 保持**空串**，不得写成行键值 "2"
        self.assertEqual(values, [u"未知杂质", u"未知杂质", u"", u""])
        self.assertEqual(len(notes), 1)

    def test_rejects_when_a_configured_slot_cannot_land(self):
        """配置了多个槽位、但本次报告没取全（缺槽/块长不符）→ 整组拒绝并点名"""
        analysis = self._analysis(u'["1", "1"]')
        warnings = []
        # 行键列只有槽位 1；配置里多了槽位 2 → 槽位 2 不存在于行键列 → 整组不建成值
        result = _import.plan_skeleton(
            analysis, u"imp_name", u"g_sample_id",
            [skeleton_row(u"1", [u"未知杂质", u"未知杂质"]),
             skeleton_row(u"2", [u"未知杂质"])], warnings)
        self.assertIsNone(result)
        self.assertTrue(any(u"没取全" in w for w in warnings))
        self.assertTrue(any(u"不存在于行键列" in w for w in warnings))

    def test_rejects_all_when_block_length_differs(self):
        """块长不符 → 整组拒绝：空列补值要求所有配置槽位都落上，不掩盖缺槽"""
        analysis = self._analysis(u'["1", "1", "1", "2", "2"]')
        warnings = []
        result = _import.plan_skeleton(
            analysis, u"imp_name", u"g_sample_id",
            [skeleton_row(u"1", [u"未知杂质"]),  # 块长 3，只取到 1 → failed
             skeleton_row(u"2", [u"未知杂质", u"未知杂质"])], warnings)
        self.assertIsNone(result)
        self.assertTrue(any(u"没取全" in item for item in warnings), warnings)
        self.assertTrue(any(u"「1」块长" in item for item in warnings), warnings)

    def test_none_when_no_slot_matches(self):
        """配置槽位在行键列里都不存在 → 整组跳过并点名"""
        analysis = self._analysis(u'["1", "1"]')
        warnings = []
        result = _import.plan_skeleton(
            analysis, u"imp_name", u"g_sample_id",
            [skeleton_row(u"9", [u"未知杂质"])], warnings)
        self.assertIsNone(result)
        self.assertTrue(any(u"没取全" in item for item in warnings), warnings)
        self.assertTrue(any(u"不存在于行键列" in item for item in warnings),
                        warnings)

    def test_none_when_slot_absent_from_skeleton(self):
        """槽位在行键列里不存在 → 整组跳过并点名该槽位"""
        analysis = self._analysis(u'["1", "1"]')
        warnings = []
        result = _import.plan_skeleton(
            analysis, u"imp_name", u"g_sample_id",
            [skeleton_row(u"7", [u"未知杂质"])], warnings)
        self.assertIsNone(result)
        self.assertTrue(any(u"「7」不存在于行键列" in item for item in warnings),
                        warnings)

    def test_none_when_slot_is_split_into_segments(self):
        """槽位在行键列里分成多段 → 分不出写哪一段，跳过"""
        analysis = self._analysis(u'["1", "2", "1"]')
        warnings = []
        result = _import.plan_skeleton(
            analysis, u"imp_name", u"g_sample_id",
            [skeleton_row(u"1", [u"未知杂质"])], warnings)
        self.assertIsNone(result)
        self.assertTrue(any(u"分成 2 段" in item for item in warnings), warnings)


class FakeUpload(object):
    """上传对象：原生 FileUpload 的 `name` 是容器内全路径，`filename` 是文件名"""

    def __init__(self, filename=None, name=None):
        if filename is not None:
            self.filename = filename
        if name is not None:
            self.name = name


class UploadNameTest(unittest.TestCase):
    """正文没有 WS-ID 时的临时桥接：只认文件名首段，且规则与正文同一套"""

    def setUp(self):
        # 延迟导入要拿到**真的** empower_pdf（不在 Zope 里跑时包不存在），
        # 否则这条桥接会被 except 吞掉、测试变成空转。
        empower = _load_source(
            "maitux_empower_pdf_for_name_test",
            os.path.join(_SERVICES, "empower_pdf.py"))
        services = types.ModuleType("maitux.instrument_acquisition.services")
        services.empower_pdf = empower
        self._stubs = {
            "maitux": types.ModuleType("maitux"),
            "maitux.instrument_acquisition": types.ModuleType(
                "maitux.instrument_acquisition"),
            "maitux.instrument_acquisition.services": services,
        }
        self._added = []
        for name, module in self._stubs.items():
            if name not in sys.modules:
                sys.modules[name] = module
                self._added.append(name)

    def tearDown(self):
        for name in self._added:
            sys.modules.pop(name, None)

    def test_prefix_with_underscore(self):
        self.assertEqual(
            _import.worksheet_id_from_name(u"WS-007_1 SYS.pdf"), u"WS-007")

    def test_prefix_with_space(self):
        self.assertEqual(
            _import.worksheet_id_from_name(u"WS-007 8 Acc-spiked-STD.pdf"),
            u"WS-007")

    def test_bare_worksheet_id_filename(self):
        """`WS-007.pdf`：剥掉扩展名后才判得通过（不剥的话首段是 `WS-007.pdf`）"""
        self.assertEqual(_import.worksheet_id_from_name(u"WS-007.pdf"), u"WS-007")

    def test_full_container_path(self):
        """自动导入给的是容器内全路径"""
        self.assertEqual(
            _import.worksheet_id_from_name(
                u"/data/dcu_auto_import/WS-007_1 SYS.pdf"), u"WS-007")

    def test_windows_path(self):
        self.assertEqual(
            _import.worksheet_id_from_name(u"C:\\dcu\\WS-006_1 SYS.pdf"),
            u"WS-006")

    def test_old_style_name_is_rejected(self):
        """旧式 Sample Set Name（日期开头）不得被当成 WS-ID"""
        self.assertEqual(
            _import.worksheet_id_from_name(u"20260512_VF_IP_LC013_01.pdf"), u"")

    def test_plain_report_name_is_rejected(self):
        self.assertEqual(_import.worksheet_id_from_name(u"1 SYS.pdf"), u"")

    def test_empty_is_rejected(self):
        for value in (None, u"", u".pdf"):
            self.assertEqual(_import.worksheet_id_from_name(value), u"")

    def test_upload_name_prefers_filename(self):
        self.assertEqual(
            _import._upload_name(FakeUpload(u"WS-007_1 SYS.pdf")),
            u"WS-007_1 SYS.pdf")

    def test_upload_name_falls_back_to_name(self):
        self.assertEqual(
            _import._upload_name(FakeUpload(name=u"/data/x/WS-007_1 SYS.pdf")),
            u"/data/x/WS-007_1 SYS.pdf")

    def test_upload_name_of_missing_upload(self):
        self.assertEqual(_import._upload_name(None), u"")


if __name__ == "__main__":
    unittest.main()
