# -*- coding: utf-8 -*-
"""Empower PDF 文本抽取（纯 Python，py2 / py3 双兼容）

★ 为什么不直接依赖 `pdftotext`：

1. 本部署的镜像里**没有** poppler（`run_deps.txt` 未装 `poppler-utils`）；
2. 更重要的是**产物形态**：Empower 报告的 Peaks 表是"逐格文本 + 坐标"画出来的，
   下游解析要按**列 x 边界**把数字归到 `RT / Area / %Area / ...` 列上，
   所以这里抽出来的必须是**带坐标的单元格**，而不是一段版式文本。
   `pdftotext -layout` 只能给版式文本，做列归属不可靠。

因此本模块的主路径是纯 Python：解压内容流 + 解析文档内 ToUnicode CMap +
还原 `Tm/Td/TJ` 坐标；`pdftotext` 只作为**文本兜底**（人工核对 / 未来文本型解析）。

产物结构（`extract_pdf` 的返回值）::

    {
      u"method": u"python" | u"pdftotext",
      u"note":   u"",                 # 兜底/降级原因，供日志
      u"pages":  [ {u"index": 0,
                    u"items": [ {u"x": 86.5, u"y": 784.8, u"text": u"Sample Name:"} ],
                    u"text":  u"..."} ],
      u"text":   u"..."               # 各页 text 以 \\f 连接
    }

★ 本模块**只依赖标准库**，且不得 import bika/senaite —— 单测会按文件路径直接加载它。
"""

import os
import re
import subprocess
import tempfile
import zlib

try:  # Python 2
    text_type = unicode
    _chr = unichr
except NameError:  # Python 3
    text_type = str
    _chr = chr

#: 页码脚注（页切分 + 页序锚点）：`Page: 1 of 12`
PAGE_MARK_RE = re.compile(r"^Page:\s*(\d+)\s*of\s*(\d+)$")

_OBJ_RE = re.compile(br"(\d+)\s+(\d+)\s+obj(.*?)endobj", re.S)
_STREAM_RE = re.compile(br"stream\r?\n")
_BEGIN_CMAP_RE = re.compile(br"beginbfchar(.*?)endbfchar", re.S)
_BEGIN_CMAP_RANGE_RE = re.compile(br"beginbfrange(.*?)endbfrange", re.S)
_BFCHAR_RE = re.compile(br"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_BFRANGE_RE = re.compile(
    br"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")

_TOKEN_RE = re.compile(
    br"(?P<str>\((?:\\.|[^\\()])*\))"
    br"|(?P<hex><[0-9A-Fa-f\s]*>)"
    br"|(?P<arropen>\[)"
    br"|(?P<arrclose>\])"
    br"|(?P<num>[-+]?\d*\.?\d+)"
    br"|(?P<op>[A-Za-z'\"*]+)"
)

#: 同一视觉行的 y 容差（PDF 用户单位）
ROW_TOLERANCE = 1.5
#: 版式文本的估算字符宽（PDF 用户单位）；仅用于人看的 `text` 字段
ESTIMATED_CHAR_WIDTH = 4.0


# ---------------------------------------------------------------------------
# 基础工具（py2 / py3 兼容）
# ---------------------------------------------------------------------------

def _decode_text(raw):
    """bytes -> unicode（尽力而为，绝不抛异常）"""
    if isinstance(raw, text_type):
        return raw
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, AttributeError):
            continue
    return raw.decode("latin-1", "replace")


def _unhexlify(text):
    """十六进制串 -> bytes（py2 用 decode('hex')，py3 用 binascii）"""
    try:
        import binascii
        return binascii.unhexlify(text)
    except Exception:
        try:
            return text.decode("hex")  # py2
        except Exception:
            return b""


def _inflate(raw):
    """zlib 解压；失败返回 None（不抛异常）"""
    for candidate in (raw, raw.rstrip(b"\r\n"), raw.lstrip(b"\r\n")):
        try:
            return zlib.decompress(candidate)
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# PDF 结构：对象 / 流 / CMap
# ---------------------------------------------------------------------------

def parse_objects(data):
    """解析出 {对象号: 对象体 bytes}（不追对象流 ObjStm，够用且简单）"""
    objects = {}
    for match in _OBJ_RE.finditer(data):
        objects[int(match.group(1))] = match.group(3)
    return objects


def stream_of(body):
    """对象体 -> 解压后的流（没有流或解压失败返回 None）"""
    marker = _STREAM_RE.search(body)
    if not marker:
        return None
    return _inflate(body[marker.end():])


def collect_streams(objects):
    """{对象号: 解压后的流}"""
    streams = {}
    for num, body in objects.items():
        decoded = stream_of(body)
        if decoded is not None:
            streams[num] = decoded
    return streams


