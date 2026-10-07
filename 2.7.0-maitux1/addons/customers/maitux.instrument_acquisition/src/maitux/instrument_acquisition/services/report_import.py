# -*- coding: utf-8 -*-
"""报告导入落位（首期只做 `imp_sys_suit`）

把 `parsers/empower_report_parser.py` 的产物（`injections` / `grouped`）
按**报告目标登记表**落到 Worksheet 分析行的 interim 字段。

★ 为什么不让调试页第 3 步（通道 A）直接写报告语义：

1. 通道 A 按 interim keyword 模糊匹配 —— `imp_sys_suit` 与 `imp_ip_sys_suit`
   **共用 `imp_std1_area` / `imp_std2_area` 等同名字段**，写进哪一个取决于
   样品的分析顺序，不可控；
2. 通道 A 没有白名单与 diff。

本模块按 **(WorkSheet → 分析 keyword → interim keyword)** 定位，
只允许写**页面（`keyword_glossary`）勾选的目标位**，且**先 dry-run 出 diff，确认后才写**。

★ **"分析 keyword" 在一张 WorkSheet 里可能命中多个分析**（实测 WS-001 装 3 个样品、
WS-004 装 2 个样品，且各自都有 `Ca`/`Mg`）。早期实现是"**取第一个命中**"→ 一单多样品时
会**静默写错样品**，连 dry-run 都看不出来（diff 也是拿第一个样品比的）。
现在改为 **`resolve_analysis()`：唯一命中才落位，多个命中一律点名拒绝**
（`AMBIGUOUS_ANALYSIS`，diff 里附候选样品清单）—— 与采集页（通道 A 用分析 UID 定位）
保持同样的"样品感知"，宁可漏写、不可写错。详见
`doc/仪器采集/DCU-多样品Worksheet影响分析.md`。

落位规则：**从 `keyword_glossary` 页面读配置**（`services/report_targets.py`），
代码里**不再有**目标位默认值 —— 页面是唯一权威。页面每行给出：

| 页面列 | 作用 |
|---|---|
| 报告导入目标位 | 勾选才落位（未勾选一律不写） |
| 来源 SampleName | 报告正文里的 `STD-1` / `SYS` … |
| 取值规则 `pick` | `main_peak.*` 取单值、`peaks.*` 取该针整列（按峰序） |
| 写法 `decimals` | 按站点现值保留几位小数（空 = 原样） |
| 期望长度 | 针数/峰数；不符即跳过（防"单针报告覆盖完整数组"） |
| 第 N 针 | 只取该来源的第 N 针（0 = 全部针按序拼接） |
| 取前 N 峰 | 每针只取前 N 个峰（0 = 全部） |
| 目标 RT | 只保留 RT 落在 ±0.5 min 窗口内的峰（0 = 不筛） |
| 峰序号清单 | 只保留这些峰序号（如 `3,6,7,8,15,16`；空 = 不筛） |
| 行键列 | **`row-sync` 落位**：数组的行键列名（如 `g_sample_id`） |
| 行槽位 | 要写的槽位取值；与「来源 SampleName」**按位置一一对应的逗号清单** |
| 排除 RT | 剔除站点不存的小峰（RT 落在任一值 ±0.5 min 内） |

★ **峰级"多列同行"组靠 `行键列 + 行槽位` 落位**（Step 3）：峰级数组是**扁平列表 +
行键列重复标号**（实测 `imp_chrom.g_sample_id` = `1..6` 各 14 次，`imp_name`/`g_rt`/
`g_area` 各 84 值），所以一个目标列要写多个槽位时，页面一行给两个**等长清单**：

    acq_source_sample = ACC-100%-SPIKED-1(T0), ACC-100%-SPIKED-2, …
    acq_slot          = 1, 2, …

落位规则：

1. **布局的唯一权威是分析上现有的行键列**（`g_sample_id` / `imp_deg_id` /
   `imp_qc_point`）—— 用它在目标列里定出该槽位的连续块 `[start, end)`；
2. 新值个数必须**恰好等于块长**，否则**跳过该槽位并点名**（少写一个峰 = 值表与站点
   现值不一致，属于"写错"）；**一个槽位都没落上 → 状态 `SLOT_SKIPPED`**（不报
   `MATCH`，否则"什么都没写"会被误读成"已对齐"）；
3. 目标列必须与行键列**等长**（否则按行替换会错位）→ 不等长即整组跳过；
4. 两个清单**必须等长**（错配一次 = 整列数据错位）、同一槽位配两次、同一目标位
   同时配"整列"与"槽位" → 一律**点名拒绝**（配置错，两套语义会互相覆盖）；
5. **本期不建槽**：行键列里没有该槽位（或列不存在）→ 跳过并列出可用槽位，
   绝不"按顺序兜底"猜落位。

★ **`排除 RT` 是站点自己的报告阈值口径**（实测）：同一针在站点不同分析里存的峰表
不同 —— `imp_chrom` 槽 1 与报告 15 峰只差 RT 47.479（area 1065）、`imp_degradation`
只差 RT 10.122、`imp_repeat` 一个都不少。站点现值是验收基准，所以把"剔除哪些 RT"
显式配出来（不猜阈值规则）。

★ **覆盖默认关闭**（自动导入无人复核）：现值与本次**不同**（`DIFF`）时默认不写，
状态记 `SKIPPED_OVERWRITE`，需显式 `allow_overwrite=True` 才覆盖。
反例：站点现值可能已被人工改过，静默覆盖就是"写错"。

★ **报告 PDF 强制留档**：写入成功后把 PDF 挂到目标 WorkSheet、并链接到本次写入的
每个分析（同标题附件已存在则复用，重复导入不产生重复附件）；
**挂附件失败视为本次失败** —— 追溯性缺失按质量事件处理，宁可让文件留在
`failed/` 等人工处理。

★ **`decimals` 必须按站点现值定**（不要统一"去掉 `.0`"）：实测 `imp_sep_res_before`
现值是 `"5.0"`，若按"整数去 `.0`"归一就会写成 `"5"` → 与现值 DIFF（首次 dry-run 抓到）。

★ **`expected_length` 是防覆盖闸门**：反例（实测）`1 SYS-plate.pdf` 里只有 1 针
`STD-1`，若不加长度校验，一次批量导入就会把 6 针的 `imp_std1_area` 覆盖成 1 个值。
宁可漏写，不可写错。

★ 本模块**顶层不 import bika / senaite**（单测按文件路径加载），
`report_targets` 也在 `run()` 内部延迟导入，避免包级依赖。
"""

import json

try:  # Python 2
    text_type = unicode
except NameError:  # Python 3
    text_type = str

#: RT 匹配窗口（分钟）：页面「目标 RT」两侧各留多少
#:
#: ★ 这是**工程容差**（不是业务参数）——业务参数是"目标 RT 是多少"（页面列），
#:   而"多近算同一个峰"是匹配规则。实测依据：指定杂质 Z7 在 12 个进样里的 RT
#:   落在 24.28~24.38（跨针漂移 0.1 min），而最近的相邻峰在 25.43（差 1.1 min），
#:   所以 ±0.5 既容得下漂移、又不会吃到邻峰。真要调，只改这一个常量。
RT_MATCH_TOLERANCE = 0.5

