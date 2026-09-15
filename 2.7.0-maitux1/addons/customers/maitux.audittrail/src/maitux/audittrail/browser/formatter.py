# -*- coding: utf-8 -*-
"""审计追踪里的结构化数据（Interim Fields / 工作表布局 / JSON）展示格式化工具"""

import json

try:
    from html import escape
except ImportError:
    from cgi import escape


try:
    string_types = (basestring,)
except NameError:
    string_types = (str,)


RESULT_TYPE_TITLES = {
    "calculated": u"计算值",
    "numeric": u"数值",
    "string": u"字符串",
    "text": u"文本",
    "datetime": u"日期时间",
    "select": u"下拉选择",
    "multiselect": u"多选",
    "multiselect_duplicates": u"多选(可重复)",
    "multichoice": u"多项选择",
    "multivalue": u"多值",
}


try:
    text_type = unicode
except NameError:
    text_type = str


def safe_text(value):
    """把任意值转换为安全字符串，避免把 None 直接展示到页面"""
    if value is None:
        return u""
    if isinstance(value, text_type):
        return value
    try:
        return text_type(value)
    except Exception:
        return text_type(str(value))


def safe_html(value):
    """统一做 HTML 转义，避免公式中的特殊字符破坏页面结构"""
    return escape(safe_text(value), quote=True)


def is_truthy(value):
    """兼容 bool、字符串和数字等不同来源的真值判断"""
    if isinstance(value, bool):
        return value
    text = safe_text(value).strip().lower()
    return text in ("1", "true", "yes", "on")


def get_flag_text(item):
    """把多个布尔位压缩成一列，减少审计界面的横向宽度"""
    flags = []
    if is_truthy(item.get("allow_empty")):
        flags.append(u"允许空")
    if is_truthy(item.get("report")):
        flags.append(u"报告")
    if is_truthy(item.get("hidden")):
        flags.append(u"隐藏")
    if is_truthy(item.get("wide")) or is_truthy(item.get("apply_wide")):
        flags.append(u"全局应用")
    return u"，".join(flags) if flags else u"无"


def get_result_type_title(value):
    """把内部 result_type 转成更容易阅读的中文文案"""
    text = safe_text(value).strip()
    if not text:
        return u""
    return RESULT_TYPE_TITLES.get(text, text)


def item_to_dict(item):
    """把单行 Interim Field 转成字典

    快照中同一字段可能以两种结构存储：
    - 字典结构：{"keyword": "NM", ...}
    - 键值对列表结构：[["keyword", "NM"], ["unit", "g"], ...]
    """
    if isinstance(item, dict):
        return dict(item)
    if isinstance(item, (list, tuple)):
        # 兼容 [[key, value], ...] 键值对列表
        return {pair[0]: pair[1]
                for pair in item
                if isinstance(pair, (list, tuple)) and len(pair) >= 2}
    return {}


def format_default_value(value):
    """默认值可能是一段 JSON，直接显示会把中文露成 \\uXXXX 转义

    多选类型（list / multiselect / multichoice）的 interim 默认值在快照里是
    `json.dumps()` 的产物，而 `json.dumps` 默认 `ensure_ascii=True`，
    所以 "未知杂质" 存进去就成了 "\\u672a\\u77e5\\u6742\\u8d28"。
    数据本身没问题，是这里没解回来。

    只在看起来像 JSON 容器时才尝试解析；解析失败就原样返回，
    绝不能因为格式化把原始值弄丢 —— 这是审计记录。
    """
    if isinstance(value, (list, tuple)):
        return u"、".join([safe_text(item) for item in value])

    text = safe_text(value).strip()
    if not text or text[0] not in (u"[", u"{"):
        return text

    try:
        decoded = json.loads(text)
    except (ValueError, TypeError):
        return text

    if isinstance(decoded, (list, tuple)):
        return u"、".join([safe_text(item) for item in decoded])
    return safe_text(decoded)


def clean_no_value(value):
    """把快照中的 <NO_VALUE> 占位符转成空串，避免界面出现噪音"""
    text = safe_text(value).strip()
    if text.upper() in ("<NO_VALUE>", "NO_VALUE"):
        return u""
    return text


