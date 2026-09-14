# -*- coding: utf-8 -*-
#
# 查表 API（**只读**，给报告 / 接口 / 其他 addon 用）
#
# 三条规则（见 项目文档/keyword对照表/结构定稿.md §8）：
#
#   1. 行级：只有 sync_state == active 的行参与输出
#   2. 术语级兜底：按 calc keyword 查时，只要该 keyword 还有**任意一个**
#      活跃行，译名就仍然有效 —— 否则 imp_name 被 3 个检查项目使用、
#      其中 1 个停用时，整个字段的译名会因为不相干的项目停用而查不到
#   3. 英文缺失时回落中文；整体查不到返回 None，由调用方兜底
#      （一般做法是原样输出 keyword）

from maitux.glossary.config import STATE_ACTIVE
from maitux.glossary.keys import text
from maitux.glossary.utils import get_container
from maitux.glossary.utils import iter_entries

#: 一次请求内复用同一份索引（报告里逐条查名字时避免重复遍历容器）
_REQUEST_ATTR = "maitux_glossary_index"


def build_index(container=None):
    """把中间表读成查询索引。

    :returns: dict

        ``pairs``          ``{(analysis_kw, calc_kw): {zh, en}}``
                           只含活跃行
        ``fields``         ``{calc_kw: {zh, en, conflicts}}``
                           由活跃行推导；``conflicts`` 非空表示同一 calc keyword
                           出现了多个不同译文（应被校验拦下，这里如实报告）
        ``inactive_pairs`` 未激活行数
        ``total_pairs``    全部行数
    """
    container = container or get_container()
    pairs = {}
    fields = {}
    inactive = 0
    total = 0

    for obj in iter_entries(container):
        total += 1
        analysis_keyword = text(getattr(obj, "analysis_keyword", None))
        calc_keyword = text(getattr(obj, "calc_keyword", None))
        if not analysis_keyword or not calc_keyword:
            continue

        state = text(getattr(obj, "sync_state", None))
        if state != STATE_ACTIVE:
            inactive += 1
            continue

        row = {
            "zh": text(getattr(obj, "zh", None)),
            "en": text(getattr(obj, "en", None)),
        }
        pairs[(analysis_keyword, calc_keyword)] = row

        entry = fields.get(calc_keyword)
        if entry is None:
            entry = {"zh": row["zh"], "en": row["en"], "conflicts": []}
            fields[calc_keyword] = entry

        for name in ("zh", "en"):
            current = entry.get(name) or u""
            value = row.get(name) or u""
            if not value or value == current:
                continue
            if not current:
                entry[name] = value
            else:
                desc = u"%s=%s|%s" % (name, current, value)
                if desc not in entry["conflicts"]:
                    entry["conflicts"].append(desc)

    return {
        "pairs": pairs,
        "fields": fields,
        "inactive_pairs": inactive,
        "total_pairs": total,
    }


def get_request():
    try:
        from zope.globalrequest import getRequest
        return getRequest()
    except Exception:
        return None


def get_index():
    """取索引，带请求级缓存。"""
    request = get_request()
    if request is not None:
        cached = getattr(request, _REQUEST_ATTR, None)
        if cached is not None:
            return cached
    index = build_index()
    if request is not None:
        try:
            setattr(request, _REQUEST_ATTR, index)
        except Exception:
            pass
    return index


def _pick(entry, lang):
    """按语言取值，英文缺失时回落中文。"""
    if not entry:
        return None
    order = ("en", "zh") if text(lang) != u"zh" else ("zh", "en")
    for name in order:
        value = text(entry.get(name))
        if value:
            return value
    return None


def get_field_name(calc_keyword, lang=u"en"):
    """按 calc keyword 取字段译名 —— **本表的事实主键**。

    :returns: unicode 名字，或 None（表里没有该 calc keyword 的活跃行）
    """
    index = get_index()
    return _pick(index["fields"].get(text(calc_keyword)), lang)