def _refs(fragment):
    """把 `12 0 R 13 0 R` 片段解析成 [12, 13]"""
    return [int(num) for num in re.findall(br"(\d+)\s+\d+\s+R", fragment)]


def content_refs(body):
    """页对象的 /Contents 引用号列表（单个或数组）"""
    array = re.search(br"/Contents\s*\[([^\]]*)\]", body, re.S)
    if array:
        return _refs(array.group(1))
    single = re.search(br"/Contents\s+(\d+)\s+\d+\s+R", body)
    if single:
        return [int(single.group(1))]
    return []


def kids_refs(body):
    """页树节点的 /Kids 引用号列表"""
    array = re.search(br"/Kids\s*\[([^\]]*)\]", body, re.S)
    if not array:
        return []
    return _refs(array.group(1))


#: `/Type /Page`（叶子页）与 `/Type /Pages`（页树节点）
_PAGE_LEAF_RE = re.compile(br"/Type\s*/Page[^s]")
_PAGES_NODE_RE = re.compile(br"/Type\s*/Pages")


def page_order(objects):
    """按**页树**解析页对象顺序（PDF 阅读顺序）

    ★ 为什么一定要走页树：内容流在文件里是**对象号顺序**，而且一页的
    `/Contents` 可能是**多个流**（实测 `table.pdf` 首页挂了 12 个流、
    `1 SYS.pdf` 的 STD-1 第 1 针被拆成两个流）。用"按页脚切流"会把
    一次进样劈成两页，峰表与样品信息错配（实测踩过）。
    """
    leaves = []
    nodes = {}
    for num, body in objects.items():
        if _PAGES_NODE_RE.search(body):
            nodes[num] = kids_refs(body)
            continue
        if _PAGE_LEAF_RE.search(body):
            leaves.append(num)
    if not leaves:
        return []

    child_of = {}
    for parent, kids in nodes.items():
        for kid in kids:
            child_of[kid] = parent
    roots = [num for num in nodes if num not in child_of]
    roots.sort()

    ordered = []
    visited = set()

    def walk(num):
        if num in visited:
            return
        visited.add(num)
        kids = nodes.get(num)
        if kids is None:
            if num in leaves:
                ordered.append(num)
            return
        for kid in kids:
            walk(kid)

    for root in roots:
        walk(root)
    for num in sorted(leaves):
        if num not in visited:
            ordered.append(num)
    return ordered


def assemble_pages(objects, streams, cmap):
    """按页树把内容流组装成页（每页：多个流的单元格按流顺序拼接）"""
    pages = []
    for num in page_order(objects):
        items = []
        for ref in content_refs(objects.get(num, b"")):
            content = streams.get(ref)
            if content:
                items.extend(extract_items(content, cmap))
        if items:
            pages.append(items)
    return pages


def _page_number(items):
    """从页脚 `Page: N of M` 取页码；没有就返回 None"""
    for item in items:
        match = PAGE_MARK_RE.match((item.get("text") or u"").strip())
        if match:
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                return None
    return None


def split_pages(items):
    """按页码脚注切页（**仅在没有页树时的兜底**），并按页码排序"""
    pages = []
    current = []
    for item in items:
        current.append(item)
        if PAGE_MARK_RE.match((item.get("text") or u"").strip()):
            pages.append(current)
            current = []
    if current:
        pages.append(current)

    decorated = []
    for index, page in enumerate(pages):
        number = _page_number(page)
        key = number if number is not None else 10 ** 6 + index
        decorated.append((key, index, page))
    decorated.sort(key=lambda entry: (entry[0], entry[1]))
    return [entry[2] for entry in decorated]


def _parse_cmap(text):
    """解析 ToUnicode CMap 的 bfchar / bfrange，返回 {code(int): unicode}"""
    cmap = {}
    for block in _BEGIN_CMAP_RE.findall(text):
        for src, dst in _BFCHAR_RE.findall(block):
            try:
                cmap[int(src, 16)] = _decode_text(
                    _unhexlify(dst)).encode("latin-1").decode("utf-16-be",
                                                             "replace")
            except Exception:
                continue
    for block in _BEGIN_CMAP_RANGE_RE.findall(text):
        for low, high, dst in _BFRANGE_RE.findall(block):
            try:
                first = int(low, 16)
                last = min(int(high, 16), first + 2000)
                base = int(dst, 16)
            except Exception:
                continue
            for offset in range(last - first + 1):
                cmap[first + offset] = _chr(base + offset)
    return cmap


def collect_cmap(streams):
    """把文档内所有 CMap 合并成一张表（一套汇报用 1~2 个字体，够用）

    :param streams: {对象号: 流} 或 [(对象号, 流)] 均可
    """
    cmap = {}
    values = streams.values() if hasattr(streams, "values") else \
        [item[1] for item in streams]
    for decoded in values:
        if b"begincmap" in decoded:
            cmap.update(_parse_cmap(decoded))
    return cmap