def normalize_rows(value):
    """只提取审计页面真正关心的字段，屏蔽原始 JSON 噪音"""
    rows = []
    if not isinstance(value, (list, tuple)):
        return rows

    for item in value:
        row = item_to_dict(item)
        if not row:
            continue
        rows.append({
            "keyword": safe_text(row.get("keyword")),
            "title": safe_text(row.get("title")),
            "result_type": get_result_type_title(row.get("result_type")),
            "value": format_default_value(row.get("value")),
            "formula": clean_no_value(row.get("formula")),
            "unit": safe_text(row.get("unit")),
            "choices": safe_text(row.get("choices")),
            "flags": get_flag_text(row),
        })
    return rows


def render_interim_fields_html(value):
    """把 Interim Fields 渲染成可读表格，替代原始 JSON 串"""
    rows = normalize_rows(value)
    if not rows:
        return u'<span class="audit-interim-empty">未设置</span>'

    header = u"""
<table class="table table-condensed table-bordered audit-interim-table">
  <thead>
    <tr>
      <th>关键字</th>
      <th>字段标题</th>
      <th>结果类型</th>
      <th>默认值</th>
      <th>公式</th>
      <th>单位</th>
      <th>选项</th>
      <th>标志</th>
    </tr>
  </thead>
  <tbody>
""".strip()

    body = []
    for row in rows:
        body.append(u"""
    <tr>
      <td>{keyword}</td>
      <td>{title}</td>
      <td>{result_type}</td>
      <td>{value}</td>
      <td>{formula}</td>
      <td>{unit}</td>
      <td>{choices}</td>
      <td>{flags}</td>
    </tr>
""".format(
            keyword=safe_html(row["keyword"]),
            title=safe_html(row["title"]),
            result_type=safe_html(row["result_type"]),
            value=safe_html(row["value"]),
            formula=safe_html(row["formula"]),
            unit=safe_html(row["unit"]),
            choices=safe_html(row["choices"]),
            flags=safe_html(row["flags"]),
        ).strip())

    footer = u"""
  </tbody>
</table>
""".strip()

    return u"\n".join([header] + body + [footer])


# --------------------------------------------------------------------------
# Worksheet 布局（layout_view）在审计追踪页面的呈现
#
# 工作表快照里的 Layout 是一个 DataGridField，值是 JSON 意义上的
# "list of dict"：
#
#     [{"position": 1, "type": "a",
#       "container_uid": "…", "analysis_uid": "…"}, …]
#
# 原生 compare_snapshots 走 _process_value 的字典分支，把它打印成
# json.dumps 的原始串；两个 UID 都是 32 位裸串，读者看不出"哪个分析项、
# 在哪个样品、第几格"变了 —— 记是记全了，可读性为零。这里摊成表格，
# 并把 UID 换成可读标题。
#
# UID 的解析由调用方注入 `uid_resolver`：本模块刻意不 import bika.lims.api，
# 保持脱离 Plone 就能跑单元测试（与 Interim Fields 一节同样的取舍）。
# --------------------------------------------------------------------------

#: 快照里出现过的工作表布局字段名（大小写不敏感）
WORKSHEET_LAYOUT_FIELDS = ("layout_view", "layout")

#: 布局行的判据键。position / type 太通用（Interim Fields、模板布局也有同名的
#: 键），两个 *_uid 才是布局独有的特征。
LAYOUT_ROW_KEYS = ("container_uid", "analysis_uid")

#: 布局行的 type 取值（见 senaite.core: Worksheet.get_analysis_type）
ANALYSIS_TYPE_TITLES = {
    "a": u"常规分析",
    "b": u"空白",
    "c": u"质控",
    "d": u"平行样",
}


def get_analysis_type_title(value):
    """把布局行的 type 单字母转成可读文案"""
    text = safe_text(value).strip().lower()
    if not text:
        return u""
    return ANALYSIS_TYPE_TITLES.get(text, text)


def resolve_uid(value, uid_resolver=None):
    """把 UID 换成可读标题；换不动就原样显示 UID

    审计页面宁可显示裸 UID，也不能因为解析失败把值吞掉。
    """
    text = clean_no_value(value)
    if not text or uid_resolver is None:
        return text
    try:
        title = uid_resolver(text)
    except Exception:
        # 解析器已经自己兜过底了，这里只是不让任何意外冒到渲染层
        return text
    title = clean_no_value(title)
    return title or text


