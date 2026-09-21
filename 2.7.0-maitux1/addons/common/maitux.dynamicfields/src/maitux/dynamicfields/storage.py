# -*- coding: utf-8 -*-
"""字段定义的持久化：portal annotation

为什么不用 ``plone.registry`` / ``registry.xml``：本包随镜像发布、站点侧不安装，
**拿不到 GenericSetup profile 这个执行时机**（`common-addons.cfg` 里 [plonesite]
那段是死代码，实测 profile 一条都进不去）。annotation 不需要任何 profile。

代价：配置不随 profile 导出导入，所以必须自带 JSON 导出 / 导入（见 browser/view.py）。

记录结构（**机制中立**——不写"这是 AT 字段"还是"DX 字段"，走哪条生成路径
由运行时查 FTI 的 meta_type 决定）::

    {
      "id": "<32 位 hex>",         # 稳定主键，重命名标签也不变
      "portal_type": "AnalysisRequest",
      "name": "contract_no",        # ASCII，创建后不可改
      "type": "text",               # config.FIELD_TYPE_IDS 之一，创建后不可改
      "labels": {"zh-cn": u"合同编号", "en": u"Contract No."},
      "descriptions": {...},
      "required": False, "readonly": False, "default": None,
      "states": [],                 # 可编辑工作流状态，空 = 不限
      "show_edit": True, "show_view": True,
      "show_list": False, "list_default": False, "show_report": False,
      "fieldset": "default", "order": 0,
      "index": False, "metadata": False,
      "options": [{"key": "normal", "labels": {...}}],
      "multi": False, "allowed_types": [],
      "min": None, "max": None, "precision": 2,
      "maxlen": None, "regex": "", "regex_msg": {},
      "created": "2026-09-21T10:00:00", "creator": "admin",
    }
"""
import json
import re
import uuid
from datetime import datetime

from persistent.mapping import PersistentMapping
from zope.annotation.interfaces import IAnnotations

from maitux.dynamicfields import config

try:
    from bika.lims import api
except ImportError:  # pragma: no cover - 仅在无 senaite 环境的单测里
    api = None


# --------------------------------------------------------------------------
# 底层读写
# --------------------------------------------------------------------------

def get_portal(portal=None):
    if portal is not None:
        return portal
    if api is None:
        return None
    try:
        return api.get_portal()
    except Exception:
        return None


def _container(portal=None, create=True):
    """返回 annotation 里的配置容器；取不到时返回 None（绝不抛）"""
    portal = get_portal(portal)
    if portal is None:
        return None
    try:
        annotations = IAnnotations(portal)
    except Exception:
        return None
    store = annotations.get(config.ANNOTATION_KEY)
    if store is None:
        if not create:
            return None
        store = PersistentMapping()
        store["rev"] = 0
        store["fields"] = PersistentMapping()
        annotations[config.ANNOTATION_KEY] = store
    if "fields" not in store:
        store["fields"] = PersistentMapping()
    if "rev" not in store:
        store["rev"] = 0
    return store


def get_revision(portal=None):
    """配置版本号。schema 缓存用它做 key——改一次配置加一，缓存自然失效"""
    store = _container(portal, create=False)
    if store is None:
        return 0
    try:
        return int(store.get("rev", 0))
    except Exception:
        return 0


def _bump(store):
    try:
        store["rev"] = int(store.get("rev", 0)) + 1
    except Exception:
        store["rev"] = 1


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------

def get_all_records(portal=None):
    """全部字段定义，按 (portal_type, order, name) 排序。任何异常都返回 []"""
    store = _container(portal, create=False)
    if store is None:
        return []
    try:
        records = [dict(r) for r in store["fields"].values()]
    except Exception:
        return []
    records.sort(key=lambda r: (r.get("portal_type") or "",
                                r.get("order") or 0,
                                r.get("name") or ""))
    return records


def get_records_for_type(portal_type, portal=None):
    """某个 portal_type 上的字段定义。**热路径**：AT/DX 两边每请求都会调到"""
    return [r for r in get_all_records(portal)
            if r.get("portal_type") == portal_type]


def get_record(field_id, portal=None):
    store = _container(portal, create=False)
    if store is None:
        return None
    try:
        record = store["fields"].get(field_id)
    except Exception:
        return None
    return dict(record) if record is not None else None


def get_record_by_name(portal_type, name, portal=None):
    for record in get_records_for_type(portal_type, portal):
        if record.get("name") == name:
            return record
    return None