# ★ 取值规则/写法/长度的**词表与读取**都在 `services/report_targets.py`
#   （页面列与之一一对应）。本模块只做"解析产物 + 目标位 → diff/写入"，
#   目标位由调用方传入或由 `run()` 在 Zope 环境内延迟加载 ——
#   这样本文件在裸 python 下可按路径加载做单测（不触发包级 import）。
#
# ★ 例外：名称类规则集合与「未知杂质」常量是**纯常量**（不触发包级 import），
#   直接按文件路径加载，避免 `pick_values` 里再套一层延迟导入。
try:  # 包内正常导入
    from maitux.instrument_acquisition.services.report_targets import (
        NAME_PICK_RULES, UNKNOWN_IMPURITY)
except ImportError:  # 单测按文件路径加载本模块时
    import os
    _here = os.path.dirname(os.path.abspath(__file__))
    _targets_path = os.path.join(_here, "report_targets.py")
    _namespace = {}
    with open(_targets_path) as _handle:
        exec(compile(_handle.read(), _targets_path, "exec"), _namespace)
    NAME_PICK_RULES = _namespace["NAME_PICK_RULES"]
    UNKNOWN_IMPURITY = _namespace["UNKNOWN_IMPURITY"]

REPORT_TYPE = u"empower_pdf"


# ---------------------------------------------------------------------------
# 纯逻辑（可单测，无 Zope 依赖）
# ---------------------------------------------------------------------------

def _text(value):
    if value is None:
        return u""
    if isinstance(value, text_type):
        return value.strip()
    try:
        return value.decode("utf-8").strip()
    except Exception:
        return (u"%s" % value).strip()


def _to_int(value):
    try:
        return int(_text(value))
    except Exception:
        return 0


def normalize_number(value):
    """数值归一为站点写法：整数不带 `.0`，无值写 `N/A`"""
    if value is None:
        return u"N/A"
    if isinstance(value, bool):
        return u"%s" % value
    if isinstance(value, float):
        if value == int(value):
            return u"%d" % int(value)
        return (u"%s" % value).strip()
    if isinstance(value, int):
        return u"%d" % value
    return _text(value)


def format_value(value, decimals=None):
    """按目标列的写法格式化

    - `decimals=None`：原样（走 `normalize_number`：整数不带 `.0`，非整数原样）
    - `decimals=0`：整数；`decimals=n`：n 位小数

    ★ 站点现值是"这一列该长什么样"的权威：`imp_sep_res_before` 存的是 `"5.0"`，
    所以该列必须给 `decimals=1`，不能用"去 `.0`"的通用归一。
    """
    if value is None:
        return u"N/A"
    if decimals is None:
        return normalize_number(value)
    if isinstance(value, bool):
        return u"%s" % value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return normalize_number(value)
    return (u"%%.%df" % decimals) % number


def main_peak(injection, peaks=None):
    """取**主峰**（面积最大者）；无峰返回 None

    :param peaks: 已筛选过的峰列表（页面维度筛完再传进来）；
        不给则用该针的全部峰。
    """
    if peaks is None:
        peaks = injection.get("peaks") or []
    peaks = list(peaks)
    if not peaks:
        return None
    return max(peaks, key=lambda peak: peak.get("area") or 0)


def rt_within(value, target):
    """`value` 是否落在 `target ± RT_MATCH_TOLERANCE` 内（`None` 一律不算命中）"""
    if value is None or target is None:
        return False
    return abs(value - target) <= RT_MATCH_TOLERANCE


def select_peaks(peaks, peak_indexes=None, rt=None, peaks_limit=None,
                 drop_rt=None):
    """按页面维度筛选峰，顺序有意固定：

    1. **峰序号**（`acq_peak_indexes`）：按**报告原始峰序**（1 起）挑，
       如 `3,6,7,8,15,16` —— 必须作用在原始列表上，所以放第一步；
    2. **排除 RT**（`acq_drop_rt`）：剔除 RT 落在任一"排除 RT" ± 容差内的峰
       （站点自己的报告阈值口径，见模块 docstring）；
    3. **RT 窗口**（`acq_rt`）：只保留 RT 落在 `目标 ± RT_MATCH_TOLERANCE`
       内的峰（RT 缺失的峰直接排除）；
    4. **取前 N 峰**（`acq_peaks`）：最后截取前 N 个。

    ★ 筛完可能是 0 个或多个：调用方**不做兜底猜测**（0 个 → 跳过并告警，
    多个 → 由 `expected_length` / 槽位块长闸门决定），避免"悄悄选错峰"。
    """
    selected = list(peaks or [])
    if peak_indexes:
        wanted = set(peak_indexes)
        selected = [peak for index, peak in enumerate(selected, 1)
                    if index in wanted]
    if drop_rt:
        selected = [peak for peak in selected
                    if not any(rt_within(peak.get("rt"), target)
                               for target in drop_rt)]
    if rt:
        selected = [peak for peak in selected if rt_within(peak.get("rt"), rt)]
    if peaks_limit:
        selected = selected[:peaks_limit]
    return selected


def is_report_payload(parsed):
    """是否是报告解析产物（而不是调试通道 A 的 samples 形态）"""
    if not isinstance(parsed, dict):
        return False
    if parsed.get("report_type") == REPORT_TYPE:
        return True
    return bool(parsed.get("injections") or parsed.get("grouped"))


def pick_values(injection, rule, peaks_limit=None, rt=None, peak_indexes=None,
                drop_rt=None):
    """按取值规则取该针的值列表；该针取不到（筛完无峰）返回 `[]`

    - `main_peak.area`   → `[<（筛选后）主峰面积>]`（单值）
    - `peaks.area`       → 该针**全部峰**的面积（按峰序）
    - `peaks.rt`         → 该针全部峰的 RT（按峰序）
    - `peaks.resolution` → 该针全部峰的分离度（首峰无前峰 → `None` → 归一成 `N/A`）
    - `peaks.sn`         → 该针全部峰的 USP s/n（按峰序）
    - `peaks.area_sum`   → 该针（筛选后）**峰面积之和**（单值）
    - `peaks.name`       → 该针全部峰的**峰名**（按峰序）；报告里 Peak Name
      空白（未命名杂质）→ 落位 `UNKNOWN_IMPURITY`（「未知杂质」）

    ★ `peaks.name` 是**唯一一条字符串规则**：它不走 `format_value` 的数值归一，
      且空白峰**必须占位**（写「未知杂质」而不是跳过）—— 峰级数组按峰序一一对应，
      少一个值就会让槽位长度校验拒绝整段、或让「期望长度」闸门整行跳过。

    峰维度（`peak_indexes` / `rt` / `peaks_limit` / `drop_rt`）先经 `select_peaks`
    统一筛，再按规则取值 —— 见 `select_peaks` 里的顺序说明。

    :param peaks_limit: 页面「取前 N 峰」（实测 `imp_linearity` 取前 3 峰）
    :param rt: 页面「目标 RT」，按 ±`RT_MATCH_TOLERANCE` 匹配
        （实测 `imp_rec_spec.g_area` = RT≈24.3 的指定杂质峰）
    :param peak_indexes: 页面「峰序号清单」，按报告原始峰序挑
        （实测 `imp_specificity` 取 SYS 16 峰里的 3,6,7,8,15,16）
    :param drop_rt: 页面「排除 RT」列表，命中者剔除（站点报告阈值口径）
    """
    field = (rule or u"").split(u".")[-1]
    if not field:
        return []

    peaks = select_peaks(injection.get("peaks") or [],
                         peak_indexes=peak_indexes, rt=rt,
                         peaks_limit=peaks_limit, drop_rt=drop_rt)

    if rule.startswith(u"main_peak."):
        peak = main_peak(injection, peaks)
        if peak is None:
            return []
        return [peak.get(field)]

    if rule == u"peaks.area_sum":
        if not peaks:
            return []
        total = 0.0
        for peak in peaks:
            area = peak.get("area")
            if area is None:
                # ★ 缺面积的峰不进求和（当成 0 会得到一个"看着合理"的错值）
                return []
            total += area
        return [total]

    if rule.startswith(u"peaks."):
        if not peaks:
            return []
        if rule in NAME_PICK_RULES:
            # ★ 名称类：字符串语义，空白峰占位为「未知杂质」（不跳过）
            return [_text(peak.get(field)) or UNKNOWN_IMPURITY
                    for peak in peaks]
        return [peak.get(field) for peak in peaks]
    return []


