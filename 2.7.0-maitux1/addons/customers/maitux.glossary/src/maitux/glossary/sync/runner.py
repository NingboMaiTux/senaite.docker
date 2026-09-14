# -*- coding: utf-8 -*-
#
# 把同步计划落到中间表
#
# 写入以**提权身份**执行（plone.api.env.adopt_roles(["Manager"])）：
# 需求是"任何能打开界面的人都触发同步"，而只读用户没有写权限 ——
# 不提权则同步对只读用户必然失败，"任何人"就落不了地。
# 提权的代价是"谁改的"不能靠权限体系归因，所以每次写入都记
# last_sync_by + 一条带触发者的日志（规则 R9：可观测）。

import time
import traceback
from datetime import datetime

from bika.lims import api
from plone import api as ploneapi

from maitux.glossary import logger
from maitux.glossary.config import ENTRY_TYPE
from maitux.glossary.config import MAX_SAMPLES
from maitux.glossary.config import STATE_ACTIVE
from maitux.glossary.config import STATE_INACTIVE
from maitux.glossary.keys import make_entry_id
from maitux.glossary.keys import safe_unicode
from maitux.glossary.keys import text
from maitux.glossary.sync.core import SyncOutcome
from maitux.glossary.sync.core import build_plan
from maitux.glossary.sync.reader import read_site_snapshot
from maitux.glossary.utils import get_entry
from maitux.glossary.utils import iter_entries

#: 站点快照的短命缓存。
#:
#: 为什么需要：同步发生在**页面请求**里，而表格行是随后由 AJAX
#: (``ajax_folderitems``) 渲染的 —— 那是另一个请求，拿不到页面请求里的
#: 同步结果。列表页要显示"站点 Field title"列（对账用，仅提示），
#: 就得把上一轮快照暂存一下。
#:
#: 按容器物理路径为键 —— 同一个 Zope 进程里跑着多个站点（Care / MaiLIMS /
#: InnoCare），不能只按一个全局变量存。
_SNAPSHOT_CACHE = {}
SNAPSHOT_TTL = 300.0


def remember_snapshot(container, site_keys, now=None):
    try:
        path = "/".join(container.getPhysicalPath())
    except Exception:
        return
    _SNAPSHOT_CACHE[path] = (now or time.time(), site_keys or {})


def get_remembered_snapshot(container):
    """``(site_keys, age_seconds)``；过期或没有则返回 ``({}, None)``。"""
    try:
        path = "/".join(container.getPhysicalPath())
    except Exception:
        return {}, None
    cached = _SNAPSHOT_CACHE.get(path)
    if not cached:
        return {}, None
    timestamp, site_keys = cached
    age = time.time() - timestamp
    if age > SNAPSHOT_TTL:
        return {}, age
    return site_keys, age


def run_sync(container, max_samples=MAX_SAMPLES):
    """与站点对账一次，把结果落到 ``container``。

    **不抛异常**：任何失败都记 ERROR 日志并在 ``outcome.ok`` 上体现，
    页面照常渲染（规则 R9 —— 失败要看得见，但不能把页面打崩）。
    """
    started = time.time()
    user = get_current_user_id()
    outcome = SyncOutcome(user=user)

    try:
        snapshot = read_site_snapshot()
        table_rows, table_duplicates = load_table_rows(container)

        plan = build_plan(snapshot.get("keys"), table_rows)

        outcome.plan = plan
        outcome.site_keys = snapshot.get("keys") or {}
        outcome.duplicate_keywords = snapshot.get("duplicate_keywords") or {}
        outcome.orphan_calculations = snapshot.get("orphan_calculations") or []
        outcome.title_conflicts = snapshot.get("title_conflicts") or []
        outcome.table_duplicates = table_duplicates

        with ploneapi.env.adopt_roles(["Manager"]):
            apply_plan(container, plan, user)

        remember_snapshot(container, outcome.site_keys)

    except Exception as exc:
        outcome.ok = False
        outcome.error = safe_unicode(exc)
        logger.error("maitux.glossary: sync FAILED: %s", exc)
        logger.error(traceback.format_exc())

    outcome.elapsed = time.time() - started
    log_outcome(outcome, max_samples=max_samples)
    return outcome


def get_current_user_id():
    """触发者。取不到就记 "unknown"，不要让同步因此失败。"""
    try:
        user = ploneapi.user.get_current()
        return text(user.getId())
    except Exception:
        return u"unknown"


def load_table_rows(container):
    """把中间表现有行读成 ``{key: row}``。

    :returns: ``(rows, duplicates)`` —— 键重复时 ``duplicates`` 非空。
    正常情况不可能重复（ID 由键哈希得出），出现即说明历史数据被搬过。
    """
    rows = {}
    duplicates = []
    for obj in iter_entries(container):
        key = (text(getattr(obj, "analysis_keyword", None)),
               text(getattr(obj, "calc_keyword", None)))
        if key in rows:
            duplicates.append(u"%s / %s" % key)
        rows[key] = {
            "sync_state": text(getattr(obj, "sync_state", None)),
            "zh": text(getattr(obj, "zh", None)),
            "en": text(getattr(obj, "en", None)),
        }
    return rows, duplicates


def apply_plan(container, plan, user):
    """执行计划。调用方负责提权。"""
    now = datetime.utcnow()

    for key, seed in plan.to_create:
        create_entry(container, key, seed, user, now)

    for key in plan.to_activate:
        set_state(container, key, STATE_ACTIVE, user, now)

    for key in plan.to_deactivate:
        set_state(container, key, STATE_INACTIVE, user, now)