def looks_like_layout_rows(value):
    """判断值是不是工作表布局行（list of dict）"""
    if not isinstance(value, (list, tuple)) or not value:
        return False

    keys = set()
    for item in value:
        row = item_to_dict(item)
        if not row:
            return False
        keys.update(row.keys())
    return any(key in keys for key in LAYOUT_ROW_KEYS)


def is_worksheet_layout(field, value):
    """工作表布局：行结构命中，或字段名命中且值为空

    字段名命中时不直接认，仍要看行结构 —— 同名字段存了别的列表就不能抢过来。
    唯一的例外是空列表：此时按布局渲染，界面显示"未设置"而不是 "[]"。
    """
    if isinstance(value, (list, tuple)) and not value:
        return safe_text(field).strip().lower() in WORKSHEET_LAYOUT_FIELDS
    return looks_like_layout_rows(value)


def normalize_layout_rows(value, uid_resolver=None):
    """把布局行整理成审计表格需要的列"""
    rows = []
    if not isinstance(value, (list, tuple)):
        return rows

    for num, item in enumerate(value):
        row = item_to_dict(item)
        if not row:
            continue
        rows.append({
            "index": safe_text(num + 1),
            "position": clean_no_value(row.get("position")),
            "type": get_analysis_type_title(row.get("type")),
            "container": resolve_uid(row.get("container_uid"), uid_resolver),
            "analysis": resolve_uid(row.get("analysis_uid"), uid_resolver),
        })
    return rows


def render_worksheet_layout_html(value, uid_resolver=None):
    """把工作表布局渲染成可读表格，替代原始 JSON 串"""
    rows = normalize_layout_rows(value, uid_resolver=uid_resolver)
    if not rows:
        return u'<span class="audit-layout-empty">未设置</span>'

    header = u"""
<table class="table table-condensed table-bordered audit-layout-table">
  <thead>
    <tr>
      <th>#</th>
      <th>位置</th>
      <th>类型</th>
      <th>样品</th>
      <th>分析项</th>
    </tr>
  </thead>
  <tbody>
""".strip()

    body = []
    for row in rows:
        body.append(u"""
    <tr>
      <td>{index}</td>
      <td>{position}</td>
      <td>{type}</td>
      <td>{container}</td>
      <td>{analysis}</td>
    </tr>
""".format(
            index=safe_html(row["index"]),
            position=safe_html(row["position"]),
            type=safe_html(row["type"]),
            container=safe_html(row["container"]),
            analysis=safe_html(row["analysis"]),
        ).strip())

    footer = u"""
  </tbody>
</table>
""".strip()

    return u"\n".join([header] + body + [footer])


# --------------------------------------------------------------------------
# 通用 JSON 数据可视化
#
# 快照里凡是 dict / list[dict] / JSON 串形态的值，原生 _process_value 都会
# 打印成 json.dumps 的原始串（dict 分支）或按 "; " 拼接（list 分支）。
# 对审计读者来说那是一堵读不动的墙。这里统一摊开：
#
#   - dict        → 键 / 值 两列
#   - list[dict]  → 以键的并集为列头的记录表
#   - list[标量]  → 项目符号列表
#
# 嵌套结构递归渲染，超过 JSON_MAX_DEPTH 层退回转义后的 JSON 文本 ——
# 任何数据都必须渲染得出来，格式化的底线是"不丢内容"。
# --------------------------------------------------------------------------

#: 递归渲染的最大层数，再深就退回原始 JSON 文本
JSON_MAX_DEPTH = 3

#: 看起来像 JSON 容器的首字符
JSON_CONTAINER_CHARS = (u"[", u"{")


def is_string(value):
    """跨 Python 2 / 3 的字符串判断"""
    return isinstance(value, string_types)