def select_injections(injections, injection_no=None):
    """按「第 N 针」挑针；`None` / 0 = 全部针（调用方已按 injection_no 升序）"""
    if not injection_no:
        return list(injections)
    return [item for item in injections
            if _to_int(item.get("injection_no")) == injection_no]


def plan_rows(parsed, targets):
    """报告产物 + 目标位 → 落位计划

    :param targets: 页面配置生成的目标位列表（`report_targets.build_target` 的产物）
    :returns: (rows, warnings)；row 含 value（list[str]）与 value_text（JSON 串）

    row 的两种形态：

    | 形态 | 判据 | 含义 |
    |---|---|---|
    | 整列行 | 无 `slot` | `value` = 该目标位的**完整列**（Step 1/2 的语义） |
    | 槽位行 | 有 `slot` / `row_key` | `value` = 该**槽位连续块**的值（Step 3 的 `row-sync`） |

    ★ 槽位行的合并（写进哪一段）在 `run()` 里做 —— 那里才拿得到分析上的
    行键列现值（布局的权威）。
    """
    rows = []
    warnings = []

    groups = {}
    for group in parsed.get("grouped") or []:
        name = _text(group.get("sample_name"))
        if name:
            groups[name] = group

    for target in targets or []:
        # ★ 槽位模式：一个目标列要写多个槽位（页面一行用两个等长清单表达），
        #   每个 (来源, 槽位) 各产出一行；非槽位模式：来源是单值，产出 1 行。
        pairs = zip(target.get(u"sources") or (), target.get(u"slots") or ())
        if not pairs:
            pairs = ((target[u"sample_name"], u""),)
        for sample_name, slot in pairs:
            row = _plan_source(groups, target, sample_name, slot, warnings)
            if row is not None:
                rows.append(row)

    return rows, warnings


def _plan_source(groups, target, sample_name, slot, warnings):
    """一个 (来源 SampleName, 槽位) → 落位行；取不到返回 None（原因进 warnings）"""
    interim_keyword = target[u"interim_keyword"]
    group = groups.get(sample_name)
    if group is None:
        warnings.append(
            u"报告里没有 %s 进样，跳过 %s" % (sample_name, interim_keyword))
        return None

    injections = sorted(group.get("injections") or [],
                        key=lambda item: _to_int(item.get("injection_no")))
    # ★ 「第 N 针」维度：`imp_loqN_area` 这类字段 = 第 N 针的整列峰（M0 §6.3）
    injection_no = target.get(u"injection")
    if injection_no:
        selected = select_injections(injections, injection_no)
        if not selected:
            warnings.append(
                u"%s 里没有第 %s 针，跳过 %s"
                % (sample_name, injection_no, interim_keyword))
            return None
        injections = selected

    values = []
    for injection in injections:
        picked = pick_values(injection, target[u"pick"],
                             target.get(u"peaks_limit"),
                             rt=target.get(u"rt"),
                             peak_indexes=target.get(u"peak_indexes"),
                             drop_rt=target.get(u"drop_rt"))
        if not picked:
            warnings.append(
                u"%s 第 %s 针无峰，已跳过该针"
                % (sample_name, _text(injection.get("injection_no"))))
            continue
        values.extend(format_value(value, target.get(u"decimals"))
                      for value in picked)

    if not values:
        warnings.append(u"%s 没有可用峰，跳过 %s" % (sample_name,
                                                interim_keyword))
        return None

    expected = target.get(u"expected_length")
    if expected and len(values) != expected:
        # ★ 防覆盖闸门：单针/局部报告不得覆盖完整数组（映射表里写了几针就收几针）
        warnings.append(
            u"%s 的长度与映射表不符（映射表 %d，本报告 %d），跳过 %s —— "
            u"局部报告（如仅含 1 针 STD-1 的进样板报告）不得覆盖完整数组"
            % (interim_keyword, expected, len(values), interim_keyword))
        return None

    return {
        u"analysis_keyword": target[u"analysis_keyword"],
        u"interim_keyword": interim_keyword,
        u"sample_name": sample_name,
        u"title": target[u"title"],
        u"injection_count": len(injections),
        u"value": values,
        u"value_text": json.dumps(values, ensure_ascii=False),
        u"row_key": target.get(u"row_key") or u"",
        u"slot": slot or u"",
    }


def compare_value(current, value_text):
    """现值 vs 采集值：MATCH / DIFF / NEW（NEW = 现值空）

    另附 same_ignoring_spaces：忽略逗号后空格后是否一致（诊断用，
    WS-006 首轮比对就栽在"格式不同"上）。
    """
    current = _text(current)
    if not current:
        return u"NEW", False
    status = u"MATCH" if current == value_text else u"DIFF"
    same = current.replace(u", ", u",") == value_text.replace(u", ", u",")
    return status, same


def describe_value(value_text, limit=120):
    """把（可能很长的）数组文本压成一条日志友好的短串"""
    text = _text(value_text)
    if len(text) <= limit:
        return text
    return u"%s…（共 %d 字符）" % (text[:limit], len(text))


def find_slot_runs(values, slot):
    """行键数组里该槽位的**连续块**列表 `[(start, end), ...]`

    ★ 只认连续段：峰级数组是"行键重复标号 + 该行的峰按序"，所以一个槽位就是**一段**。
    出现多段（中间夹了别的槽位）说明站点结构不是预期形态 → 调用方点名拒绝。
    """
    wanted = _text(slot)
    runs = []
    start = None
    for index, value in enumerate(values or []):
        if _text(value) == wanted:
            if start is None:
                start = index
        elif start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(values or [])))
    return runs


def group_plan_rows(rows, warnings):
    """落位行 → 按 `(分析, interim)` 分组的处理单元

    同一目标位下**整列行与槽位行互斥**：两种语义都会重写整列，混配必然互相覆盖，
    所以一律点名拒绝（配置错），不做"谁先谁后"的猜测。
    """
    order = []
    groups = {}
    for row in rows:
        key = (row[u"analysis_keyword"], row[u"interim_keyword"])
        if key not in groups:
            groups[key] = {u"whole": None, u"slots": []}
            order.append(key)
        bucket = groups[key]
        if row.get(u"slot"):
            bucket[u"slots"].append(row)
        elif bucket[u"whole"] is None:
            bucket[u"whole"] = row
        else:
            # 纯函数层的重名由 `plan_rows` 的页面唯一性保证；这里只做最后一道
            warnings.append(u"%s.%s 配了多个整列目标位（页面应只有一行），"
                            u"取第一条" % key)

    units = []
    for key in order:
        bucket = groups[key]
        if bucket[u"whole"] is not None and bucket[u"slots"]:
            warnings.append(
                u"%s.%s 同时配了「整列」目标位与「行槽位」目标位 —— "
                u"两种落位语义互斥，本目标位整组跳过" % key)
            continue
        units.append((key, bucket))
    return units


