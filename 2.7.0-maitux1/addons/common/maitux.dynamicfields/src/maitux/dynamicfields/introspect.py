# -*- coding: utf-8 -*-
"""类型与字段内省：AT / DX 两套机制归一成同一个展示模型

机制判定看 FTI 的 ``meta_type``，**不看常量表**：

- ``Dexterity FTI``                                   -> DX
- ``Factory-based Type Information with dynamic views`` -> AT

这样上游把某个类型从 AT 迁成 DX（2.7 里 SampleType / SamplePoint / Supplier /
Contact / Worksheet 刚迁完，AnalysisRequest / Client / Instrument /
AnalysisService 迟早也会迁），本包只要不改代码就自动跟上，客户已配好的字段
定义一条都不用动。
"""
from maitux.dynamicfields import config
from maitux.dynamicfields import storage

try:
    from bika.lims import api
except ImportError:  # pragma: no cover
    api = None


MECH_AT = "AT"
MECH_DX = "DX"

DX_META_TYPE = "Dexterity FTI"

#: 本包生成的 schema / 字段所在模块前缀
OWN_MODULE_PREFIX = "maitux.dynamicfields"

#: 视为「原生」的模块前缀
NATIVE_PREFIXES = (
    "Products.Archetypes",
    "Products.CMFCore",
    "Products.CMFPlone",
    "plone.",
    "zope.",
    "senaite.core",
    "senaite.app",
    "bika.lims",
)


# --------------------------------------------------------------------------
# 机制判定
# --------------------------------------------------------------------------

def get_fti(portal_type):
    if api is None:
        return None
    try:
        tool = api.get_tool("portal_types")
    except Exception:
        return None
    if tool is None:
        return None
    try:
        return tool.getTypeInfo(portal_type)
    except Exception:
        return None


def get_mechanism(portal_type):
    """返回 ``AT`` / ``DX``；类型不存在返回 None"""
    fti = get_fti(portal_type)
    if fti is None:
        return None
    meta_type = getattr(fti, "meta_type", "") or ""
    if meta_type == DX_META_TYPE:
        return MECH_DX
    return MECH_AT


def type_exists(portal_type):
    return get_fti(portal_type) is not None


# --------------------------------------------------------------------------
# 类型清单
# --------------------------------------------------------------------------

def get_type_title(portal_type):
    return config.TYPE_TITLES.get(portal_type, portal_type)


def list_types(include_empty=True, query=None):
    """白名单内**且当前站点真实存在**的类型。

    清单从 portal_types 实测读取，不是手写死的——`Setup`(DX) / `BikaSetup`(AT)、
    `SampleTemplate`(DX) / `ARTemplate`(AT)、`ResultsReport`(DX) / `ARReport`(AT)
    这三对迁移遗留在站点上是两个 FTI 都真实注册着的，手写清单必然选错。
    """
    items = []
    for portal_type in config.ALLOWED_TYPES:
        if portal_type in config.EXCLUDED_TYPES:
            continue
        mechanism = get_mechanism(portal_type)
        if mechanism is None:
            # 当前站点没装这个类型（比如某些 addon 没装）
            continue
        count = storage.count_for_type(portal_type)
        if not include_empty and not count:
            continue
        if query and not _matches(query, portal_type,
                                  get_type_title(portal_type)):
            continue
        items.append({
            "portal_type": portal_type,
            "title": get_type_title(portal_type),
            "mechanism": mechanism,
            "count": count,
            "primary": portal_type in config.PRIMARY_TYPES,
        })
    return items


def list_type_groups(query=None):
    """按 config.TYPE_GROUPS 分组后的类型清单，供配置页左栏使用

    ★ 分组里那个列表的 key 叫 ``types`` 不叫 ``items``。TAL 的路径表达式
    ``group/items`` 在字典上会解析成 **dict.items() 方法**并调用它，拿回来的是
    (key, value) 元组列表，模板里再取 ``item['portal_type']`` 就报
    ``TypeError: tuple indices must be integers``。实测踩过。
    同理不要用 keys / values / get / copy / update / pop 当 key。
    """
    by_id = dict([(item["portal_type"], item)
                  for item in list_types(query=query)])
    groups = []
    used = set()
    for title, type_ids in config.TYPE_GROUPS:
        items = []
        for portal_type in type_ids:
            item = by_id.get(portal_type)
            if item is not None:
                items.append(item)
                used.add(portal_type)
        if items:
            groups.append({"title": title, "types": items})
    leftovers = [item for key, item in by_id.items() if key not in used]
    if leftovers:
        leftovers.sort(key=lambda i: i["portal_type"])
        groups.append({"title": u"其它", "types": leftovers})
    return groups


