# -*- coding: utf-8 -*-

from zope.schema.vocabulary import SimpleTerm
from zope.schema.vocabulary import SimpleVocabulary

from maitux.glossary import _
from maitux.glossary.config import STATE_ACTIVE
from maitux.glossary.config import STATE_INACTIVE


def SyncStatesVocabulary(context=None):
    """活跃 / 未激活 —— 由同步维护，人工不选。
    """
    terms = [
        SimpleTerm(STATE_ACTIVE, STATE_ACTIVE, _(u"Active")),
        SimpleTerm(STATE_INACTIVE, STATE_INACTIVE, _(u"Inactive")),
    ]
    return SimpleVocabulary(terms)


# ---------------------------------------------------------------------------
# 报告导入映射（采集侧消费，见 addons/customers/maitux.instrument_acquisition）
#
# ★ 这里刻意用**受控词表**而不是自由文本：这两个值的错误后果是"写错数据"
#   或"静默不落位"，而自由文本必然会被手打错（实测本项目已有先例）。
# ---------------------------------------------------------------------------

def AcquisitionPickVocabulary(context=None):
    """取值规则：该针怎么取值（与 report_targets.PICK_RULES 一一对应）"""
    terms = [
        SimpleTerm(u"main_peak.area", u"main_peak.area",
                   _(u"main_peak.area — 每针主峰（面积最大）的面积")),
        SimpleTerm(u"peaks.area", u"peaks.area",
                   _(u"peaks.area — 该针全部峰的面积，按峰序")),
        SimpleTerm(u"peaks.rt", u"peaks.rt",
                   _(u"peaks.rt — 该针全部峰的 RT，按峰序")),
        SimpleTerm(u"peaks.resolution", u"peaks.resolution",
                   _(u"peaks.resolution — 该针全部峰的分离度（首峰 N/A）")),
        SimpleTerm(u"peaks.sn", u"peaks.sn",
                   _(u"peaks.sn — 该针全部峰的 USP s/n，按峰序")),
        SimpleTerm(u"peaks.area_sum", u"peaks.area_sum",
                   _(u"peaks.area_sum — 该针全部峰的面积之和（单值）")),
        SimpleTerm(u"peaks.name", u"peaks.name",
                   _(u"peaks.name — 该针全部峰的峰名，按峰序（空白峰写「未知杂质」）")),
    ]
    return SimpleVocabulary(terms)


def AcquisitionDecimalsVocabulary(context=None):
    """写法：按站点现值保留几位小数（空 = 原样，不做格式化）"""
    terms = [
        SimpleTerm(u"", u"raw", _(u"空 = 原样（保留报告里的写法）")),
        SimpleTerm(u"0", u"d0", _(u"0 = 整数")),
        SimpleTerm(u"1", u"d1", _(u"1 = 1 位小数")),
        SimpleTerm(u"2", u"d2", _(u"2 = 2 位小数")),
        SimpleTerm(u"3", u"d3", _(u"3 = 3 位小数")),
    ]
    return SimpleVocabulary(terms)