# ---------------------------------------------------------------------------
# Zope 层（延迟导入 bika）
# ---------------------------------------------------------------------------

def worksheet_id_from_name(name):
    """从**上传文件名**首段取 WorkSheet ID（临时桥接；正文有 WS-ID 时不走这里）

    ★ 正式来源是报告正文的 `Sample Set Name`（规范 §3.1，实验室只写 `WS-007`）。
      在实验室按新约定出报告之前，允许把文件命名成 `WS-007_1 SYS.pdf` 顶上。
    ★ 判定规则**复用** `empower_pdf.worksheet_id_from_text()`，不另立一套口径；
      这里只做"文件名"特有的两步清理：剥掉目录（自动导入给的是容器内全路径）、
      剥掉扩展名（否则 `WS-007.pdf` 的首段是 `WS-007.pdf`，会判不通过）。
    ★ 延迟导入：本模块顶层不 import 包内其它模块（单测按文件路径加载）。

    :returns: WS-ID；取不到返回 u""
    """
    text = _text(name)
    if not text:
        return u""
    text = text.replace(u"\\", u"/").rsplit(u"/", 1)[-1]
    head, dot, _extension = text.rpartition(u".")
    if dot and head:
        text = head
    if not text:
        return u""
    try:
        from maitux.instrument_acquisition.services import empower_pdf
    except Exception:
        return u""
    try:
        return _text(empower_pdf.worksheet_id_from_text(text))
    except Exception:
        return u""


def _upload_name(attachment):
    """上传对象 → 文件名（原生 FileUpload 的 `name` 是容器内全路径）"""
    if attachment is None:
        return u""
    for attribute in ("filename", "name"):
        value = getattr(attachment, attribute, None)
        if value:
            return _text(value)
    return u""


def find_worksheet(worksheet_id):
    """按 WorkSheet ID（如 `WS-007`）查找 Worksheet 对象"""
    from bika.lims import api

    worksheet_id = _text(worksheet_id)
    if not worksheet_id:
        return None

    for catalog in ("portal_catalog", "senaite_catalog"):
        try:
            brains = api.search({
                "portal_type": "Worksheet",
                "getId": worksheet_id,
            }, catalog=catalog)
        except Exception:
            continue
        for brain in brains:
            obj = api.get_object(brain)
            if api.is_object(obj):
                return obj

    # 兜底：按 /worksheets/<id> 遍历（WorkSheet ID 就是路径 id）
    try:
        folder = api.get_portal().worksheets
        obj = getattr(folder, str(worksheet_id), None)
        if api.is_object(obj):
            return obj
    except Exception:
        pass
    return None


def find_analyses(worksheet, analysis_keyword):
    """返回 Worksheet 里**全部**同 keyword 的分析（不再是"取第一个"）

    一张 WorkSheet 可以装多个样品的**同一个** AS（实测 WS-001 三样品、
    WS-004 两样品，各自都有 `Ca`/`Mg`），所以"命中几个"本身就是要判定的事实。
    """
    matches = []
    for analysis in worksheet.getAnalyses() or []:
        try:
            if analysis.getKeyword() == analysis_keyword:
                matches.append(analysis)
        except Exception:
            continue
    return matches


def sample_id_of(analysis):
    """返回分析所属登记样品（AR）的 ID，如 `AAP260920001`；取不到返回 u""

    ★ 与 `services/session_store.py` 的 `sample_id_of` **同口径**（先问分析，
    再回退到父对象 id）。这里自带一份是为了让本模块保持"按文件路径即可单测"。
    """
    try:
        get_request_id = getattr(analysis, "getRequestID", None)
        if get_request_id is not None:
            request_id = get_request_id()
            if request_id:
                return _text(request_id)
    except Exception:
        pass
    try:
        from bika.lims import api
        return _text(api.get_id(api.get_parent(analysis)) or u"")
    except Exception:
        return u""


def resolve_analysis(worksheet, analysis_keyword, sample_id=None):
    """把"分析 keyword"解析成**唯一一个**分析对象；不唯一就拒绝

    :returns: `(analysis, status, message)`

    | 情形 | status | message |
    |---|---|---|
    | 命中 1 个 | `u""` | `u""` |
    | 命中 0 个 | `MISSING_ANALYSIS` | 空 |
    | 命中多个、未给 `sample_id` | `AMBIGUOUS_ANALYSIS` | 候选样品清单（点名） |
    | 命中多个、给了 `sample_id` 但过滤后 ≠ 1 个 | `AMBIGUOUS_ANALYSIS` | 说明过滤结果 |

    ★ 绝不做"取第一个"的兜底：这个分支错一次的后果是**把数据写进别的样品**，
    而且 diff 也是拿错样品比的 —— dry-run 也发现不了。
    """
    matches = find_analyses(worksheet, analysis_keyword)
    if not matches:
        return None, u"MISSING_ANALYSIS", u""
    if len(matches) == 1:
        return matches[0], u"", u""

    candidates = [sample_id_of(item) or u"(未知样品)" for item in matches]
    if sample_id:
        wanted = _text(sample_id)
        selected = [item for item, candidate in zip(matches, candidates)
                    if candidate == wanted]
        if len(selected) == 1:
            return selected[0], u"", u""
        return None, u"AMBIGUOUS_ANALYSIS", (
            u"%s 在 WorkSheet 里命中 %d 个分析，按样品「%s」过滤后剩 %d 个"
            u"（候选样品：%s）"
            % (analysis_keyword, len(matches), wanted, len(selected),
               u"、".join(sorted(set(candidates)))))

    return None, u"AMBIGUOUS_ANALYSIS", (
        u"%s 在 WorkSheet 里命中 %d 个分析（分属样品：%s）—— "
        u"一张 WorkSheet 装多个样品时必须指明样品，否则会写错样品"
        % (analysis_keyword, len(matches),
           u"、".join(sorted(set(candidates)))))


def _interim(analysis, keyword):
    """返回分析的该 interim 定义；没有返回 None"""
    for interim in analysis.getInterimFields() or []:
        if interim.get("keyword") == keyword:
            return interim
    return None


def read_interim_array(analysis, keyword):
    """读一个数组 interim → `list[str]`

    :returns: `None` = 该 interim 不存在 / 不是 JSON 数组（**不可当布局用**）；
        `[]` = 存在但为空（长度 0，会被列长校验拦下）
    """
    if _interim(analysis, keyword) is None:
        return None
    raw = _text(analysis.getInterimValue(keyword))
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if not isinstance(parsed, list):
        return None
    return [_text(value) for value in parsed]