def maybe_decode_json(value, depth=0):
    """看起来像 JSON 容器就解回来，解不动原样返回

    只在首字符是 [ 或 { 时才尝试；解析失败一律原样返回 ——
    审计记录不允许因为"格式化"把原始值弄丢。
    """
    if not is_string(value) or depth > JSON_MAX_DEPTH:
        return value

    text = value.strip()
    if not text or text[0] not in JSON_CONTAINER_CHARS:
        return value

    try:
        decoded = json.loads(text)
    except (ValueError, TypeError):
        return value

    if isinstance(decoded, (dict, list, tuple)):
        return decoded
    return value


def is_json_data(value):
    """判断一个快照值是否值得结构化展示

    纯标量不进来：审计页面里绝大多数字段都是标量，走 code 分支更好读。
    纯字符串列表（如 analyses 的 UID 列表）也不进来：_process_value 已经
    把它拼成可读的一行了。

    例外是**字面就是 JSON 的字符串** —— 它已经解出来了，就一定要摊开。
    多选类型 interim 的默认值正是这种形态，原样打印会连中文都露成 \\uXXXX。
    """
    if is_string(value):
        decoded = maybe_decode_json(value)
        return isinstance(decoded, (dict, list, tuple)) and bool(decoded)
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, (list, tuple)):
        return any(isinstance(item, (dict, list, tuple)) for item in value)
    return False


def render_json_raw_html(value):
    """兜底：转义后的 JSON 文本，绝不丢内容"""
    try:
        text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
    except (ValueError, TypeError):
        # ensure_ascii=False 下非 ASCII 字节串解不开会走到这里，也照接
        text = safe_text(value)
    return u'<pre class="audit-json-raw">{}</pre>'.format(safe_html(text))


def render_json_mapping_html(mapping, depth=0):
    """dict → 键 / 值 两列"""
    if not isinstance(mapping, dict) or not mapping:
        return u'<span class="audit-json-empty">未设置</span>'

    if depth >= JSON_MAX_DEPTH:
        return render_json_raw_html(mapping)

    rows = []
    # key=safe_text 保证键类型混杂（unicode 与 str）时也不会比较崩
    for key in sorted(mapping.keys(), key=safe_text):
        rows.append(u"""
    <tr>
      <th class="audit-json-key">{key}</th>
      <td>{value}</td>
    </tr>
""".format(
            key=safe_html(key),
            value=render_json_html(mapping[key], depth + 1),
        ).strip())

    return u"""
<table class="table table-condensed table-bordered audit-json-table">
  <tbody>
{}
  </tbody>
</table>
""".format(u"\n".join(rows)).strip()


def render_json_records_html(records, depth=0):
    """list[dict] → 以键的并集为列头的记录表"""
    columns = []
    for record in records:
        for key in record.keys():
            if key not in columns:
                columns.append(key)
    columns = sorted(columns, key=safe_text)

    head = u"".join(
        u"<th>{}</th>".format(safe_html(column)) for column in columns)

    body = []
    for num, record in enumerate(records):
        cells = u"".join(
            u"<td>{}</td>".format(
                render_json_html(record.get(column, u""), depth + 1))
            for column in columns)
        body.append(
            u'<tr><td class="audit-json-index">{}</td>{}</tr>'.format(
                safe_html(num + 1), cells))

    return u"""
<table class="table table-condensed table-bordered audit-json-table">
  <thead>
    <tr>
      <th>#</th>
      {head}
    </tr>
  </thead>
  <tbody>
    {body}
  </tbody>
</table>
""".format(head=head, body=u"\n    ".join(body)).strip()


def render_json_array_html(sequence, depth=0):
    """list → 记录表（全是字典时）或项目符号列表"""
    if not isinstance(sequence, (list, tuple)) or not sequence:
        return u'<span class="audit-json-empty">未设置</span>'

    if depth >= JSON_MAX_DEPTH:
        return render_json_raw_html(list(sequence))

    records = [item_to_dict(item) for item in sequence]
    if all(records):
        return render_json_records_html(records, depth)

    items = [
        u'<li class="audit-json-item">{}</li>'.format(
            render_json_html(item, depth + 1))
        for item in sequence
    ]
    return u'<ul class="audit-json-list">{}</ul>'.format(u"".join(items))


