# -*- coding: utf-8 -*-
"""报告落位目标位 —— **从 `keyword_glossary` 页面读配置**（唯一权威）

页面列（`maitux.glossary` 的 GlossaryEntry 行，人工维护）：

| 页面列 | 字段 | 含义 |
|---|---|---|
| 报告导入目标位 | `acq_enabled` | 勾选 = 该公式字段是落位目标位 |
| 来源 SampleName | `acq_source_sample` | 报告正文里供数的 SampleName（如 `STD-1` / `SYS`） |
| 取值规则 | `acq_pick` | 该针怎么取值（受控词表，见下） |
| 写法 | `acq_decimals` | 保留几位小数（空 = 原样） |
| 期望长度 | `acq_length` | 针数/峰数；不符即跳过（0 = 不校验） |
| 第 N 针 | `acq_injection` | 只取该来源的第 N 针（0 = 全部针按序拼接） |
| 取前 N 峰 | `acq_peaks` | 每针只取前 N 个峰（0 = 全部峰） |
| 目标 RT | `acq_rt` | 只保留 RT 落在 ±0.5 min 窗口内的峰（0 = 不筛） |
| 峰序号清单 | `acq_peak_indexes` | 只保留这些峰序号（如 `3,6,7,8,15,16`；空 = 不筛） |
| 行键列 | `acq_row_key` | **`row-sync` 用**：数组的行键列名（如 `g_sample_id` / `imp_deg_id` / `imp_qc_point`） |
| 行槽位 | `acq_slot` | **`row-sync` 用**：本次落位写入的行键取值（如 `1` / `未破坏`） |
| 排除 RT | `acq_drop_rt` | 剔除 RT 落在任一值 ±0.5 min 内的峰（空 = 不剔除） |

★ **`row-sync`（峰级"多列同行"）靠 `acq_row_key` + `acq_slot` 表达**：峰级数组是
**扁平列表 + 行键列重复标号**（实测 `imp_chrom` 的 `g_sample_id` 是 `1..6` 各 14 次，
`imp_name`/`g_rt`/`g_area` 各 84 个值），所以"写某一槽位"= 用行键列定出该槽位的
**连续块**、再原位替换目标列的这一段。

★ **一个目标列要写多个槽位**（`imp_chrom.g_rt` 要写槽 1–6），而页面上同一
`(分析, 目标列)` **只有一行** —— 所以槽位模式下：

| 页面列 | 形态 | 例 |
|---|---|---|
| 来源 SampleName | **逗号分隔清单** | `ACC-100%-SPIKED-1(T0), ACC-100%-SPIKED-2` |
| 行槽位 | **逗号分隔清单** | `1, 2` |

两个清单**按位置一一对应、必须等长**（不等长 = 配置错，点名拒绝整行）。
非槽位行（Step 1/2 的整列语义）两个清单都不填，来源仍是单值。

★ **`acq_drop_rt` 是站点自己的"报告阈值"口径**（实测逼出来的）：同一针在站点
不同分析里存的峰表不同 —— `imp_chrom` 槽 1 与报告 15 峰只差 RT 47.479（area 1065），
`imp_degradation` 与报告只差 RT 10.122，`imp_repeat` 一个都不少。站点现值是验收基准，
所以把"剔除哪些 RT"显式配出来（不猜阈值规则）。

★ **代码里不再有目标位默认值**：页面没配 → 不落位（宁缺勿错），
且在 dry-run 结果里**明确告警**（绝不静默"什么都没发生"）。

★ 本模块顶层不 import bika / senaite（单测按文件路径加载）；
Zope 相关的读取在函数内延迟导入。
"""

# ---------------------------------------------------------------------------
# 受控词表（页面下拉的取值来源；页面侧的同一份词表见
# maitux.glossary.vocabularies —— 两边必须一致，改一处要同步另一处）
# ---------------------------------------------------------------------------

#: 取值规则
PICK_MAIN_PEAK_AREA = u"main_peak.area"
PICK_PEAKS_AREA = u"peaks.area"
PICK_PEAKS_RT = u"peaks.rt"
PICK_PEAKS_RESOLUTION = u"peaks.resolution"
PICK_PEAKS_SN = u"peaks.sn"
PICK_PEAKS_AREA_SUM = u"peaks.area_sum"
#: 名称类（唯一一条**字符串**取值规则，其余都是数值）
PICK_PEAKS_NAME = u"peaks.name"
PICK_RULES = (PICK_MAIN_PEAK_AREA, PICK_PEAKS_AREA, PICK_PEAKS_RT,
              PICK_PEAKS_RESOLUTION, PICK_PEAKS_SN, PICK_PEAKS_AREA_SUM,
              PICK_PEAKS_NAME)

