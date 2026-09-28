# -*- coding: utf-8 -*-
"""Waters Empower 报告解析（纯函数，py2 / py3 双兼容）

输入：`pdf_text.extract_pdf()` 的产物（**带坐标的单元格**）。
输出（与方案 §4.1 的契约一致，并按《S1919 仪器进样数据采集与命名规范 v1.1》扩字段）::

    {
      u"report": {
          u"project": u"S1919\\Method Verfication I",
          u"report_method": u"The Report of S1908 IP",
          u"report_method_id": u"2067",
          u"sample_set_name": u"20260512_VF_IP_LC013_01",
          u"worksheet_id": u"",            # 规范 §3.1：SampleSetName 前缀里的 WorkSheet ID
          u"page_count": 13,
      },
      u"injections": [
          {u"sample_name": u"STD-1", u"sample_type": u"Unknown", u"vial": u"1:A,4",
           u"injection_no": u"2", u"acquired": u"...", u"processed": u"...",
           u"role": u"STD-1", u"segments": [], u"level": u"", u"idx": u"",
           u"page_indexes": [5], u"peaks": [
              {u"peak_no": 1, u"rt": 34.53, u"area": 64814, u"pct_area": 100.0,
               u"height": 4790, u"sn": 398, u"resolution": None, u"tailing": 1.0,
               u"purity_angle": None, u"purity_threshold": None, u"name": u""}]}
      ],
      u"warnings": [u"..."],
    }

★ 关键几何事实（实测 `1 SYS.pdf` / `4 LOD.pdf` 得出，改动解析前务必先读）：

1. **样品信息块**：左标签右值，两列并排（左列 label x≈41 / value x≈131；
   右列 label x≈290 / value x≈386）；标签与值可能差 0.5pt 的 y 抖动。
   取值规则 = 同一行内、位于标签**右侧最近**的那个单元格。
2. **Peaks 表**：表头在表格顶部，**列宽逐页不同**（Empower 按内容自适应），
   所以列锚点必须取**当页表头自己的 x**，不能跨页复用。
3. 表头分组标签（`Purity` + `Angle` / `Threshold`）分两行，x 对齐，需按 x 合并。
4. 数据单元格是**右对齐**的，与表头锚点有 ≤16pt 偏差 → 用"最近锚点"归属。
5. 峰表**会跨页**（峰 1-7 在第 4 页、峰 8-16 在第 5 页），续页**不重复**样品信息块
   → 解析必须把"无样品信息块的页"接到上一节。

★ 本模块**只依赖标准库**，不得 import bika/senaite（单测按文件路径直接加载）。
"""

import re

try:  # Python 2
    text_type = unicode
except NameError:  # Python 3
    text_type = str

#: 样品信息块的标签（左列 + 右列）
SAMPLE_LABELS = (
    u"Sample Name:", u"Sample Type:", u"Vial:", u"Sample Set Name:",
    u"Injection #:", u"Processing Method:", u"Injection Volume:",
    u"Channel Name:", u"Run Time:", u"Proc. Chnl. Descr.:",
    u"Acq. Method Set:", u"Date Acquired:", u"Date Processed:",
    u"Acquired By:",
)

#: 峰表列标签（含表头里的分组标签片段）
COLUMN_LABELS = (
    u"Peak Name", u"RT(min)", u"Area", u"% Area", u"Height", u"USP s/n",
    u"Resolution", u"Tailing", u"Purity", u"Angle", u"Threshold",
)

#: 受控角色词表（规范 §4.2）；按长度倒序匹配，避免 `STD-1` 被 `STD` 抢走
ROLE_VOCABULARY = (
    u"REC-SPEC", u"REC-NS", u"STD-1-QC", u"STAB-RT", u"STAB-4C",
    u"STD-1", u"STD-2", u"BLANK", u"LIN", u"LOD", u"LOQ", u"SYS", u"ID",
    u"DEG",
)

#: 样品信息块同行的 y 容差
LABEL_ROW_TOLERANCE = 2.0
#: 峰表数据行的 y 容差（峰号与数值行实测差 0.24pt，跨行间距 ≥18pt）
PEAK_ROW_TOLERANCE = 2.0
#: 单元格归属列的最大 x 偏差（超出即视为表外内容）
COLUMN_MAX_DISTANCE = 40.0
#: 批号式 SampleName（供试品/重复性）：以 ICPNB 开头
BATCH_NAME_RE = re.compile(u"^[A-Z]{2,}[0-9]")

