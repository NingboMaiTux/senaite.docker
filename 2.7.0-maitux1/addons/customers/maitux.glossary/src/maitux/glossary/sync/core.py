# -*- coding: utf-8 -*-
#
# 同步计划 —— 纯逻辑，不 import 任何 Zope / senaite 模块（离线可测）
#
# 需求（见 项目文档/keyword对照表/结构定稿.md §4）：
#   R1  新 key -> 追加
#   R2  已存在的 key，除 sync_state 外的字段完全不动
#   R3  消失 -> 只改 sync_state；重新出现 -> 对称恢复活跃
#   R4（已取消）新行的 zh 不再从站点/兄弟行回填 —— zh、en **默认为空**，
#      由人工填写；同一 calc keyword 的一致性由"按 calc keyword 批量改"
#      （datamanagers/glossaryentry.py）保证。
#
# 输入输出都是普通 dict / list，方便离线断言。

from maitux.glossary.config import STATE_ACTIVE
from maitux.glossary.config import STATE_INACTIVE
from maitux.glossary.keys import text


class SyncPlan(object):
    """一轮同步要做的全部改动。

    :param to_create:     [(key, seed_dict), ...]  key = (analysis_kw, calc_kw)
    :param to_activate:   [key, ...]  站点上又有 -> 恢复活跃
    :param to_deactivate: [key, ...]  站点上没了 -> 未激活
    :param unchanged:     int         站点上仍在、且本来就是活跃
    :param zh_mismatch:   [(key, table_zh, site_title), ...]  仅提示
    :param dirty_states:  [(key, state), ...] 表里存了非法状态值
    """

    def __init__(self, to_create=None, to_activate=None, to_deactivate=None,
                 unchanged=0, zh_mismatch=None, dirty_states=None):
        self.to_create = to_create or []
        self.to_activate = to_activate or []
        self.to_deactivate = to_deactivate or []
        self.unchanged = unchanged
        self.zh_mismatch = zh_mismatch or []
        self.dirty_states = dirty_states or []

    @property
    def created(self):
        return len(self.to_create)

    @property
    def activated(self):
        return len(self.to_activate)

    @property
    def deactivated(self):
        return len(self.to_deactivate)

    def summary(self):
        """给日志/界面用的一行摘要（可观测信号，规则 R9）。"""
        return u"+%d new, %d deactivated, %d reactivated, %d unchanged" % (
            self.created, self.deactivated, self.activated, self.unchanged)

    def sample_new(self, limit=10):
        return [u"%s / %s" % (k[0], k[1]) for k, _seed in self.to_create[:limit]]

    def sample_deactivated(self, limit=10):
        return [u"%s / %s" % (k[0], k[1]) for k in self.to_deactivate[:limit]]

    def sample_activated(self, limit=10):
        return [u"%s / %s" % (k[0], k[1]) for k in self.to_activate[:limit]]


class SyncOutcome(object):
    """一轮同步的结果（给调用方/列表页看）。

    ``site_keys`` 是这一轮站点快照，列表页用它渲染"分析类别 / 检测项目 /
    站点 Field title"等**只读参考列**并参与搜索 —— 因此不需要把这些值
    存进表里（存了就等于每轮都在改已存在的行，违反 R2）。
    """

    def __init__(self, plan=None, site_keys=None, duplicate_keywords=None,
                 orphan_calculations=None, title_conflicts=None,
                 table_duplicates=None, user=u"", elapsed=0.0, ok=True,
                 error=u""):
        self.plan = plan
        self.site_keys = site_keys or {}
        self.duplicate_keywords = duplicate_keywords or {}
        self.orphan_calculations = orphan_calculations or []
        self.title_conflicts = title_conflicts or []
        self.table_duplicates = table_duplicates or []
        self.user = user
        self.elapsed = elapsed
        self.ok = ok
        self.error = error


def make_seed(key, site_info):
    """新行的初始字段值。

    ``zh`` / ``en`` **留空** —— 按需求，中文名不再从站点的 Field title 回填，
    由人工填写；这样表里"有值"的一定是人填的，不会与站点现状混淆。
    """
    analysis_keyword, calc_keyword = key
    return {
        "analysis_keyword": text(analysis_keyword),
        "calc_keyword": text(calc_keyword),
        "category": text((site_info or {}).get("category")),
        "zh": u"",
        "en": u"",
        "sync_state": STATE_ACTIVE,
    }


def build_plan(site_keys, table_rows):
    """比对站点快照与中间表，得出这一轮要做什么。

    :param site_keys:  ``{(analysis_kw, calc_kw): {"category":...,
                         "service_title":..., "site_title":...}}``
    :param table_rows: ``{(analysis_kw, calc_kw): {"sync_state":...,
                         "zh":..., "en":...}}``
    :returns: :class:`SyncPlan`
    """
    site_keys = site_keys or {}
    table_rows = table_rows or {}

    to_create = []
    to_activate = []
    to_deactivate = []
    zh_mismatch = []
    dirty_states = []
    unchanged = 0

    # 站点有、表里没有 -> 追加
    for key in sorted(site_keys.keys()):
        if key in table_rows:
            continue
        to_create.append((key, make_seed(key, site_keys[key])))

    for key in sorted(table_rows.keys()):
        row = table_rows[key]
        state = text(row.get("sync_state"))

        if state not in (STATE_ACTIVE, STATE_INACTIVE):
            dirty_states.append((key, state))

        if key in site_keys:
            if state == STATE_ACTIVE:
                unchanged += 1
            else:
                # "重新出现"与"状态值非法"都归一到活跃
                to_activate.append(key)

            # 人工填的 zh 与站点 Field title 的差异：**仅提示，不改表**（R2）
            table_zh = text(row.get("zh"))
            site_title = text(site_keys[key].get("site_title"))
            if table_zh and site_title and table_zh != site_title:
                zh_mismatch.append((key, table_zh, site_title))
        else:
            if state == STATE_ACTIVE or state not in (STATE_ACTIVE,
                                                      STATE_INACTIVE):
                to_deactivate.append(key)

    return SyncPlan(
        to_create=to_create,
        to_activate=to_activate,
        to_deactivate=to_deactivate,
        unchanged=unchanged,
        zh_mismatch=zh_mismatch,
        dirty_states=dirty_states,
    )