def count_for_type(portal_type, portal=None):
    return len(get_records_for_type(portal_type, portal))


def count_all(portal=None):
    return len(get_all_records(portal))


# --------------------------------------------------------------------------
# 写入
# --------------------------------------------------------------------------

def _now():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _current_user():
    if api is None:
        return u""
    try:
        return api.get_current_user().getUserName() or u""
    except Exception:
        return u""


def new_id():
    return uuid.uuid4().hex


def defaults(portal_type, name, field_type):
    """一条新记录的完整默认值。新增可选项时只改这里，老记录读取走 .get()"""
    return {
        "id": new_id(),
        "portal_type": portal_type,
        "name": name,
        "type": field_type,
        "labels": {},
        "descriptions": {},
        "required": False,
        "readonly": False,
        "default": None,
        "states": [],
        "show_edit": True,
        "show_view": True,
        "show_list": False,
        "list_default": False,
        # 二期：报告模板尚未接入本包配置
        "show_report": False,
        "fieldset": "default",
        "order": 0,
        "index": False,
        "metadata": False,
        "options": [],
        "multi": False,
        "allowed_types": [],
        "include_inactive": False,
        "min": None,
        "max": None,
        "precision": 2,
        "maxlen": None,
        "regex": "",
        "regex_msg": {},
        "created": _now(),
        "creator": _current_user(),
    }


def save_record(record, portal=None):
    """新增或整条覆盖。调用方负责先过 validation.validate_record()"""
    store = _container(portal)
    if store is None:
        raise RuntimeError("dynamicfields: no portal annotation available")
    field_id = record.get("id") or new_id()
    record["id"] = field_id
    persistent = PersistentMapping()
    persistent.update(record)
    store["fields"][field_id] = persistent
    _bump(store)
    return field_id


def delete_record(field_id, portal=None):
    """删除定义。对象上已写入的属性值**保留不清理**（v1，快且无风险）"""
    store = _container(portal, create=False)
    if store is None:
        return None
    try:
        record = store["fields"].pop(field_id, None)
    except Exception:
        return None
    if record is not None:
        _bump(store)
        return dict(record)
    return None


# --------------------------------------------------------------------------
# 导入 / 导出
# --------------------------------------------------------------------------

def export_json(portal=None):
    """导出全部定义。因为不走 GenericSetup，这是唯一的配置搬运方式"""
    payload = {
        "version": 1,
        "exported": _now(),
        "revision": get_revision(portal),
        "fields": get_all_records(portal),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def import_json(text, mode="merge", portal=None):
    """导入定义。

    :param mode: ``merge`` 只加不删（同 portal_type+name 视为同一条，覆盖）；
                 ``replace`` 先清空再导入。
    :returns: (added, updated, skipped, errors)
    """
    from maitux.dynamicfields import validation

    try:
        payload = json.loads(text)
    except Exception as exc:
        return 0, 0, 0, [u"JSON 解析失败：%s" % exc]

    incoming = payload.get("fields") if isinstance(payload, dict) else payload
    if not isinstance(incoming, list):
        return 0, 0, 0, [u"JSON 结构不对：缺少 fields 列表"]

    store = _container(portal)
    if store is None:
        return 0, 0, 0, [u"取不到 portal，无法导入"]

    if mode == "replace":
        store["fields"] = PersistentMapping()

    added = updated = skipped = 0
    errors = []
    for raw in incoming:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        portal_type = raw.get("portal_type")
        name = raw.get("name")
        record = defaults(portal_type or "", name or "", raw.get("type") or "")
        record.update(raw)
        problems = validation.validate_record(
            record, portal=portal, existing_id=None, skip_uniqueness=True)
        if problems:
            skipped += 1
            errors.append(u"%s.%s：%s" % (portal_type, name, u"；".join(problems)))
            continue
        existing = get_record_by_name(portal_type, name, portal)
        if existing is not None:
            record["id"] = existing["id"]
            updated += 1
        else:
            record["id"] = record.get("id") or new_id()
            added += 1
        persistent = PersistentMapping()
        persistent.update(record)
        store["fields"][record["id"]] = persistent

    _bump(store)
    return added, updated, skipped, errors


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------

_NAME_RE = re.compile(config.FIELD_NAME_PATTERN)
_OPTION_RE = re.compile(config.OPTION_KEY_PATTERN)


def is_valid_name(name):
    return bool(name and _NAME_RE.match(name))


def is_valid_option_key(key):
    return bool(key and _OPTION_RE.match(key))
