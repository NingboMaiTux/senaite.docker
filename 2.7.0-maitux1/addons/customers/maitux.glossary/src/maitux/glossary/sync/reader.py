# -*- coding: utf-8 -*-
#
# 站点快照：现在有哪些 (analysis_keyword, calc_keyword) 组合
#
# 遍历范围**只含 is_active 的 AnalysisService / Calculation**（结构定稿 §6）。
# 连带效应：停用一个 AS，会让它名下所有组合在下一轮同步里变成"未激活"；
# 重新启用后会由 R3 的对称重算自动恢复为活跃。

from bika.lims import api
from senaite.core.catalog import SETUP_CATALOG

from maitux.glossary.keys import text


def read_site_snapshot():
    """遍历站点，返回本轮对账所需的全部信息。

    :returns: dict

        ``keys``
            ``{(analysis_keyword, calc_keyword): {"category": u"",
             "service_title": u"", "site_title": u""}}``
            （``service_title`` = 检测项目/分析服务的标题，只用于列表页参考列与搜索；
             ``site_title`` = 该字段在站点上的 Field title，同为参考值）
        ``duplicate_keywords``
            ``{analysis_keyword: [title, ...]}`` —— 只含**重复**的 AS keyword。
            有重复时行键会一对多，必须先修数据。
        ``orphan_calculations``
            ``[title, ...]`` —— 没有任何 active AS 使用的 Calculation。
            它们的 interim 凑不出 analysis_keyword，因此不进表。
        ``title_conflicts``
            ``[u"...", ...]`` —— 同一个 calc keyword 在 AS 侧与 Calculation 侧
            的 title 不一致（理论上 core 会拦，实际是脏数据信号）。
    """
    keys = {}
    duplicate_keywords = {}
    title_conflicts = []
    used_calc_uids = set()

    services = api.search(
        {"portal_type": "AnalysisService", "is_active": True},
        SETUP_CATALOG)

    for brain in services:
        service = api.get_object(brain)
        analysis_keyword = text(service.getKeyword())
        if not analysis_keyword:
            continue

        title = text(api.get_title(service))
        duplicate_keywords.setdefault(analysis_keyword, []).append(title)

        category = u""
        try:
            category = text(api.get_title(service.getCategory()))
        except Exception:
            category = u""

        # 以 Calculation 侧为准（Calculation 编辑页的 Interim Fields 才是
        # 字段的定义处），AS 侧只作补充 —— 两者的并集。
        service_titles = {}
        for interim in service.getInterimFields() or []:
            keyword = text(interim.get("keyword"))
            if keyword:
                service_titles[keyword] = text(interim.get("title"))

        for calc in _related_calculations(service):
            used_calc_uids.add(api.get_uid(calc))
            for interim in calc.getInterimFields() or []:
                keyword = text(interim.get("keyword"))
                if not keyword:
                    continue
                calc_title = text(interim.get("title"))
                as_title = service_titles.get(keyword, u"")
                if calc_title and as_title and calc_title != as_title:
                    title_conflicts.append(
                        u"%s.%s: calculation=%s, service=%s"
                        % (analysis_keyword, keyword, calc_title, as_title))
                keys[(analysis_keyword, keyword)] = {
                    "category": category,
                    "service_title": title,
                    "site_title": calc_title,
                }

        for keyword, title_value in service_titles.items():
            key = (analysis_keyword, keyword)
            if key not in keys:
                keys[key] = {
                    "category": category,
                    "service_title": title,
                    "site_title": title_value,
                }

    duplicate_keywords = dict(
        (kw, titles) for kw, titles in duplicate_keywords.items()
        if len(titles) > 1)

    orphan_calculations = _find_orphan_calculations(used_calc_uids)

    return {
        "keys": keys,
        "duplicate_keywords": duplicate_keywords,
        "orphan_calculations": orphan_calculations,
        "title_conflicts": title_conflicts,
    }


def _as_calc(value):
    """把 UID 或对象统一成 Calculation 对象。"""
    if value is None:
        return None
    if isinstance(value, (str, unicode)):
        try:
            return api.get_object_by_uid(value)
        except Exception:
            return None
    return value


def _related_calculations(service):
    """该 AS 关联的所有 Calculation（Method <-> Calculation 是 1:N，取并集）。"""
    calcs = []
    seen = set()

    def add(value):
        calc = _as_calc(value)
        if calc is None:
            return
        try:
            uid = api.get_uid(calc)
        except Exception:
            uid = None
        if uid and uid in seen:
            return
        if uid:
            seen.add(uid)
        calcs.append(calc)

    try:
        add(service.getCalculation())
    except Exception:
        pass
    try:
        for method in service.getMethods() or []:
            for calc in method.getCalculations() or []:
                add(calc)
    except Exception:
        pass
    return calcs


def _find_orphan_calculations(used_calc_uids):
    """没有任何 active AS 使用的 Calculation 的标题。"""
    orphans = []
    try:
        brains = api.search(
            {"portal_type": "Calculation", "is_active": True}, SETUP_CATALOG)
    except Exception:
        return orphans
    for brain in brains:
        try:
            if api.get_uid(brain) in used_calc_uids:
                continue
            orphans.append(text(api.get_title(brain)))
        except Exception:
            continue
    return orphans