def _matches(query, *values):
    """关键字匹配：大小写不敏感，任一字段命中即可

    过滤放在服务端、走 GET 参数，不引 JS——这个配置页其余部分也都是
    整页 POST / GET，保持一致。
    """
    if not query:
        return True
    try:
        needle = query.strip().lower()
    except Exception:
        return True
    if not needle:
        return True
    for value in values:
        if value is None:
            continue
        try:
            if needle in u"%s" % value.lower():
                return True
        except Exception:
            continue
    return False


def list_reference_targets():
    """对象引用字段能指向哪些类型——**读全部 portal_type，不用白名单**

    白名单 ALLOWED_TYPES 管的是「哪些类型能被加字段」，跟「引用能指向谁」是
    两件事。早期两者共用一份清单，结果 Project / HazardCategory /
    StorageCondition 这些选不到，arextension 里三个引用字段直接复现不了。

    这里只排掉明显无意义的：临时对象、Plone 基础设施类型。
    """
    if api is None:
        return []
    try:
        tool = api.get_tool("portal_types")
        type_ids = tool.objectIds()
    except Exception:
        return []

    skip_prefixes = ("Temporary", "ATBooleanCriterion", "ATCurrentAuthor",
                     "ATDate", "ATList", "ATPath", "ATPortalType",
                     "ATReference", "ATRelative", "ATSelection",
                     "ATSimpleInt", "ATSimpleString", "ATSort", "ATBoolean")
    skip_exact = set(["Plone Site", "TempFolder", "Discussion Item",
                      "Topic", "Collection", "Document", "File", "Image",
                      "Folder", "Link", "News Item", "Event"])

    items = []
    for type_id in type_ids:
        if type_id in skip_exact:
            continue
        if any(type_id.startswith(prefix) for prefix in skip_prefixes):
            continue
        items.append({
            "portal_type": type_id,
            "title": config.TYPE_TITLES.get(type_id, type_id),
            "known": type_id in config.ALLOWED_TYPES,
        })
    items.sort(key=lambda i: (not i["known"], i["portal_type"]))
    return items


def get_workflow_states(portal_type):
    """该类型绑定的工作流状态 [(id, title)]，供「可编辑状态」下拉使用"""
    if api is None:
        return []
    try:
        wftool = api.get_tool("portal_workflow")
    except Exception:
        return []
    if wftool is None:
        return []
    states = []
    seen = set()
    try:
        chain = wftool.getChainForPortalType(portal_type) or ()
    except Exception:
        chain = ()
    for wf_id in chain:
        try:
            workflow = wftool.getWorkflowById(wf_id)
            for state_id, state in workflow.states.items():
                if state_id in seen:
                    continue
                seen.add(state_id)
                states.append((state_id, getattr(state, "title", "") or state_id))
        except Exception:
            continue
    states.sort(key=lambda s: s[0])
    return states


# --------------------------------------------------------------------------
# 字段内省
# --------------------------------------------------------------------------

def _find_instance(portal_type):
    """找一个该类型的实例。

    AT 侧必须拿实例才能看到 extender 追加的字段（比如
    INNOCARE.arextension 加在 AnalysisRequest 上的那 9 个）；只读注册表里的
    基础 schema 会把它们全漏掉。
    """
    if api is None:
        return None
    try:
        brains = api.search({"portal_type": portal_type, "sort_limit": 1})
    except Exception:
        return None
    for brain in brains[:1]:
        try:
            return api.get_object(brain)
        except Exception:
            return None
    return None


def _source_from_module(module_name):
    """模块名 -> 来源标签 (source_id, kind)

    kind: ``own`` 本包 / ``native`` 原生 / ``addon`` 其它 add-on
    """
    module_name = module_name or ""
    if module_name.startswith(OWN_MODULE_PREFIX):
        return OWN_MODULE_PREFIX, "own"
    for prefix in NATIVE_PREFIXES:
        if module_name.startswith(prefix):
            return "senaite.core", "native"
    parts = module_name.split(".")
    if len(parts) >= 2:
        return ".".join(parts[:2]), "addon"
    return module_name or "unknown", "addon"