#: 名称类取值规则集合（`pick_values` 据此走字符串分支，不走数值归一）
NAME_PICK_RULES = (PICK_PEAKS_NAME,)

#: 峰未命名（报告 Peak Name 空白）时的落位值
#:
#: ★ 客户口径（2026-09-22 确认）：Peak Name **只会出现"采集名称"或"空白"**两种，
#:   空白即未命名杂质 → 落位写本常量。
#: ★ 必须**占位**、不能跳过：峰级数组按峰序一一对应，少一个值就会让
#:   `merge_slot_rows` 的长度校验拒绝整段（或让「期望长度」闸门整行跳过）。
UNKNOWN_IMPURITY = u"未知杂质"

#: 写法（空 = 原样不格式化），与 maitux.glossary 的 AcquisitionDecimals 词表一致
DECIMALS_CHOICES = (u"", u"0", u"1", u"2", u"3")

#: 来源 SampleName 的受控角色词表（命名规范 v1.1 §4.2）
ROLE_VOCABULARY = (
    u"BLANK", u"SYS", u"STD-1", u"STD-2", u"STD-1-QC", u"ID", u"LOD", u"LOQ",
    u"LIN", u"REC-SPEC", u"REC-NS", u"DEG", u"STAB",
)

#: 批号式 SampleName（供试品/重复性，规范 §4.3(5)）
BATCH_PREFIX_RE = r"^[A-Z]{2,}[0-9]"


try:  # Python 2
    text_type = unicode  # noqa: F821
except NameError:  # Python 3
    text_type = str


def _text(value):
    if value is None:
        return u""
    if isinstance(value, text_type):
        return value.strip()
    try:
        return value.strip().decode("utf-8")
    except Exception:
        return (u"%s" % value).strip()


def _as_int(value, default=0):
    text = _text(value)
    if not text:
        return default
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _as_float(value, default=0.0):
    text = _text(value)
    if not text:
        return default
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def parse_peak_indexes(value):
    """`"3,6,7,8,15,16"` → `(3, 6, 7, 8, 15, 16)`；空 → `()`；非法 → `None`

    ★ 非法返回 `None`（而不是"忽略坏的那一段"）：调用方据此**点名拒绝**整行 ——
    这个列错一个数字的后果是"选错峰、写错值"，不能猜。
    """
    text = _text(value).replace(u"，", u",").replace(u" ", u"")
    if not text:
        return ()
    indexes = []
    for part in text.split(u","):
        if not part:
            return None
        try:
            number = int(part)
        except (TypeError, ValueError):
            return None
        if number < 1:
            return None
        indexes.append(number)
    return tuple(sorted(set(indexes)))


def parse_drop_rt(value):
    """`"10.12, 47.48"` → `(10.12, 47.48)`；空 → `()`；非法 → `None`

    ★ 与 `parse_peak_indexes` 同样**非法即 `None`**（调用方点名拒绝整行）：
    漏掉一个"该剔的 RT"会多写一个峰，多写一个"不该剔的 RT"会少写一个峰，
    两个方向的后果都是**值表与站点现值不一致**，不能猜。
    """
    text = _text(value).replace(u"，", u",").replace(u" ", u"")
    if not text:
        return ()
    targets = []
    for part in text.split(u","):
        if not part:
            return None
        try:
            number = float(part)
        except (TypeError, ValueError):
            return None
        if number <= 0:
            return None
        targets.append(number)
    return tuple(sorted(set(targets)))


def parse_text_list(value):
    """`"a, b"` → `(u"a", u"b")`；空 → `()`；有空格段 → `None`（点名拒绝）

    ★ 两个清单（来源 SampleName / 行槽位）**按位置一一对应**，所以空段不能忽略：
    `"1,,2"` 会让后一个槽位整体错位一格 —— 这类错误必须整行拒绝，不猜。
    """
    text = _text(value).replace(u"，", u",")
    if not text:
        return ()
    items = []
    for part in text.split(u","):
        part = part.strip()
        if not part:
            return None
        items.append(part)
    return tuple(items)


