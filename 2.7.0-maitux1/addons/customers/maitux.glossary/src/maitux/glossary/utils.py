# -*- coding: utf-8 -*-
#
# 中间表读写的小工具（容器/条目定位）
#
# 本模块**不 import content / sync 子包**，只按鸭子类型操作对象，
# 以免形成循环导入。纯函数在 keys.py（那个模块没有 Zope 依赖）。

from bika.lims import api

from maitux.glossary.config import CONTAINER_TYPE
from maitux.glossary.config import ENTRY_TYPE
from maitux.glossary.config import FOLDER_ID
from maitux.glossary.config import SETUP_FOLDER_ID
from maitux.glossary.keys import safe_unicode  # noqa: F401  (re-export)
from maitux.glossary.keys import text  # noqa: F401  (re-export)


def get_portal():
    return api.get_portal()


def _get_child(parent, child_id):
    """取直接子对象；不存在或取不到都返回 None。"""
    try:
        return parent._getOb(child_id, None)
    except Exception:
        return None


def get_container_parents(portal):
    """容器可能所在的父对象，**按优先级排列**。

    v2 起容器在 ``<site>/setup/keyword_glossary``（这样才会出现在设置菜单里，
    见 config.SETUP_FOLDER_ID 的说明）；v1 曾把它建在**站点根目录**下。
    所以两个位置都要找，setup 里的优先 —— 老站点在 setuphandlers 的迁移
    跑起来之前，也必须能读到老容器。
    """
    parents = []
    setup = _get_child(portal, SETUP_FOLDER_ID)
    if setup is not None:
        parents.append(setup)
    parents.append(portal)
    return parents


def get_container(portal=None):
    """取中间表容器；不存在返回 None（**幂等，不创建**）。

    注意：**所有读容器的地方都必须走这里**（列表页、手动刷新、查表 API）。
    v1 -> v2 改成"容器在 setup 下"时，这里漏改过一次，症状是手动刷新按钮
    报「未找到关键词对照表容器」，而列表页看起来一切正常（列表视图会把
    get_container() 的 None 回退成 self.context）。
    """
    portal = portal or get_portal()
    if portal is None:
        return None

    for parent in get_container_parents(portal):
        container = _get_child(parent, FOLDER_ID)
        if container is None:
            continue
        if api.get_portal_type(container) == CONTAINER_TYPE:
            return container
    return None


def iter_entries(container):
    """遍历容器内全部条目（不依赖任何 catalog 索引）。"""
    if container is None:
        return []
    try:
        values = list(container.objectValues())
    except Exception:
        return []
    return [obj for obj in values
            if api.get_portal_type(obj) == ENTRY_TYPE]


def get_entry(container, analysis_keyword, calc_keyword):
    """按 (analysis_keyword, calc_keyword) 取条目，走确定性 ID，O(1)。"""
    if container is None:
        return None
    from maitux.glossary.keys import make_entry_id
    entry_id = make_entry_id(analysis_keyword, calc_keyword)
    try:
        obj = container._getOb(entry_id, None)
    except Exception:
        obj = None
    if obj is None or api.get_portal_type(obj) != ENTRY_TYPE:
        return None
    # ID 由哈希派生，理论上不会撞；仍然核对一次两段 key。
    # 万一撞了就当"没有"——宁可新增一行，也不要张冠李戴。
    if text(getattr(obj, "analysis_keyword", None)) != text(analysis_keyword):
        return None
    if text(getattr(obj, "calc_keyword", None)) != text(calc_keyword):
        return None
    return obj


def find_by_calc_keyword(container, calc_keyword):
    """取同一 calc keyword 的全部行（含未激活行）。

    用来实现"人工编辑按 calc keyword 批量改"（R5）：
    同一字段的译文必须全表一致，否则这张表就不能当术语库用。
    """
    calc_keyword = text(calc_keyword)
    result = []
    for obj in iter_entries(container):
        if text(getattr(obj, "calc_keyword", None)) == calc_keyword:
            result.append(obj)
    return result