def _dx_fields(portal_type, instance):
    from zope.schema import getFieldsInOrder

    schemata = []
    try:
        if instance is not None:
            from plone.dexterity.utils import iterSchemata
            schemata = list(iterSchemata(instance))
        else:
            from plone.dexterity.utils import iterSchemataForType
            schemata = list(iterSchemataForType(portal_type))
    except Exception:
        schemata = []

    fields = []
    for schema in schemata:
        module_name = getattr(schema, "__module__", "") or ""
        source, kind = _source_from_module(module_name)
        try:
            pairs = getFieldsInOrder(schema)
        except Exception:
            continue
        for name, field in pairs:
            fields.append({
                "name": name,
                "type": field.__class__.__name__,
                "label": _safe_text(getattr(field, "title", u"")),
                "required": bool(getattr(field, "required", False)),
                "source": source,
                "kind": kind,
            })
    return fields


def _at_fields(portal_type, instance):
    schema = None
    if instance is not None:
        try:
            schema = instance.Schema()
        except Exception:
            schema = None
    if schema is None:
        schema = _registered_at_schema(portal_type)
    if schema is None:
        return []

    fields = []
    try:
        raw_fields = schema.fields()
    except Exception:
        return []
    for field in raw_fields:
        module_name = getattr(field.__class__, "__module__", "") or ""
        source, kind = _source_from_module(module_name)
        widget = getattr(field, "widget", None)
        label = getattr(widget, "label", u"") if widget is not None else u""
        fields.append({
            "name": getattr(field, "__name__", u""),
            "type": field.__class__.__name__,
            "label": _safe_text(label),
            "required": bool(getattr(field, "required", False)),
            "source": source,
            "kind": kind,
        })
    return fields


def _registered_at_schema(portal_type):
    """没有实例时的兜底：archetype_tool 里注册的基础 schema（不含 extender）"""
    if api is None:
        return None
    try:
        tool = api.get_tool("archetype_tool")
    except Exception:
        return None
    if tool is None:
        return None
    try:
        for entry in tool.listRegisteredTypes(inProject=True):
            if entry.get("portal_type") == portal_type \
                    or entry.get("name") == portal_type:
                return entry.get("schema")
    except Exception:
        return None
    return None


def _safe_text(value):
    if value is None:
        return u""
    try:
        if isinstance(value, bytes):
            return value.decode("utf-8", "ignore")
        return u"%s" % value
    except Exception:
        return u""


def get_all_fields(portal_type):
    """该类型当前的**全部**字段，含来源标注。

    返回 [{name, type, label, required, source, kind}]，
    kind 为 ``own`` / ``native`` / ``addon``。
    """
    mechanism = get_mechanism(portal_type)
    if mechanism is None:
        return []
    instance = _find_instance(portal_type)
    if mechanism == MECH_DX:
        return _dx_fields(portal_type, instance)
    return _at_fields(portal_type, instance)


def get_foreign_field_names(portal_type):
    """本包之外的字段名集合，供重名校验使用

    注意边界：其它 add-on 若像 INNOCARE.labid 那样用运行时 IBehaviorAssignable
    挂 DX 字段，且当前站点没有该类型的实例，这里可能漏掉它——此时重名校验会放行。
    实例存在时（正常运行的站点）不受影响。
    """
    names = set()
    for field in get_all_fields(portal_type):
        if field.get("kind") != "own":
            names.add(field.get("name"))
    return names


def group_fields(portal_type):
    """按来源切三段，配置页右栏直接用

    「原生字段不能删」因此是**看得见的结构**，不是一条藏在代码里的校验：
    可删除的集合天然只有 own 那一段，另外两段界面上根本渲染不出删除按钮。
    """
    own, addon, native = [], [], []
    for field in get_all_fields(portal_type):
        kind = field.get("kind")
        if kind == "own":
            own.append(field)
        elif kind == "addon":
            addon.append(field)
        else:
            native.append(field)
    return {"own": own, "addon": addon, "native": native}