def source_is_batch(sample_name):
    """来源是否为批号式（供试品/重复性）：允许，但不在受控角色词表里"""
    import re
    return bool(re.match(BATCH_PREFIX_RE, _text(sample_name).upper()))


def build_target(row):
    """一行页面数据 → 目标位定义；非法返回 `(None, 原因)`

    :param row: ``{"analysis_keyword":..., "calc_keyword":...,
                   "acq_source_sample":..., "acq_pick":...,
                   "acq_decimals":..., "acq_length":...,
                   "acq_injection":..., "acq_peaks":...,
                   "acq_rt":..., "acq_peak_indexes":...,
                   "acq_row_key":..., "acq_slot":..., "acq_drop_rt":...}``
    """
    analysis_keyword = _text(row.get("analysis_keyword"))
    interim_keyword = _text(row.get("calc_keyword"))
    if not analysis_keyword or not interim_keyword:
        return None, u"行键不完整（analysis_keyword / calc_keyword 有空值）"

    sample_name = _text(row.get("acq_source_sample"))

    pick = _text(row.get("acq_pick"))
    if not pick:
        return None, u"未填「取值规则」"
    if pick not in PICK_RULES:
        return None, u"「取值规则」不在受控词表内：%s" % pick

    decimals = _text(row.get("acq_decimals"))
    if decimals not in DECIMALS_CHOICES:
        return None, u"「写法」不在受控词表内：%s" % decimals

    length = _as_int(row.get("acq_length"), 0)
    if length < 0:
        return None, u"「期望长度」不能为负：%s" % length

    injection = _as_int(row.get("acq_injection"), 0)
    if injection < 0:
        return None, u"「第 N 针」不能为负：%s" % injection

    peaks_limit = _as_int(row.get("acq_peaks"), 0)
    if peaks_limit < 0:
        return None, u"「取前 N 峰」不能为负：%s" % peaks_limit

    rt = _as_float(row.get("acq_rt"), 0.0)
    if rt < 0:
        return None, u"「目标 RT」不能为负：%s" % rt

    peak_indexes = parse_peak_indexes(row.get("acq_peak_indexes"))
    if peak_indexes is None:
        return None, (u"「峰序号清单」格式非法：%s（应为 1 起、逗号分隔的整数，"
                      u"如 3,6,7,8,15,16）"
                      % _text(row.get("acq_peak_indexes")))

    drop_rt = parse_drop_rt(row.get("acq_drop_rt"))
    if drop_rt is None:
        return None, (u"「排除 RT」格式非法：%s（应为逗号分隔的正数，"
                      u"如 10.12,47.48）" % _text(row.get("acq_drop_rt")))

    # ★ 行键列（`row-sync` 必需）/ 行槽位清单：槽位模式下"来源 SampleName"也是清单，
    #   两个清单按位置一一对应、必须等长（错配一次 = 整列数据错位）
    row_key = _text(row.get("acq_row_key"))
    slots = parse_text_list(row.get("acq_slot"))
    if slots is None:
        return None, (u"「行槽位」格式非法：%s（应为逗号分隔、段不能为空）"
                      % _text(row.get("acq_slot")))

    sources = ()
    if slots:
        if not row_key:
            return None, (u"填了「行槽位」%s 却没填「行键列」—— 落位时无法定位"
                          u"这些槽位在数组里的连续块" % _text(row.get("acq_slot")))
        sources = parse_text_list(sample_name)
        if not sources:
            return None, (u"填了「行槽位」时「来源 SampleName」必须是逗号分隔的"
                          u"清单（与行槽位**按位置一一对应**）")
        if len(sources) != len(slots):
            return None, (
                u"「来源 SampleName」%d 个、与「行槽位」%d 个不等长 —— "
                u"两个清单按位置一一对应，错配一次就是整列数据错位"
                % (len(sources), len(slots)))
        # ★ 槽位唯一性：同一个槽位只能配一个来源，两个来源抢一个槽位 = 整列数据
        #   被后者覆盖前者（静默丢数据）。必须在配置阶段就点名拒绝。
        seen = {}
        for idx, slot in enumerate(slots):
            if slot in seen:
                return None, (
                    u"「行槽位」里槽位「%s」被重复配置 %d 次 —— 同一目标位的"
                    u"连续块只能由一个来源写，删掉多余配置（重复处第 %d / %d 位）"
                    % (slot, slots.count(slot), seen[slot] + 1, idx + 1))
            seen[slot] = idx
    else:
        if row_key:
            return None, (u"填了「行键列」%s 却没填「行槽位」—— 不知道要写哪一行"
                          % row_key)
        if not sample_name:
            return None, u"未填「来源 SampleName」"

    warnings = []
    for name in (sources or (sample_name,)):
        if not name:
            continue
        if name.upper() not in ROLE_VOCABULARY and not source_is_batch(name):
            warnings.append(
                u"%s.%s 的来源「%s」既不在受控角色词表、也不是批号式 —— "
                u"必须与报告正文里的 SampleName 逐字符一致"
                % (analysis_keyword, interim_keyword, name))

    return {
        u"analysis_keyword": analysis_keyword,
        u"interim_keyword": interim_keyword,
        u"sample_name": sample_name,
        u"pick": pick,
        u"decimals": None if decimals == u"" else int(decimals),
        u"expected_length": length or None,
        u"injection": injection or None,
        u"peaks_limit": peaks_limit or None,
        u"rt": rt or None,
        u"peak_indexes": peak_indexes or None,
        u"row_key": row_key,
        u"sources": sources,
        u"slots": slots,
        u"drop_rt": drop_rt or None,
        u"title": _text(row.get("zh")) or u"%s.%s" % (analysis_keyword,
                                                      interim_keyword),
    }, u"；".join(warnings)