def get_name(analysis_keyword, calc_keyword, lang=u"en"):
    """按 (analysis_keyword, calc_keyword) 取译名，带兜底链。

    兜底链::

        1. 精确匹配 (analysis_keyword, calc_keyword) 的活跃行
        2. 该 calc keyword 的任意活跃行（术语由 calc keyword 全局唯一决定）
        3. None —— 调用方自行兜底（一般原样输出 keyword）
    """
    index = get_index()
    analysis_keyword = text(analysis_keyword)
    calc_keyword = text(calc_keyword)

    if analysis_keyword and calc_keyword:
        value = _pick(index["pairs"].get((analysis_keyword, calc_keyword)),
                      lang)
        if value:
            return value

    if calc_keyword:
        return _pick(index["fields"].get(calc_keyword), lang)

    return None


def find_by_zh(zh):
    """反查：中文名 -> [(analysis_keyword, calc_keyword), ...]（活跃行）。"""
    return _find_by(u"zh", zh)


def find_by_en(en):
    """反查：英文名 -> [(analysis_keyword, calc_keyword), ...]（活跃行）。"""
    return _find_by(u"en", en)


def _find_by(name, value):
    value = text(value)
    if not value:
        return []
    index = get_index()
    found = []
    for key in sorted(index["pairs"].keys()):
        if text(index["pairs"][key].get(name)) == value:
            found.append(key)
    return found


def validate():
    """校验表内纪律。**不修改任何数据**。

    :returns: ``{"errors": [...], "warnings": [...]}``
    """
    container = get_container()
    errors = []
    warnings = []

    keys = set()
    service_categories = {}
    field_zh = {}
    field_en = {}

    for obj in iter_entries(container):
        analysis_keyword = text(getattr(obj, "analysis_keyword", None))
        calc_keyword = text(getattr(obj, "calc_keyword", None))
        where = u"%s / %s" % (analysis_keyword, calc_keyword)

        if not analysis_keyword:
            errors.append(u"%s: analysis_keyword 为空" % where)
        if not calc_keyword:
            errors.append(u"%s: calc_keyword 为空" % where)
        if not analysis_keyword or not calc_keyword:
            continue

        key = (analysis_keyword, calc_keyword)
        if key in keys:
            errors.append(u"%s: 键重复" % where)
        keys.add(key)

        category = text(getattr(obj, "category", None))
        if category:
            previous = service_categories.get(analysis_keyword)
            if previous and previous != category:
                errors.append(
                    u"%s: 同一检查项目出现两个类别（%s / %s）"
                    % (where, previous, category))
            else:
                service_categories[analysis_keyword] = category

        zh = text(getattr(obj, "zh", None))
        en = text(getattr(obj, "en", None))
        for name, value, store in ((u"zh", zh, field_zh),
                                   (u"en", en, field_en)):
            if not value:
                continue
            previous = store.get(calc_keyword)
            if previous and previous != value:
                errors.append(
                    u"%s: 同一 calc keyword 的 %s 不一致（%s / %s）"
                    % (where, name, previous, value))
            else:
                store[calc_keyword] = value

        # zh / en 空是**正常默认状态**（新行即空，等人工填），所以只算
        # warning、不算 error —— 这里就是"还有多少没翻译"的清单。
        if not zh:
            warnings.append(u"%s: zh 为空" % where)
        if not en:
            warnings.append(u"%s: en 为空" % where)

    # calc keyword 不得与任何 analysis_keyword 撞名
    # （依据 senaite.core.validators.interimfields.no_dup_service_keyword_validator）
    analysis_keywords = set([k[0] for k in keys])
    for calc_keyword in set([k[1] for k in keys]):
        if calc_keyword in analysis_keywords:
            errors.append(
                u"calc keyword '%s' 与某个 Analysis Keyword 同名 —— core "
                u"禁止 interim keyword 与 AnalysisService keyword 重名"
                % calc_keyword)

    return {"errors": errors, "warnings": warnings}


def stats():
    """覆盖率统计。"""
    index = get_index()
    fields = index["fields"]
    services = set([key[0] for key in index["pairs"].keys()])

    return {
        u"rows_total": index["total_pairs"],
        u"rows_active": len(index["pairs"]),
        u"rows_inactive": index["inactive_pairs"],
        u"services": len(services),
        u"calc_keywords": len(fields),
        u"with_zh": len([1 for f in fields.values() if f.get("zh")]),
        u"with_en": len([1 for f in fields.values() if f.get("en")]),
    }