#: 页脚/页眉标签：这些行**不是**峰表数据行
FOOTER_PREFIXES = (
    u"Project Name:", u"Reported by User:", u"Report Method:", u"Date Printed:",
    u"Page:", u"Report Method ID:",
)
#: 页脚里的 `Page: N of M`
FOOTER_PAGE_RE = re.compile(u"^Page:\\s*\\d+\\s*of\\s*\\d+$")

#: 列 key 与产物字段的映射
COLUMN_FIELD_MAP = {
    u"RT(min)": u"rt",
    u"Area": u"area",
    u"% Area": u"pct_area",
    u"Height": u"height",
    u"USP s/n": u"sn",
    u"Resolution": u"resolution",
    u"Tailing": u"tailing",
    u"Purity Angle": u"purity_angle",
    u"Purity Threshold": u"purity_threshold",
    u"Peak Name": u"name",
}

#: 规范 §3.1 的 Sample Set Name 首段（WorkSheet ID），如 `WS-003`
WORKSHEET_ID_RE = re.compile(u"^[A-Za-z]{1,6}[-_]?\\d{1,6}$")
#: 日期式首段（旧序列名 `20260512_VF_IP_LC013_01`）——用于识别"没有 WorkSheet ID"
DATE_SEGMENT_RE = re.compile(u"^\\d{8}$")


# ---------------------------------------------------------------------------
# 基础工具
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


def _to_float(value):
    """把单元格文本转 float；`---` / 空 / 非数字返回 None"""
    text = _text(value).replace(u",", u"")
    if not text or text in (u"---", u"-", u"—", u"n/a", u"N/A"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value):
    number = _to_float(value)
    if number is None:
        return None
    try:
        return int(round(number))
    except (ValueError, OverflowError):
        return None


def _row_key(y, tolerance):
    """把 y 归到"行"：按容差聚簇后返回簇的代表值（用于分行）"""
    return round(y / tolerance)


def group_rows(items, tolerance):
    """把单元格按 y 分行；返回 [[item, ...], ...]（行内按 x 升序，行间自上而下）"""
    rows = []
    for item in sorted(items, key=lambda it: (-it["y"], it["x"])):
        if rows and abs(rows[-1][0] - item["y"]) <= tolerance:
            rows[-1][1].append(item)
        else:
            rows.append([item["y"], [item]])
    result = []
    for _y, cells in rows:
        result.append(sorted(cells, key=lambda cell: cell["x"]))
    return result


# ---------------------------------------------------------------------------
# 样品信息块
# ---------------------------------------------------------------------------

def parse_sample_info(items):
    """解析样品信息块 -> {label: value}

    取值规则：同一行内、标签**右侧最近**的单元格（见模块 docstring 的几何事实 1）。
    """
    info = {}
    rows = group_rows(items, LABEL_ROW_TOLERANCE)
    for row in rows:
        for index, cell in enumerate(row):
            label = _text(cell["text"])
            if label not in SAMPLE_LABELS:
                continue
            value = u""
            for candidate in row[index + 1:]:
                text = _text(candidate["text"])
                if not text or text in SAMPLE_LABELS:
                    continue
                value = text
                break
            if value:
                info[label.rstrip(u":")] = value
    return info


# ---------------------------------------------------------------------------
# 峰表
# ---------------------------------------------------------------------------

def _header_row_index(rows):
    """找出峰表表头所在的行号：包含最多列标签的那一行"""
    best_index = None
    best_hits = 0
    for index, row in enumerate(rows):
        hits = 0
        for cell in row:
            if _text(cell["text"]) in COLUMN_LABELS:
                hits += 1
        if hits > best_hits:
            best_hits = hits
            best_index = index
    if best_hits < 3:
        return None
    return best_index