def load_targets(portal=None):
    """读页面配置 → `(targets, warnings)`

    - glossary 未安装 / 容器不存在 / 未勾选任何行 → targets 为空 + **明确告警**
    - 单行非法 → 跳过该行并在 warnings 里点名（不静默）
    """
    warnings = []
    try:
        from bika.lims import api
        from maitux.glossary.utils import get_container as _glossary_container
    except Exception as exc:
        return [], [u"keyword_glossary 不可用（%s）：报告导入将不落位任何数据"
                    % exc]

    if portal is None:
        try:
            portal = api.get_portal()
        except Exception as exc:
            return [], [u"取 portal 失败：%s" % exc]

    container = None
    try:
        container = _glossary_container()
    except Exception as exc:
        warnings.append(u"定位 keyword_glossary 失败：%s" % exc)
    if container is None:
        return [], warnings + [
            u"站点上没有 keyword_glossary（Maitux Keyword Glossary 未安装？）："
            u"报告导入将不落位任何数据"]

    rows = []
    try:
        for obj in container.objectValues():
            if not getattr(obj, "acq_enabled", False):
                continue
            rows.append({
                "analysis_keyword": getattr(obj, "analysis_keyword", u""),
                "calc_keyword": getattr(obj, "calc_keyword", u""),
                "zh": getattr(obj, "zh", u""),
                "acq_source_sample": getattr(obj, "acq_source_sample", u""),
                "acq_pick": getattr(obj, "acq_pick", u""),
                "acq_decimals": getattr(obj, "acq_decimals", u""),
                "acq_length": getattr(obj, "acq_length", 0),
                "acq_injection": getattr(obj, "acq_injection", 0),
                "acq_peaks": getattr(obj, "acq_peaks", 0),
                "acq_rt": getattr(obj, "acq_rt", 0),
                "acq_peak_indexes": getattr(obj, "acq_peak_indexes", u""),
                "acq_row_key": getattr(obj, "acq_row_key", u""),
                "acq_slot": getattr(obj, "acq_slot", u""),
                "acq_drop_rt": getattr(obj, "acq_drop_rt", u""),
            })
    except Exception as exc:
        return [], warnings + [u"遍历 keyword_glossary 失败：%s" % exc]

    if not rows:
        return [], warnings + [
            u"keyword_glossary 里没有任何行勾选「报告导入目标位」："
            u"报告导入将不落位任何数据（请在 "
            u"/lims/setup/keyword_glossary 配置）"]

    targets = []
    for row in rows:
        target, problem = build_target(row)
        if target is None:
            warnings.append(u"配置无效，已跳过 %s.%s：%s"
                            % (row.get("analysis_keyword"),
                               row.get("calc_keyword"), problem))
            continue
        if problem:
            warnings.append(problem)
        targets.append(target)

    return targets, warnings