def content_streams(streams):
    """挑出内容流（含 BT 且有 Tj/TJ 的流），按对象号稳定排序

    仅在**没有页树**时作兜底用（见 `split_pages`）。
    """
    result = []
    items = streams.items() if hasattr(streams, "items") else streams
    for objnum, decoded in items:
        if b"BT" in decoded and (b"Tj" in decoded or b"TJ" in decoded):
            result.append((objnum, decoded))
    result.sort(key=lambda entry: entry[0])
    return result


# ---------------------------------------------------------------------------
# 内容流 -> 带坐标的单元格
# ---------------------------------------------------------------------------

def decode_hex_string(raw, cmap):
    """PDF 十六进制字符串 -> unicode

    Empower 报告用 Identity 编码的 2 字节 code，先查 CMap；查不到就按
    UTF-16BE 兜底解一次（部分文档不做子集化）。
    """
    digits = re.sub(br"[^0-9A-Fa-f]", b"", raw)
    if not digits:
        return u""
    if cmap:
        if len(digits) % 4 == 0:
            parts = []
            for index in range(0, len(digits), 4):
                code = int(digits[index:index + 4], 16)
                # 查不到的 code 一律丢弃：宁可少字，也不要塞进乱码
                parts.append(cmap.get(code, u""))
            return u"".join(parts)
    try:
        return _unhexlify(digits).decode("utf-16-be", "replace")
    except Exception:
        return u""


def unescape_literal(raw):
    """PDF 字面串（`(...)` 内部）的转义还原 -> unicode"""
    out = []
    index = 0
    length = len(raw)
    while index < length:
        char = raw[index:index + 1]
        if char != b"\\":
            out.append(_decode_text(char))
            index += 1
            continue
        nxt = raw[index + 1:index + 2]
        simple = {b"n": u"\n", b"r": u"\r", b"t": u"\t",
                  b"b": u"\b", b"f": u"\f"}
        if nxt in simple:
            out.append(simple[nxt])
            index += 2
            continue
        if nxt in (b"(", b")", b"\\"):
            out.append(_decode_text(nxt))
            index += 2
            continue
        octal = re.match(br"[0-7]{1,3}", raw[index + 1:index + 4])
        if octal:
            out.append(_chr(int(octal.group(0), 8)))
            index += 1 + len(octal.group(0))
            continue
        out.append(_decode_text(nxt))
        index += 2
    return u"".join(out)


def extract_items(content, cmap):
    """内容流 -> 单元格列表（按流内出现顺序）

    只跟踪 `Tm / Td / TD / T* / Tf` 与文本显示算子：这些报告是"一格一算子"，
    单元格起点坐标由行矩阵给出，不需要字体宽度表就能定位。

    ★ 操作数必须按**裸数字**收集（`Tm`/`Td` 的 6/2 个参数不在括号里），
    PDF 里只有字符串/数组才带括号 —— 早期版本只收集括号内数组，
    结果所有单元格坐标都是 0，版式文本退化成"按字母排一列"。
    """
    items = []
    line_x = line_y = 0.0
    size = 10.0
    leading = 12.0
    operands = []
    array_items = None
    pending = []

    def emit():
        if pending:
            items.append({"x": round(line_x, 2), "y": round(line_y, 2),
                          "size": round(size, 2), "text": u"".join(pending)})
            del pending[:]

    for match in _TOKEN_RE.finditer(content):
        groups = match.groupdict()
        if groups["str"] is not None:
            text = unescape_literal(match.group(0)[1:-1])
            if array_items is not None:
                array_items.append(text)
            else:
                operands.append(("s", text))
            continue
        if groups["hex"] is not None:
            text = decode_hex_string(match.group(0)[1:-1], cmap)
            if array_items is not None:
                array_items.append(text)
            else:
                operands.append(("s", text))
            continue
        if groups["arropen"] is not None:
            array_items = []
            continue
        if groups["arrclose"] is not None:
            operands.append(("a", array_items or []))
            array_items = None
            continue
        if groups["num"] is not None:
            try:
                value = float(groups["num"])
            except ValueError:
                continue
            if array_items is not None:
                array_items.append(value)
            else:
                operands.append(value)
            continue

        operator = groups["op"]
        numbers = [value for value in operands if isinstance(value, float)]
        if operator == "Tm" and len(numbers) >= 6:
            emit()
            line_x, line_y = numbers[-2], numbers[-1]
        elif operator in ("Td", "TD") and len(numbers) >= 2:
            emit()
            line_x += numbers[-2]
            line_y += numbers[-1]
            if operator == "TD":
                leading = -numbers[-1]
        elif operator == "T*":
            emit()
            line_y -= leading
        elif operator == "TL" and numbers:
            leading = numbers[-1]
        elif operator == "Tf" and numbers:
            size = numbers[-1]
        elif operator in ("Tj", "'", '"'):
            emit()
            for kind, value in operands:
                if kind == "s":
                    pending.append(value)
            emit()
        elif operator == "TJ":
            emit()
            for kind, value in operands:
                if kind == "a":
                    for element in value:
                        if not isinstance(element, float):
                            pending.append(element)
            emit()
        operands = []

    emit()
    return items