def plan_skeleton(analysis, interim_keyword, row_key, slot_rows, warnings):
    """建槽 / 补空列：目标列为空时，按本次报告（或现有骨架）生成整列值

    :returns: `(keys, values, notes)`；不该建、建不了时返回 `None`
        —— 返回 `None` 时由 `merge_slot_rows()` 走既有路径并给出告警。

    两种场景（**都由本函数负责**）：

    | 场景 | 行键列 | 目标列 | 做法 |
    |---|---|---|---|
    | **空单建槽** | 空 | 空 | 按本次报告的槽位结构**同时**生成行键列与目标列 |
    | **空列补值** | **有值** | 空 | 按**现有行键列**的槽位结构生成目标列（长度对齐行键列） |

    ★ 为什么需要建槽：槽位落位是「用行键列定连续块 + 原位替换」，**空单没有骨架**
      就无处落位（实测 WS-007 的峰级数组全为空 → 全部 `SLOT_LAYOUT_ERROR`）。
      生产上这些数组本应由前置步骤产生，但报告导入作为第一手数据源也应当能自举。

    ★ 为什么需要「空列补值」（2026-09-22 新增）：实测 WS-007 的 `imp_name` 是
      **空列**（`g_sample_id` 有 84 值、`imp_name` 0 值）—— 骨架已由前置步骤产生、
      名称列还没填。此时 `merge_slot_rows()` 会因「目标列 0 个值 ≠ 行键列 84 个值」
      整组拒绝，而旧版 `plan_skeleton()` 又因「行键列已有值」直接返回 `None`
      ⇒ **两条路径都不接**。本分支按现有行键列的槽位结构补出目标列骨架。

    ★ 为什么要求「本组槽位全部取到值」：**各槽位宽度不一样**（实测 `imp_repeat`
      的 6 个槽位是 12/14/12/12/12/11），漏掉哪个槽位就无从知道它该多宽 ——
      宁可整组不建（点名列清楚缺谁），也不编造宽度去补空位。
    """
    keys_now = read_interim_array(analysis, row_key)
    if keys_now is None:
        # 行键列不存在 / 不是数组：骨架写不出来
        return None
    current = read_interim_array(analysis, interim_keyword)
    if current is None or current:
        # 目标列不存在（不是数组）/ 已有值（走原位替换）
        return None

    missing = [row for row in slot_rows if not (row.get(u"value") or [])]
    if missing:
        warnings.append(
            u"%s.%s：目标列与行键列 `%s` 都为空，本应建槽，但本次报告没取到槽位 %s "
            u"的值 —— 建槽要求整组槽位都有值（各槽位宽度不同，缺一个就无从知道它该"
            u"多宽，不编造空位），整组跳过"
            % (slot_rows[0][u"analysis_keyword"], interim_keyword, row_key,
               u"、".join(_text(row[u"slot"]) for row in missing)))
        return None

    if keys_now:
        # ★ 空列补值：骨架已存在，按**现有行键列**的槽位结构生成目标列
        return _plan_empty_column(analysis, interim_keyword, row_key,
                                  keys_now, slot_rows, warnings)

    keys = []
    values = []
    notes = []
    for row in slot_rows:
        slot = _text(row[u"slot"])
        slot_values = [_text(value) for value in row[u"value"]]
        keys.extend([slot] * len(slot_values))
        values.extend(slot_values)
        notes.append(u"建槽 %s ← %s（%d 值）"
                     % (slot, row[u"sample_name"], len(slot_values)))
    return keys, values, notes


def _plan_empty_column(analysis, interim_keyword, row_key, keys_now, slot_rows,
                       warnings):
    """空列补值：按**现有行键列**的槽位结构生成目标列整列值

    :returns: `(keys, values, notes)`；不可补时返回 `None`（原因进 warnings）

    ★ 布局的权威是**现有行键列**（不是本次报告）：每个槽位的宽度 = 该槽位在行键列里的
      连续块长度。本次报告取到的值个数必须**等于块长**，否则不写该槽位
      （宁可漏写，不可按顺序兜底 —— 与 `merge_slot_rows` 同一口径）。

    ★ 目标列骨架 = 与行键列**等长**的**空串列表**，被报告覆盖的槽位原位填入取值。
      未落位的槽位保持**空串**（目标列本身就是空的，补空列这一轮只负责把它覆盖到的
      槽位填上）—— **绝不能用行键值去占位**：行键是 `1..6`/`未破坏`/`碱破坏` 这类
      结构标识，写进名称/数值列会让脏数据混入结果列（实测风险）。

    ★ 要求**本组配置的所有槽位都落上**才写：空列补值的目标是把一整根空列按行键列的
      槽位结构填齐。只要有一个配置槽位没落上（行键列里没有该槽位 / 块长不符），就说明
      本次报告没取全 —— 此时只补一部分会掩盖"缺槽"这个数据缺口，宁可整组不建、点名缺谁。
    """
    label = u"%s.%s" % (slot_rows[0][u"analysis_keyword"], interim_keyword)

    #: 目标列骨架：与行键列等长的空串列表（长度天然对齐；未落位槽位保持空串）
    merged = [u""] * len(keys_now)
    notes = []
    failed = []
    for row in slot_rows:
        slot = _text(row[u"slot"])
        runs = find_slot_runs(keys_now, slot)
        if not runs:
            failed.append(u"「%s」不存在于行键列" % slot)
            continue
        if len(runs) > 1:
            failed.append(u"「%s」分成 %d 段" % (slot, len(runs)))
            continue
        start, end = runs[0]
        values = [_text(value) for value in row[u"value"]]
        if len(values) != (end - start):
            failed.append(u"「%s」块长 %d、取到 %d（来源 %s）"
                          % (slot, end - start, len(values),
                             row[u"sample_name"]))
            continue
        merged[start:end] = values
        notes.append(u"补空列 %s ← %s（%d 值，位置 %d-%d）"
                     % (slot, row[u"sample_name"], len(values),
                        start, end - 1))

    if failed:
        # 任意一个配置槽位没落上 → 整组拒绝，点名缺谁（不掩盖数据缺口）
        warnings.append(
            u"%s：目标列为空、行键列 `%s` 有 %d 值，但本次报告没取全 —— "
            u"槽位 %s —— 空列补值要求整组槽位都落上，整组跳过"
            % (label, row_key, len(keys_now), u"、".join(failed)))
        return None
    if not notes:
        # 一个槽位都没落上：不写（否则会把"什么都没写"误报成已对齐）
        warnings.append(
            u"%s：目标列为空、行键列 `%s` 有 %d 值，但本次报告没有一个槽位"
            u"能对上块长 —— 整组跳过" % (label, row_key, len(keys_now)))
        return None
    return list(keys_now), merged, notes