def build_columns(rows, header_index):
    """由表头行（含上下相邻行的分组标签）构建列锚点

    :returns: [(column_key, anchor_x), ...]，按 x 升序
    """
    anchors = []
    header_y = rows[header_index][0]["y"] if rows[header_index] else 0
    neighbors = []
    if header_index > 0:
        neighbors.append(rows[header_index - 1])
    neighbors.append(rows[header_index])
    if header_index + 1 < len(rows):
        neighbors.append(rows[header_index + 1])

    for row in neighbors:
        for cell in row:
            label = _text(cell["text"])
            if label in COLUMN_LABELS:
                anchors.append([label, cell["x"]])
    anchors.sort(key=lambda entry: entry[1])

    # 合并分两行写的括号式表头：`Purity` + `Angle` / `Threshold`
    merged = []
    index = 0
    while index < len(anchors):
        label, x = anchors[index]
        nxt = anchors[index + 1] if index + 1 < len(anchors) else None
        if label == u"Purity" and nxt and abs(nxt[1] - x) <= 6.0:
            merged.append([u"Purity %s" % nxt[0], min(x, nxt[1])])
            index += 2
            continue
        merged.append([label, x])
        index += 1

    # 同一标签可能重复出现（例如右侧还有一组），保留 x 最小的一处
    deduped = {}
    for label, x in merged:
        if label not in deduped or x < deduped[label]:
            deduped[label] = x
    columns = [(label, x) for label, x in deduped.items()]
    columns.sort(key=lambda entry: entry[1])
    return columns, header_y


def assign_column(x, columns):
    """按"最近锚点"把数据单元格 x 归属到列；超出容差返回 None"""
    best = None
    best_distance = None
    for label, anchor in columns:
        distance = abs(anchor - x)
        if best_distance is None or distance < best_distance:
            best = label
            best_distance = distance
    if best is None or best_distance is None or best_distance > COLUMN_MAX_DISTANCE:
        return None
    return best


def _is_footer_row(row):
    """该行是否属于页脚/页眉（不是峰表数据行）"""
    for cell in row:
        text = _text(cell["text"])
        if not text:
            continue
        if FOOTER_PAGE_RE.match(text):
            return True
        for prefix in FOOTER_PREFIXES:
            if text.startswith(prefix):
                return True
    return False


def parse_peaks(items):
    """解析峰表 -> [{peak_no, rt, area, ...}, ...]（无数据行时返回 []）"""
    rows = group_rows(items, PEAK_ROW_TOLERANCE)
    header_index = _header_row_index(rows)
    if header_index is None:
        return [], []

    columns, header_y = build_columns(rows, header_index)
    peaks = []
    warnings = []
    for row in rows:
        if row[0]["y"] >= header_y - 0.5:
            continue
        # ★ 页脚行必须排除：`Report Method ID: 2067` 里的 `2067` 落在 RT 列
        # 锚点附近，不排除就会凭空多出一个 "RT=2067" 的假峰（实测踩过）。
        if _is_footer_row(row):
            continue
        peak = {}
        for cell in row:
            label = assign_column(cell["x"], columns)
            if not label:
                continue
            value = _text(cell["text"])
            if not value:
                continue
            peak[label] = value
        if not peak:
            continue
        if not any(label in peak for label in (u"RT(min)", u"Area")):
            # 只有峰号/峰名、没有数值的行不是数据行（例如栏目标题残余）
            continue
        value_columns = [label for label in peak
                         if label in COLUMN_FIELD_MAP and label != u"Peak Name"]
        if len(value_columns) < 2:
            # 单列命中的行是不完整的（多半是页脚/图注残留），不进结果
            continue
        peak_no = _to_int(peak.get(u"Peak Name", u""))
        item = {u"peak_no": peak_no}
        for label, field in COLUMN_FIELD_MAP.items():
            if label in (u"Peak Name",):
                continue
            item[field] = _to_float(peak.get(label))
        name = peak.get(u"Peak Name", u"")
        item[u"name"] = u"" if _to_float(name) is not None else name
        peaks.append(item)

    return peaks, warnings


# ---------------------------------------------------------------------------
# SampleName 拆分（规范 §4.5）
# ---------------------------------------------------------------------------