# ---------------------------------------------------------------------------
# 版式文本
# ---------------------------------------------------------------------------

def items_to_layout(items, char_width=ESTIMATED_CHAR_WIDTH):
    """把单元格拼成**给人看**的版式文本（列按 x 对齐，仅供调试/人工核对）"""
    rows = []
    for item in sorted(items, key=lambda it: (-it["y"], it["x"])):
        text = (item.get("text") or u"").strip()
        if not text:
            continue
        if rows and abs(rows[-1][0] - item["y"]) <= ROW_TOLERANCE:
            rows[-1][1].append((item["x"], text))
        else:
            rows.append((item["y"], [(item["x"], text)]))

    lines = []
    for _y, cells in rows:
        cells.sort(key=lambda cell: cell[0])
        line = u""
        cursor = None
        for x, text in cells:
            if cursor is not None:
                gap = x - cursor
                line += u" " * max(1, int(gap / char_width))
            line += text
            cursor = x + len(text) * char_width
        lines.append(line.rstrip())
    return u"\n".join(lines)


# ---------------------------------------------------------------------------
# pdftotext 文本兜底（可选）
# ---------------------------------------------------------------------------

def find_executable(name):
    """定位可执行文件（py2 用 distutils，py3 用 shutil.which）"""
    try:
        from distutils.spawn import find_executable as _find  # noqa: WPS433
        path = _find(name)
        if path:
            return path
    except Exception:
        pass
    try:
        import shutil
        return shutil.which(name)
    except Exception:
        return None


def pdftotext_text(data, filename=u"uploaded.pdf"):
    """用 `pdftotext -layout` 抽文本；不可用/失败时返回 (None, 原因)"""
    executable = find_executable("pdftotext")
    if not executable:
        return None, u"pdftotext not found in PATH"
    handle = tempfile.NamedTemporaryFile(
        prefix="maitux_pdf_", suffix=".pdf", delete=False)
    try:
        handle.write(data)
        handle.close()
        process = subprocess.Popen(
            [executable, "-layout", handle.name, "-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = process.communicate()
        if process.returncode != 0:
            return None, _decode_text(err or b"") or u"pdftotext failed"
        text = _decode_text(out or b"")
        if not text.strip():
            return None, u"pdftotext returned empty output"
        return text, u""
    except Exception as exc:  # 兜底：绝不因 pdftotext 让导入失败
        return None, u"%s" % exc
    finally:
        try:
            os.unlink(handle.name)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

def extract_pdf(data, filename=u"uploaded.pdf"):
    """抽取 PDF：优先纯 Python（带坐标），失败才退到 pdftotext（纯文本）

    页序优先走**页树**（`assemble_pages`）；没有页树（少见）才退回
    "按页脚切内容流"。两条路都拿不到内容时，退 `pdftotext`（纯文本、
    无坐标，下游解析会明确报"没有坐标单元格"）。

    :param data: PDF 原始字节
    :param filename: 仅用于日志/错误信息
    :returns: 见模块 docstring 的产物结构
    """
    objects = parse_objects(data)
    streams = collect_streams(objects)
    cmap = collect_cmap(streams)

    note = u""
    pages = assemble_pages(objects, streams, cmap)
    if not pages:
        items = []
        for _objnum, content in content_streams(streams):
            items.extend(extract_items(content, cmap))
        pages = split_pages(items)
        if pages:
            note = u"no page tree: fell back to footer-based page splitting"

    if pages:
        page_items = []
        for index, page in enumerate(pages):
            page_items.append({
                "index": index,
                "items": page,
                "text": items_to_layout(page),
            })
        return {
            "method": "python",
            "note": note,
            "pages": page_items,
            "text": u"\f".join(page["text"] for page in page_items),
        }

    # 纯 Python 抽不出内容（比如扫描件/未知字体）——退到 pdftotext 纯文本
    text, reason = pdftotext_text(data, filename)
    if text is None:
        return {"method": "none", "note": reason, "pages": [], "text": u""}
    return {
        "method": "pdftotext",
        "note": u"pure-python extraction gave no text; fell back (%s)" % reason,
        "pages": [{"index": index, "items": [], "text": page}
                  for index, page in enumerate(text.split(u"\f"))],
        "text": text,
    }