def merge_slot_rows(analysis, interim_keyword, slot_rows, warnings):
    """把若干**槽位行**合并进目标列的现值 → `(next_values, current_values, notes)`

    ★ 布局的权威是分析上**现有的行键列**（`g_sample_id` / `imp_deg_id` /
    `imp_qc_point`）：用它定出每个槽位的连续块，再在目标列里**原位替换**这一段。

    ★ 整组不可写（拿不到布局 / 列长不一致 / 配置重复）→ `next_values is None`
    并把原因写进 warnings；单个槽位不可写 → 只跳过该槽位，其余照写。

    ★ **空单的骨架由 `plan_skeleton()` 负责**（目标列与行键列都为空时自举建槽）；
    本函数只在"已有骨架"时做原位替换。行键列里没有该槽位、或目标列不存在 → 跳过
    （宁可漏写，不可按顺序兜底猜落位）。
    """
    label = u"%s.%s" % (slot_rows[0][u"analysis_keyword"], interim_keyword)

    row_keys = sorted(set(row[u"row_key"] for row in slot_rows))
    if len(row_keys) != 1:
        warnings.append(u"%s 的槽位行配了多个「行键列」（%s）—— 整组跳过"
                        % (label, u"、".join(row_keys)))
        return None, None, []
    row_key = row_keys[0]

    slots = {}
    for row in slot_rows:
        slot = row[u"slot"]
        if slot in slots:
            warnings.append(
                u"%s 的槽位「%s」配了两次（来源 %s / %s）—— 取哪个都是猜，整组跳过"
                % (label, slot, slots[slot][u"sample_name"], row[u"sample_name"]))
            return None, None, []
        slots[slot] = row

    keys = read_interim_array(analysis, row_key)
    if not keys:
        warnings.append(
            u"%s：行键列 `%s` 在分析上不存在或为空（不是数组）—— 没有布局就"
            u"定位不了槽位，整组跳过" % (label, row_key))
        return None, None, []

    current = read_interim_array(analysis, interim_keyword)
    if current is None:
        warnings.append(
            u"%s：目标列在分析上不存在或不是数组 —— 整组跳过（本期不建槽）"
            % label)
        return None, None, []
    if len(current) != len(keys):
        warnings.append(
            u"%s：目标列 %d 个值、行键列 `%s` %d 个值 —— 列长不一致，"
            u"按行替换必然错位，整组跳过"
            % (label, len(current), row_key, len(keys)))
        return None, None, []

    merged = list(current)
    notes = []
    for slot in sorted(slots):
        row = slots[slot]
        runs = find_slot_runs(keys, slot)
        if not runs:
            warnings.append(
                u"%s：行键列 `%s` 里没有槽位「%s」（现值为 %s）—— 跳过该槽位"
                % (label, row_key, slot, u"、".join(sorted(set(keys)))))
            continue
        if len(runs) > 1:
            warnings.append(
                u"%s：槽位「%s」在行键列里分成 %d 段（中间夹着别的行）—— "
                u"分不出写哪一段，跳过该槽位" % (label, slot, len(runs)))
            continue
        start, end = runs[0]
        values = row[u"value"]
        if len(values) != (end - start):
            warnings.append(
                u"%s：槽位「%s」现值 %d 个、本次取到 %d 个（来源 %s）—— "
                u"不覆盖，跳过该槽位"
                % (label, slot, end - start, len(values), row[u"sample_name"]))
            continue
        merged[start:end] = values
        notes.append(u"槽位 %s ← %s（%d 值，位置 %d-%d）"
                     % (slot, row[u"sample_name"], len(values),
                        start, end - 1))
    return merged, current, notes


def _attachment_file_names(obj):
    """附件里那个文件的文件名（读法逐条兜底）

    ★ 为什么不能只写一种读法：`AttachmentFile` 在不同基线里可能是
      Archetypes 字段（`getField().get()`）、也可能是普通属性/访问器。
      读不到就返回空 —— 少一个比对名，只会让去重退化成"多存一个附件"，
      不会写错数据。
    """
    candidates = []
    try:
        field = obj.getField("AttachmentFile")
        if field is not None:
            candidates.append(field.get(obj))
    except Exception:
        pass
    try:
        candidates.append(getattr(obj, "AttachmentFile", None))
    except Exception:
        pass
    try:
        getter = getattr(obj, "getAttachmentFile", None)
        if getter is not None:
            candidates.append(getter())
    except Exception:
        pass

    names = []
    for candidate in candidates:
        filename = _text(getattr(candidate, "filename", u""))
        if filename:
            names.append(filename)
    return names


def _attachment_names(obj):
    """附件可用来比对的名字：`Title()` / `getId()` / 上传文件名

    ★ 为什么三个都要：SENAITE 的 `Attachment` 建好后 `Title()` 是自增 id
    （实测是 `attachment-23` 这种），`api.create(..., title=...)` 传进去的报告
    文件名**没有落到 `Title()` 上**，只认 `Title()` 会导致去重完全失效。
    """
    names = []
    for getter in (lambda: obj.Title(), lambda: obj.getId()):
        try:
            name = _text(getter())
        except Exception:
            name = u""
        if name:
            names.append(name)
    return names + _attachment_file_names(obj)


def _name_key(value):
    """比名字用的归一形式：只留文件名（去掉目录、统一斜杠）

    ★ 自动导入给的是**容器内全路径**（`/data/dcu_auto_import/WS-007_1 SYS.pdf`），
      而附件里存的是裸文件名 —— 不归一就永远比不上。
    """
    text = _text(value).replace(u"\\", u"/")
    return text.rsplit(u"/", 1)[-1]


def _read_file_bytes(value):
    """任一文件形态 → 原始字节（用于内容指纹，见 `find_attachment`）

    兼容 `FileUpload` / Archetypes `NamedBlobFile` / ZodbFile 等常见形态；
    读不到返回 `None`（调用方据此降级为"不做内容比对"）。
    """
    try:
        if hasattr(value, "getBlob"):
            blob = value.getBlob()
            if blob is not None:
                with blob.open("r") as handle:
                    return handle.read()
        if hasattr(value, "read"):
            stream = value.read()
            if stream is not None:
                return stream
        return None
    except Exception:
        return None


def _attachment_digest(value):
    """文件内容 → sha256（十六进制）；读不到返回 `None`"""
    data = _read_file_bytes(value)
    if data is None:
        return None
    try:
        import hashlib
        return hashlib.sha256(data).hexdigest()
    except Exception:
        return None


def find_attachment(worksheet, title, file_bytes=None):
    """WorkSheet 下是否已有**内容一致**的同名附件（重复导入不产生重复附件）

    :param file_bytes: 本次上传文件的原始字节（可为 `None`）。给定时，同名附件还须
        **内容指纹一致**才复用（#4）—— 同名但内容是对应报告的**新版本**时，静默复用
        旧附件会让追溯留档停在旧版，属"留档丢失"，这里不静默、报冲突。
    :returns: 可复用的 `Attachment` 对象；无同名附件 / 同名但内容不一致 → `None`
        （调用方据此新建或报错）。同名但内容不一致时在 `warnings` 里点名。
    """
    wanted = _name_key(title)
    if not wanted:
        return None
    digest = _attachment_digest(file_bytes) if file_bytes is not None else None
    try:
        for obj in worksheet.objectValues():
            if getattr(obj, "portal_type", None) != "Attachment":
                continue
            if wanted not in [_name_key(name) for name in _attachment_names(obj)]:
                continue
            if digest is not None:
                existing = _attachment_digest(
                    obj.getField("AttachmentFile").get(obj))
                if existing is not None and existing != digest:
                    # 同名但内容不同：这是报告的新版本，不能静默复用旧附件
                    continue
            return obj
    except Exception:
        pass
    return None