def split_sample_name(sample_name):
    """按规范 §4.5 拆分 SampleName -> {role, segments, level, idx, is_batch}

    ★ 规范给的"从右往左"规则对 `STD-1` / `LOQ` / `ID-B` 这类**角色自带数字**
    的名字会拆错（会把 `STD-1` 拆成 role=STD / idx=1）。所以实现改成
    **先按受控词表从左匹配角色**，剩下的段落再当 level / idx：

    - `REC-SPEC-LOQ-1` → role=`REC-SPEC`, segments=[`LOQ`, `1`], level=`LOQ`, idx=`1`
    - `REC-NS-LOQ-A1`  → role=`REC-NS`,  segments=[`LOQ`, `A1`], level=`LOQ`, idx=`A1`
    - `STD-1`          → role=`STD-1`,  segments=[], level=u"", idx=u""
    - `ICPNB0000...-R-1(T0)` → 批号式：is_batch=True, role=u"", segments=全文
    """
    name = _text(sample_name)
    result = {u"role": u"", u"segments": [], u"level": u"", u"idx": u"",
              u"is_batch": False}
    if not name:
        return result

    # 批号式（供试品 / 重复性）：整名当作身份，不做角色拆分
    if BATCH_NAME_RE.match(name) or name.upper().startswith(u"ICPNB"):
        result[u"is_batch"] = True
        result[u"segments"] = [name]
        return result

    tokens = name.split(u"-")
    role = u""
    consumed = 0
    for candidate in sorted(ROLE_VOCABULARY, key=len, reverse=True):
        parts = candidate.split(u"-")
        if [token.upper() for token in tokens[:len(parts)]] == \
                [part.upper() for part in parts]:
            role = candidate
            consumed = len(parts)
            break
    if not role:
        # 词表里没有：整名当角色（不猜），让上层的"未登记角色"告警去点名
        result[u"role"] = name
        result[u"segments"] = []
        return result

    segments = tokens[consumed:]
    result[u"role"] = role
    result[u"segments"] = segments
    if segments:
        result[u"level"] = segments[0]
        result[u"idx"] = segments[-1] if len(segments) > 1 else u""
    return result


# ---------------------------------------------------------------------------
# 报告级解析
# ---------------------------------------------------------------------------

def _normalize_sample_type(value):
    """Sample Type 归一：去掉文本断行产生的空白（`Unknow n` → `Unknown`）"""
    text = _text(value)
    squeezed = re.sub(u"\\s+", u"", text)
    if squeezed.lower() == u"unknown":
        return u"Unknown"
    if squeezed.lower() == u"standard":
        return u"Standard"
    if squeezed.lower() == u"blank":
        return u"Blank"
    if squeezed.lower() == u"control":
        return u"Control"
    if squeezed.lower() == u"sample":
        return u"Sample"
    return text


def _worksheet_id(sample_set_name):
    """从 Sample Set Name 首段取 WorkSheet ID（规范 §3.1）；不符合模板返回 u"" """
    name = _text(sample_set_name)
    if not name:
        return u""
    head = re.split(u"[_\\s]", name)[0]
    if not head or DATE_SEGMENT_RE.match(head):
        return u""
    if WORKSHEET_ID_RE.match(head):
        return head
    return u""


def worksheet_id_from_text(value):
    """公开入口：从**任意文本**首段取 WorkSheet ID

    ★ 为什么需要它：正文的 `Sample Set Name` 与"上传文件名"必须用**同一套**判定规则，
      否则会出现"文件名认了、正文不认"这类口径分裂。规则本体只有 `_worksheet_id` 一处。

    用途：报告正文还没有 WorkSheet ID 时（实验室按规范 §3.1 出报告之前），
    允许把文件命名成 `WS-007_1 SYS.pdf`，由调用方从文件名里取 `WS-007`。
    """
    return _worksheet_id(value)


def _report_meta(pages):
    """报告级信息：Project / Report Method / Sample Set Name（取正文里出现过的）"""
    meta = {u"project": u"", u"report_method": u"", u"report_method_id": u""}
    for page in pages:
        for item in page["items"]:
            text = _text(item["text"])
            if text.startswith(u"Project Name:") and not meta[u"project"]:
                meta[u"project"] = text.split(u":", 1)[1].strip()
            elif text.startswith(u"Report Method:") and not meta[u"report_method"]:
                meta[u"report_method"] = text.split(u":", 1)[1].strip()
            elif text.startswith(u"Report Method ID:") and not meta[u"report_method_id"]:
                meta[u"report_method_id"] = text.split(u":", 1)[1].strip()
    return meta