def create_entry(container, key, seed, user, now):
    """追加一行。ID 是确定性的 -> 天然防重（并发下重复插入会因 ID 冲突失败）。"""
    analysis_keyword, calc_keyword = key
    entry_id = make_entry_id(analysis_keyword, calc_keyword)

    obj = ploneapi.content.create(
        container=container,
        type=ENTRY_TYPE,
        id=entry_id,
        safe_id=False,
    )

    values = dict(seed or {})
    values["first_seen"] = now
    values["state_changed_on"] = now
    values["last_sync_by"] = user
    for name, value in values.items():
        set_field(obj, name, value)

    reindex(obj)
    return obj


def set_state(container, key, state, user, now):
    """改一行状态 —— **同步唯一被允许修改已存在行的字段**（R2/R3）。"""
    obj = get_entry(container, key[0], key[1])
    if obj is None:
        logger.warn(
            "maitux.glossary: cannot set state '%s' for %s / %s (row missing)",
            state, key[0], key[1])
        return None

    current = text(getattr(obj, "sync_state", None))
    if current == state:
        return obj

    set_field(obj, u"sync_state", state)
    set_field(obj, u"state_changed_on", now)
    set_field(obj, u"last_sync_by", user)
    reindex(obj)
    return obj


def set_field(obj, name, value):
    """按字段名写值（走 schema 字段，带校验）。"""
    field = None
    try:
        field = api.get_fields(obj).get(name)
    except Exception:
        field = None
    if field is None:
        setattr(obj, name, value)
        return
    field.set(obj, value)


def reindex(obj):
    """重挂索引。

    ``reindexObject()`` 覆盖 portal_catalog；uid_catalog 再显式挂一次 ——
    列表页保存单元格时走的是 ``api.get_object_by_uid``（ajax_set_fields），
    uid_catalog 里查不到就会 500，所以这一步不能省。
    """
    try:
        obj.reindexObject()
    except Exception as exc:
        logger.warn("maitux.glossary: reindexObject failed for %s: %s",
                    obj.getId(), exc)
    path = "/".join(obj.getPhysicalPath())
    for tool_name in ("uid_catalog", "portal_catalog"):
        try:
            catalog = api.get_tool(tool_name)
            catalog.catalog_object(obj, path)
        except Exception as exc:
            logger.warn("maitux.glossary: cataloging %s into %s failed: %s",
                        path, tool_name, exc)


def log_outcome(outcome, max_samples=MAX_SAMPLES):
    """日志（唯一反馈渠道，界面不提示）。"""
    plan = outcome.plan
    if not outcome.ok:
        logger.error(
            "maitux.glossary: sync by %s FAILED after %.2fs: %s",
            outcome.user, outcome.elapsed, outcome.error)
        return

    # <<< 可 grep 的主信号 >>>
    logger.info("maitux.glossary: sync by %s: %s (%.2fs)",
                outcome.user, plan.summary(), outcome.elapsed)

    for sample in plan.sample_new(max_samples):
        logger.info("maitux.glossary:   new          %s", sample)
    for sample in plan.sample_deactivated(max_samples):
        logger.info("maitux.glossary:   deactivated  %s", sample)
    for sample in plan.sample_activated(max_samples):
        logger.info("maitux.glossary:   reactivated  %s", sample)

    if len(plan.to_create) > max_samples:
        logger.info("maitux.glossary:   ... and %d more new rows",
                    len(plan.to_create) - max_samples)
    if len(plan.to_deactivate) > max_samples:
        logger.info("maitux.glossary:   ... and %d more deactivated rows",
                    len(plan.to_deactivate) - max_samples)

    # 对账提示（不改表）
    if plan.zh_mismatch:
        logger.info(
            "maitux.glossary: %d row(s) where zh differs from the site "
            "Field title (zh is an independent term - reported only, never "
            "written back)", len(plan.zh_mismatch))
        for key, table_zh, site_title in plan.zh_mismatch[:max_samples]:
            logger.info("maitux.glossary:   zh-diff      %s / %s: table=%s "
                        "site=%s", key[0], key[1], table_zh, site_title)

    if outcome.duplicate_keywords:
        logger.error(
            "maitux.glossary: %d duplicate AnalysisService keyword(s) - the "
            "row key is no longer one-to-one, fix the site data first",
            len(outcome.duplicate_keywords))
        for keyword, titles in outcome.duplicate_keywords.items():
            logger.error("maitux.glossary:   duplicate    %s -> %s",
                         keyword, u" | ".join(titles))

    if outcome.orphan_calculations:
        logger.info(
            "maitux.glossary: %d active Calculation(s) are used by no active "
            "AnalysisService - their interims cannot form a row and are not "
            "imported: %s", len(outcome.orphan_calculations),
            u", ".join(outcome.orphan_calculations[:max_samples]))

    if outcome.title_conflicts:
        logger.warn(
            "maitux.glossary: %d interim title mismatch(es) between the "
            "service and its calculation: %s", len(outcome.title_conflicts),
            u"; ".join(outcome.title_conflicts[:max_samples]))

    if outcome.table_duplicates:
        logger.error("maitux.glossary: %d duplicated row key(s) in the table: "
                     "%s", len(outcome.table_duplicates),
                     u"; ".join(outcome.table_duplicates[:max_samples]))

    if plan.dirty_states:
        logger.warn("maitux.glossary: %d row(s) with an invalid sync_state: %s",
                    len(plan.dirty_states),
                    u"; ".join([u"%s/%s=%s" % (k[0], k[1], s)
                                for k, s in plan.dirty_states[:max_samples]]))