def _attach_report(worksheet, attachment_file, title, analyses):
    """报告 PDF 留档：挂到目标 WorkSheet + 链接到本次写入的分析

    :returns: `(ok, message)`；`ok=False` 时 message 说明原因
    """
    try:
        # ★ 延迟导入：`browser/deemo` 那侧在模块级 import 本模块，反过来 import 会成环
        from maitux.instrument_acquisition.browser.deemo import (
            instrument_acquisition_test as debug)
    except Exception as exc:
        return False, u"附件留档失败（装载附件工具出错）：%s" % exc

    title = _text(title) or u"Instrument report"
    try:
        file_bytes = _read_file_bytes(attachment_file)
        attachment = find_attachment(worksheet, title, file_bytes)
        if attachment is None:
            # 无同名附件，或同名但内容不一致（报告新版本，#4）→ 新建留档。
            # 创建前 `_rewind_upload` 会消耗上传指针，这里先回卷再交出去。
            try:
                attachment_file.seek(0)
            except Exception:
                pass
            attachment = debug._create_worksheet_attachment(
                worksheet, attachment_file, title)
        if attachment is None:
            return False, u"附件留档失败：无法在 WorkSheet 上创建附件「%s」" % title
        # ★ #3：每个分析都必须成功链接到附件，任一失败都算整体失败 ——
        #   留档不完整（某个分析没挂上附件）会把追溯性缺口悄悄吞掉。
        failures = []
        for analysis in analyses or []:
            ok = debug._append_attachment_to_analysis(analysis, attachment)
            if not ok:
                try:
                    name = _text(analysis.Title()) or _text(
                        analysis.getId()) or u"未知分析"
                except Exception:
                    name = u"未知分析"
                failures.append(name)
        if failures:
            return False, (u"附件留档失败：%d 个分析未能链接附件，名单：%s"
                           % (len(failures), u"、".join(failures)))
        return True, u""
    except Exception as exc:
        return False, u"附件留档失败：%s" % exc


def should_write(status, allow_overwrite=False):
    """该 diff 状态是否允许写入

    - `MATCH`（现值与本次逐字符相同）/ `NEW`（现值空）：恒允许
    - `DIFF`（现值不同）：**默认不写**，需显式 `allow_overwrite`

    ★ 为什么默认不覆盖：**自动导入（目录 → `@@auto_import_results`）没有人工复核**
    （手工调试页有 diff 可看）。站点现值可能是人改过的，静默覆盖属于"写错"。

    ★ 注意 `MATCH` 仍会写（写的是同一个值，属无害的幂等动作），
    这样附件留档 / 审计口径保持一致。
    """
    if status == u"DIFF":
        return bool(allow_overwrite)
    return status in (u"MATCH", u"NEW")