def parse_pages(pages):
    """把**已排序**的页解析成 {report, injections, warnings}"""
    injections = []
    warnings = []
    sample_info_seen = False

    for page in pages:
        items = page["items"]
        if not items:
            continue
        info = parse_sample_info(items)
        peaks, _peak_warnings = parse_peaks(items)

        if info:
            sample_info_seen = True
            injection = {
                u"sample_name": info.get(u"Sample Name", u""),
                u"sample_type": _normalize_sample_type(info.get(u"Sample Type")),
                u"vial": info.get(u"Vial", u""),
                u"injection_no": info.get(u"Injection #", u""),
                u"acquired": info.get(u"Date Acquired", u""),
                u"processed": info.get(u"Date Processed", u""),
                u"processing_method": info.get(u"Processing Method", u""),
                u"channel": info.get(u"Channel Name", u""),
                u"page_indexes": [page["index"]],
                u"peaks": peaks,
            }
            split = split_sample_name(injection[u"sample_name"])
            injection.update(split)
            injections.append(injection)
            continue

        if peaks:
            if not sample_info_seen:
                warnings.append(
                    u"page %d has a peak table but no sample information block "
                    u"before it" % page["index"])
                continue
            # 续页：接到上一节（Empower 峰表跨页时不重复样品信息块）
            injections[-1][u"peaks"].extend(peaks)
            injections[-1][u"page_indexes"].append(page["index"])
            continue

        if not sample_info_seen and page["text"].strip():
            warnings.append(u"page %d produced no sample info and no peaks"
                            % page["index"])

    # 相邻同身份节合并（同一次进样被拆页时偶发重复样品信息块）
    merged = []
    for injection in injections:
        if merged:
            last = merged[-1]
            same = (last[u"sample_name"] == injection[u"sample_name"] and
                    last[u"vial"] == injection[u"vial"] and
                    last[u"injection_no"] == injection[u"injection_no"])
            if same and injection[u"peaks"]:
                last[u"peaks"].extend(injection[u"peaks"])
                last[u"page_indexes"].extend(injection[u"page_indexes"])
                continue
        merged.append(injection)

    for injection in merged:
        if injection[u"sample_type"] == u"Unknown":
            warnings.append(
                u"%s: Sample Type is Unknown（规范 §5：应停用，视为录入遗漏）"
                % injection[u"sample_name"])

    sample_set_name = u""
    for injection in merged:
        for page in pages:
            if page["index"] in injection[u"page_indexes"]:
                info = parse_sample_info(page["items"])
                if info.get(u"Sample Set Name"):
                    sample_set_name = info[u"Sample Set Name"]
                    break
        if sample_set_name:
            break

    report = _report_meta(pages)
    report[u"sample_set_name"] = sample_set_name
    report[u"worksheet_id"] = _worksheet_id(sample_set_name)
    report[u"page_count"] = len(pages)
    if not report[u"worksheet_id"]:
        warnings.append(
            u"Sample Set Name「%s」首段不是 WorkSheet ID（规范 §3.1）——"
            u"报告归属需人工确认" % sample_set_name)

    return {u"report": report, u"injections": merged, u"warnings": warnings}


def parse_extraction(extraction):
    """对外入口：`pdf_text.extract_pdf()` 的产物 -> 结构化结果"""
    pages = extraction.get("pages") or []
    if extraction.get("method") != "python" or not any(p.get("items") for p in pages):
        return {
            u"report": {u"page_count": len(pages), u"sample_set_name": u"",
                        u"worksheet_id": u"", u"project": u"",
                        u"report_method": u"", u"report_method_id": u""},
            u"injections": [],
            u"warnings": [u"no coordinate items available (method=%s): %s"
                          % (extraction.get("method"), extraction.get("note", u""))],
        }
    return parse_pages(pages)


# ---------------------------------------------------------------------------
# 便利函数：按 SampleName 聚合
# ---------------------------------------------------------------------------

def group_by_sample(injections):
    """按 SampleName 聚合多针（规范 §4.1：针数由 Injection 定义，不进 SampleName）

    :returns: [(sample_name, [injection, ...] 按 injection_no 升序), ...]
    """
    grouped = []
    index = {}
    for injection in injections:
        name = injection.get(u"sample_name") or u""
        if name not in index:
            index[name] = len(grouped)
            grouped.append([name, []])
        grouped[index[name]][1].append(injection)
    for _name, items in grouped:
        items.sort(key=lambda item: (_to_int(item.get(u"injection_no")) or 0))
    return [(name, items) for name, items in grouped]