def render_json_html(value, depth=0):
    """JSON 数据可视化的统一入口：dict / list / JSON 串都从这里进"""
    value = maybe_decode_json(value, depth)

    if isinstance(value, dict):
        return render_json_mapping_html(value, depth)
    if isinstance(value, (list, tuple)):
        return render_json_array_html(value, depth)
    return safe_html(value)


# --------------------------------------------------------------------------
# 电子签名（maitux.esignature）在审计追踪页面的呈现
#
# 21 CFR Part 11 §11.50(b) 要求签名 manifestation 是"电子记录任何人类可读形式"
# 的组成部分。签名数据一直写在快照的 __metadata__ 里，但原生 SENAITE 的审计
# 列表没有任何一列去渲染它 —— 记了却从不显示，本身即不满足条款。
#
# 这里只读 metadata 的字典键，不 import maitux.esignature：
# 没装 esignature 的站点取不到键，该列恒为空，不构成反向依赖。
# --------------------------------------------------------------------------

SIGNATURE_SUMMARY_PREFIX = u"Electronic signature"


def parse_signature_summary(text):
    """解析 esignature 写进 comments 的 "k=v; k=v" 摘要

    这个回落分支是必需的，不是锦上添花：结构化的 metadata["esignature"] 受
    签名策略的 auditlog_summary_enabled 门控，该开关关掉时字典根本不会写，
    只剩 DCWorkflow 带过来的这条摘要字符串。
    """
    summary = safe_text(text).strip()
    if not summary.startswith(SIGNATURE_SUMMARY_PREFIX):
        return None

    data = {}
    for piece in summary.split(u";"):
        key, sep, value = piece.strip().partition(u"=")
        if not sep:
            continue
        data[key.strip()] = value.strip()
    if not data:
        return None

    return {
        "signer": data.get(u"first_signer", u""),
        "countersigner": data.get(u"second_signer", u""),
        "meaning": data.get(u"meaning", u""),
        "reason": data.get(u"reason", u""),
        "require_countersign": data.get(u"countersign_required") == u"yes",
        "auth_backend": data.get(u"auth_backend", u""),
    }


def signature_from_metadata(esignature):
    """从结构化的 metadata["esignature"] 取签名信息"""
    if not isinstance(esignature, dict):
        return None
    if not esignature.get("enabled", True):
        return None

    return {
        "signer": safe_text(
            esignature.get("primary_signer_user_id")
            or esignature.get("initiator_user_id")
            or esignature.get("user_id")
        ),
        "countersigner": safe_text(esignature.get("countersigner_user_id")),
        "meaning": safe_text(esignature.get("meaning")),
        "reason": safe_text(esignature.get("reason")),
        "require_countersign": bool(esignature.get("require_countersign")),
        "auth_backend": safe_text(esignature.get("auth_backend_id")),
    }


def extract_signature(metadata):
    """优先取结构化字典，回落到 comments 摘要；都没有则返回 None"""
    if not isinstance(metadata, dict):
        return None
    data = signature_from_metadata(metadata.get("esignature"))
    if data:
        return data
    return parse_signature_summary(metadata.get("comments"))


def render_signature_html(data, timestamp=None):
    """把签名渲染成人类可读的几行；无签名的行返回空串"""
    if not data:
        return u""

    lines = []

    def add(label, value):
        value = safe_text(value).strip()
        if value:
            lines.append((label, value))

    # §11.50(a) 要求的三要素：签名人姓名、签署日期时间、签名含义。
    # 时间与同一行的"修改时间"列同源，这里重复一次是刻意的 ——
    # manifestation 应当自身完整，不依赖读者去横向对齐别的列。
    add(u"签名人", data.get("signer"))
    add(u"签名时间", timestamp)
    add(u"含义", data.get("meaning"))
    add(u"原因", data.get("reason"))
    if data.get("require_countersign"):
        add(u"复核人", data.get("countersigner") or u"（待复核）")
    add(u"验证方式", data.get("auth_backend"))

    if not lines:
        return u""

    rows = [
        u'<div class="audit-signature-line">'
        u'<span class="audit-signature-label">{}：</span>'
        u'<span class="audit-signature-value">{}</span>'
        u'</div>'.format(safe_html(label), safe_html(value))
        for label, value in lines
    ]
    return u'<div class="audit-signature">{}</div>'.format(u"".join(rows))