def run(parsed, confirm=False, sample_id=None, allow_overwrite=False,
        attachment=None, attachment_title=u""):
    """报告落位：`confirm=False` 只出 dry-run diff；`True` 才真正写入

    ★ 目标位从 `keyword_glossary` 页面读（页面是唯一权威）：
    页面未勾选任何行 → **不落位**，并明确告警（不静默）。

    :param sample_id: **本次导入归属的登记样品**（如 `AAP260920001`）。
        一张 WorkSheet 装多个样品、且它们有**同名分析**时（实测 WS-001/WS-004），
        靠它把同名分析收敛到唯一一个；**不传则命中多个就拒绝该目标位**
        （`AMBIGUOUS_ANALYSIS`，绝不"取第一个"）。
        调用方如何拿到它（报告正文的样品段 / 页面选择）属于后续工作，
        见 `doc/仪器采集/DCU-多样品Worksheet影响分析.md` §4 的 P1。

    :param allow_overwrite: 现值与本次**不同**（`DIFF`）时是否允许覆盖。
        默认 `False`（自动导入无人复核 → 不碰已有不同值，状态记
        `SKIPPED_OVERWRITE`）；手工路径要覆盖必须显式传 `True`。

    :param attachment: 报告 PDF（强制留档）。写入成功后挂到目标 WorkSheet，
        并链接到本次写入的每个分析；**挂附件失败视为本次失败**
        （追溯性缺失属质量事件，宁可让文件留在 failed/ 等人工处理）。

    :returns: (success, message, details)
    """
    from bika.lims import api
    from maitux.instrument_acquisition.services import report_targets
    from maitux.instrument_acquisition.services.writeback import write_interim

    if not is_report_payload(parsed):
        return False, u"不是报告解析产物，无法按报告导入落位", {
            "mode": "plan", "diff": [], "warnings": [],
        }

    targets, warnings = report_targets.load_targets()
    if not targets:
        return False, (
            u"报告导入：页面（keyword_glossary）没有可用的落位目标位配置，"
            u"未写入任何数据"), {
            "mode": "plan", "diff": [], "warnings": warnings,
        }

    rows, row_warnings = plan_rows(parsed, targets)
    warnings = list(warnings) + list(row_warnings)
    if not rows:
        return False, u"报告导入：没有可落位的目标位（见 warnings）", {
            "mode": "plan", "diff": [], "warnings": warnings,
        }

    report = parsed.get("report") or {}
    worksheet_id = _text(report.get("worksheet_id"))
    if not worksheet_id:
        # ★ 临时桥接：正文没有 WS-ID 时，允许用上传文件名前缀顶上
        #   （见 `worksheet_id_from_name()`；实验室按规范出报告后此路径自然失效）
        worksheet_id = worksheet_id_from_name(_upload_name(attachment))
        if worksheet_id:
            warnings.append(
                u"报告正文没有 WorkSheet ID，改用上传文件名前缀「%s」；"
                u"实验室按命名规范（Sample Set Name 只写 `WS-007`）出报告后，"
                u"这条兜底路径不会再被用到" % worksheet_id)
    worksheet = find_worksheet(worksheet_id)
    if worksheet is None:
        return False, (
            u"报告导入：找不到 WorkSheet「%s」。报告正文里没有 WorkSheet ID 时，"
            u"需先按命名规范把 Sample Set Name 写成 `WS-007`，"
            u"或把文件命名为 `WS-007_报告名.pdf`"
            % worksheet_id), {
            "mode": "plan", "diff": [], "warnings": warnings,
        }

    diff = []
    writable = 0
    skipped_overwrite = 0
    analysis_cache = {}
    #: `(分析, interim)` → 要写入的整列值；槽位行在这里已被合并成整列
    write_values = {}
    #: `(分析, 行键列)` → 本次自举出来的骨架（同一行键列只建一次，两次必须一致）
    skeletons = {}
    for key, bucket in group_plan_rows(rows, warnings):
        analysis_keyword, interim_keyword = key
        whole = bucket[u"whole"]
        slot_rows = bucket[u"slots"]
        first = whole or slot_rows[0]
        item = {
            u"analysis_keyword": analysis_keyword,
            u"interim_keyword": interim_keyword,
            u"sample_name": whole[u"sample_name"] if whole else u"；".join(
                u"%s ← %s" % (row[u"slot"], row[u"sample_name"])
                for row in slot_rows),
            u"title": first[u"title"],
            u"injection_count": sum(row[u"injection_count"] for row in slot_rows)
                                if slot_rows else first[u"injection_count"],
            u"current": u"",
            u"next": u"",
            u"status": u"",
            u"same_ignoring_spaces": False,
            u"hint": u"",
        }
        keyword = analysis_keyword
        if keyword not in analysis_cache:
            analysis_cache[keyword] = resolve_analysis(
                worksheet, keyword, sample_id)
        analysis, resolve_status, resolve_message = analysis_cache[keyword]

        if analysis is None:
            # ★ 0 命中（MISSING_ANALYSIS）或**命中多个**（AMBIGUOUS_ANALYSIS）：
            #   都不猜。后者还要把候选样品写进 diff 与 warnings，让人看得见。
            item[u"status"] = resolve_status or u"MISSING_ANALYSIS"
            item[u"hint"] = resolve_message
            if resolve_message:
                warnings.append(resolve_message)
            diff.append(item)
            continue
        if _interim(analysis, interim_keyword) is None:
            item[u"status"] = u"MISSING_INTERIM"
            diff.append(item)
            continue

        if whole is not None:
            current = analysis.getInterimValue(interim_keyword)
            next_values = whole[u"value"]
            item[u"next"] = whole[u"value_text"]
        else:
            # ★ 峰级"多列同行"：用行键列定出各槽位的连续块，原位替换（见 §模块 docstring）
            #   空单（目标列与行键列都为空）先自举建槽 —— 见 plan_skeleton()
            row_key = _text(slot_rows[0][u"row_key"]) if slot_rows else u""
            skeleton = None
            if row_key:
                skeleton = plan_skeleton(analysis, interim_keyword, row_key,
                                         slot_rows, warnings)
            if skeleton is not None:
                skeleton_keys, merged, notes = skeleton
                cache_key = (analysis_keyword, row_key)
                known = skeletons.get(cache_key)
                if known is not None and known != skeleton_keys:
                    # 同一行键列被两个目标列共用：骨架必须完全一致，否则数组错位
                    warnings.append(
                        u"%s：同一个行键列 `%s` 上两次建槽的槽位结构不一致 —— "
                        u"按行替换必然错位，跳过 %s"
                        % (analysis_keyword, row_key, interim_keyword))
                    item[u"status"] = u"SLOT_LAYOUT_ERROR"
                    diff.append(item)
                    continue
                if known is None:
                    skeletons[cache_key] = skeleton_keys
                    # ★ 只有「空单建槽」才把行键列本身也当成要写的目标位；
                    #   「空列补值」时行键列**已有值**，不能重写它（会覆盖现有骨架）
                    if not read_interim_array(analysis, row_key):
                        write_values[cache_key] = skeleton_keys
                        writable += 1
                        # 行键列本身也是一个要写的目标位（骨架），单独出一条 diff
                        diff.append({
                            u"analysis_keyword": analysis_keyword,
                            u"interim_keyword": row_key,
                            u"sample_name": item[u"sample_name"],
                            u"title": item[u"title"],
                            u"injection_count": item[u"injection_count"],
                            u"current": u"",
                            u"next": json.dumps(skeleton_keys,
                                               ensure_ascii=False),
                            u"status": u"NEW",
                            u"same_ignoring_spaces": False,
                            u"hint": u"建槽：行键列（骨架）",
                        })
                item[u"hint"] = u"；".join(notes)
                item[u"next"] = json.dumps(merged, ensure_ascii=False)
                # ★ 空列补值：现值是空数组（`[]`），diff 里按空串展示，
                #   状态由下面的 compare_value 判成 `NEW`（可写）
                current = u""
                next_values = merged
            else:
                merged, current_values, notes = merge_slot_rows(
                    analysis, interim_keyword, slot_rows, warnings)
                item[u"hint"] = u"；".join(notes)
                if merged is None:
                    item[u"status"] = u"SLOT_LAYOUT_ERROR"
                    diff.append(item)
                    continue
                if not notes:
                    # ★ 一个槽位都没落上（块长不符 / 槽位不存在）时合并结果与现值相同，
                    #   若照常比就会报成 MATCH —— 那是"什么都没写"被误读成"已对齐"
                    #   （实测 `PDA.pdf`：同名的 `ACC-100%-SPIKED-1(T0)` 只有 10 峰，
                    #   槽位块是 14 值 → 全跳过）。所以单列一个状态，不写、不算可写。
                    item[u"status"] = u"SLOT_SKIPPED"
                    diff.append(item)
                    continue
                current = json.dumps(current_values, ensure_ascii=False)
                next_values = merged
                item[u"next"] = json.dumps(merged, ensure_ascii=False)

        item[u"current"] = _text(current)
        item[u"status"], item[u"same_ignoring_spaces"] = compare_value(
            current, item[u"next"])
        if not should_write(item[u"status"], allow_overwrite):
            # ★ 现值与本次不同、又没授权覆盖：不写并点名（自动导入无人复核，
            #   站点现值可能是人改过的 —— 静默覆盖属于"写错"）
            item[u"status"] = u"SKIPPED_OVERWRITE"
            skipped_overwrite += 1
            warnings.append(
                u"%s.%s 现值与本次不同，且未授权覆盖 —— 跳过（现值 %s）"
                % (analysis_keyword, interim_keyword,
                   describe_value(item[u"current"])))
            diff.append(item)
            continue
        write_values[key] = next_values
        writable += 1
        diff.append(item)

    details = {
        "mode": u"write" if confirm else u"dry-run",
        "worksheet_id": worksheet_id,
        "worksheet_uid": api.get_uid(worksheet),
        "worksheet_title": api.get_title(worksheet),
        "diff": diff,
        "warnings": warnings,
        "writable": writable,
        "written": 0,
        "errors": [],
    }

    if not confirm:
        return True, (
            u"报告导入 dry-run：%d 个目标位可写（未写入任何数据），"
            u"请核对 diff 后确认" % writable), details

    errors = []
    written = 0
    written_analyses = []
    written_uids = set()
    # ★ 必须按 (分析, interim) 建索引，**不能只按 interim keyword**：
    #   `imp_lin_a1` 同时在 `imp_linearity`（3 值）与 `imp_linearity_shared`
    #   （6 值）上存在，只按字段名索引会让后者取到前者的值（静默写错）。
    for item in diff:
        if item[u"status"] not in (u"MATCH", u"DIFF", u"NEW"):
            continue
        # ★ `analysis_cache` 存的是 `(分析, 状态, 消息)` 三元组：取 [0]。
        #   （此处曾直接把三元组传给 write_interim → 必然 AttributeError）
        analysis = analysis_cache[item[u"analysis_keyword"]][0]
        key = (item[u"analysis_keyword"], item[u"interim_keyword"])
        try:
            write_interim(analysis, item[u"interim_keyword"], write_values[key])
            written += 1
            item[u"status"] = u"WRITTEN"
            uid = api.get_uid(analysis)
            if uid not in written_uids:
                written_uids.add(uid)
                written_analyses.append(analysis)
        except Exception as exc:
            errors.append(u"%s: %s" % (item[u"interim_keyword"], exc))
            item[u"status"] = u"WRITE_ERROR"

    # ★ 报告 PDF 强制留档：挂到目标 WorkSheet，并链接到本次写入的每个分析
    attached = False
    if attachment is not None and written:
        attached, attach_message = _attach_report(
            worksheet, attachment, attachment_title, written_analyses)
        if not attached:
            errors.append(attach_message)

    details["written"] = written
    details["skipped_overwrite"] = skipped_overwrite
    details["attached"] = attached
    details["errors"] = errors
    if errors:
        return False, u"报告导入：写入 %d 个目标位，%d 个失败" % (
            written, len(errors)), details
    if written == 0:
        # ★ #5：一个目标位都没写进去 → 视为失败。调用方（自动导入）据此把文件
        #   移进 `failed/` 以便重投；若这里错误地报成功，自动导入会把"根本没写"
        #   当成一次成功导入记账，文件也不再重投（数据缺口被静默吞掉）。
        #   覆盖场景同理：所有的 DIFF 都因未授权覆盖而跳过，本次仍**没有**写入。
        return False, (
            u"报告导入：没有任何目标位被写入（%d 个可写项全被跳过/未匹配）—— "
            u"请核对 diff 与告警" % writable), details

    message = u"报告导入：已写入 %d 个目标位" % written
    if skipped_overwrite:
        message += u"；%d 个目标位现值不同、未授权覆盖，已跳过" % skipped_overwrite
    if attached:
        message += u"；报告 PDF 已留档"
    return True, message, details
