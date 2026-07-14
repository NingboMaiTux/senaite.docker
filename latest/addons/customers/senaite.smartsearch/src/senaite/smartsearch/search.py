# -*- coding: utf-8 -*-
"""
智慧搜索 —— 核心搜索逻辑。

两层权限保证：
  1. ``portal_catalog`` 本身就是 CMF 的 CatalogTool，其 searchResults() 会自动按照
     当前登录用户的 allowedRolesAndUsers 索引过滤结果——这是 Zope/Plone/SENAITE
     的标准行为，客户联系人默认就只能看到自己 Client 下的对象。
  2. 为了不依赖每个目录都正确维护了安全索引（尤其是部分自定义/专用目录，比如
     Analysis 检测结果目录，不一定索引了 allowedRolesAndUsers），这里对每一条
     候选结果又额外做了一次显式的 checkPermission('View', obj) 校验，
     两层叠加，确保"在权限范围内搜索"这件事不依赖单一机制。

代价：第 2 层需要唤醒对象（brain.getObject()），比纯目录查询慢。为了控制
性能，会按 limit 的若干倍数先取候选集，过滤后再截断到 limit 条。
"""

from __future__ import absolute_import
from __future__ import division

import logging

from AccessControl.SecurityManagement import getSecurityManager

try:
    from bika.lims import api
except ImportError:
    from senaite.core.api import api  # noqa

logger = logging.getLogger("senaite.smartsearch")

# 会被 portal_catalog 索引到的常见业务类型；不同版本/自定义可能需要增减
PORTAL_CATALOG_TYPES = [
    "AnalysisRequest",
    "Batch",
    "Client",
    "Contact",
    "Instrument",
    "AnalysisService",
    "SampleType",
    "SamplePoint",
    "Method",
    "Worksheet",
    "Supplier",
    "Product",
    "LabContact",
    "Department",
]

ANALYSIS_CATALOG_CANDIDATES = [
    "senaite_catalog_analysis",
    "analysis_catalog",
    "bika_analysis_catalog",
]

TYPE_LABELS = {
    "AnalysisRequest": u"样品",
    "Batch": u"批次",
    "Client": u"客户",
    "Contact": u"联系人",
    "Instrument": u"仪器",
    "AnalysisService": u"检测项目",
    "SampleType": u"样品类型",
    "SamplePoint": u"采样点",
    "Method": u"方法",
    "Worksheet": u"工作单",
    "Supplier": u"供应商",
    "Product": u"产品",
    "LabContact": u"实验室联系人",
    "Department": u"部门",
    "Analysis": u"检测结果",
}

# 每次候选集相对最终 limit 的放大倍数，给权限过滤留出余量
OVERFETCH_MULTIPLIER = 3
MAX_CANDIDATES = 400


def _may_view(obj):
    """显式权限校验：当前登录用户是否真的有 View 权限。"""
    try:
        sm = getSecurityManager()
        return bool(sm.checkPermission("View", obj))
    except Exception as e:
        logger.warning("smartsearch 权限校验失败，保守起见跳过该结果: %s", e)
        return False


def _safe_search(catalog, **query):
    try:
        return catalog(**query)
    except Exception as e:
        logger.warning("smartsearch 查询目录出错: %s", e)
        return []


def global_search(query_text, limit=60):
    """跨多个目录、多种业务对象类型做统一搜索，只返回当前用户有权查看的结果。"""
    query_text = (query_text or "").strip()
    if len(query_text) < 2:
        return []

    candidate_limit = min(MAX_CANDIDATES, limit * OVERFETCH_MULTIPLIER)

    results = []
    seen_urls = set()

    portal_catalog = api.get_tool("portal_catalog")
    brains = _safe_search(
        portal_catalog,
        SearchableText=query_text + "*",
        portal_type=PORTAL_CATALOG_TYPES,
    )
    for b in brains[:candidate_limit]:
        if len(results) >= limit:
            break
        url = b.getURL()
        if url in seen_urls:
            continue
        try:
            obj = b.getObject()
        except Exception:
            continue
        if not _may_view(obj):
            continue
        seen_urls.add(url)
        results.append({
            "title": b.Title or b.getId,
            "id": b.getId,
            "type": b.portal_type,
            "type_label": TYPE_LABELS.get(b.portal_type, b.portal_type),
            "url": url,
            "state": getattr(b, "review_state", None),
        })

    # 检测结果（Analysis）通常是样品下的子对象，不会被 portal_catalog 索引到，
    # 需要单独查一次专用目录
    if len(results) < limit:
        for cat_name in ANALYSIS_CATALOG_CANDIDATES:
            try:
                acat = api.get_tool(cat_name)
            except Exception:
                continue
            abrains = _safe_search(acat, SearchableText=query_text + "*")
            for b in abrains[:candidate_limit]:
                if len(results) >= limit:
                    break
                try:
                    url = b.getURL()
                except Exception:
                    continue
                if url in seen_urls:
                    continue
                try:
                    obj = b.getObject()
                except Exception:
                    continue
                if not _may_view(obj):
                    continue
                seen_urls.add(url)
                results.append({
                    "title": getattr(b, "Title", query_text),
                    "id": getattr(b, "getId", ""),
                    "type": "Analysis",
                    "type_label": TYPE_LABELS["Analysis"],
                    "url": url,
                    "state": getattr(b, "review_state", None),
                })
            break  # 找到一个可用的 analysis 目录就够了

    return results[:limit]
