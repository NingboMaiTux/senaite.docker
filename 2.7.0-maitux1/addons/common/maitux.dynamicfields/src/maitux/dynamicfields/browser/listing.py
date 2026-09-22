# -*- coding: utf-8 -*-
"""把配置了「列表列」的自定义字段注入到 SENAITE 的列表视图

为什么需要这个模块
------------------
「在编辑页显示」「在查看页显示」是 schema 层面的事，造字段时设一下
widget 的 visibility 就完了。**列表列不是**：列表视图的列来自视图类里
一份写死的 ``self.columns``（OrderedDict），跟 schema 毫无关系。所以
早先版本里 ``show_list`` / ``list_default`` 存了但没人读，勾了不生效 ——
2026-09-21 因此把这两个开关从界面上撤掉过一轮，这个模块就是来补它的。

怎么接进去
----------
走 senaite.app.listing 官方的 ``IListingViewAdapter`` 订阅者扩展点，
用官方的 ``add_column()`` 往视图里插列。不覆盖视图类、不打补丁。

- ``before_render()``：按这个列表在列的 portal_type 找出配置了
  ``show_list`` 的字段，给每个插一列。``list_default`` 映射成列定义里的
  ``toggle``（True = 打开列表就带出来；False = 只出现在「列」下拉菜单里）。
- ``folder_item()``：给每一行填值。

为什么注册给**所有**列表（for 的第二项是 Interface）
----------------------------------------------------
本包是平台级的，事先不知道用户会给哪个类型加字段，没法按对象接口逐个
注册。所以订阅所有列表，在 ``before_render()`` 里按当前列表的
``contentFilter["portal_type"]`` 决定要不要动手 —— 没有配置列的类型
（绝大多数）在第一个 if 就返回了，代价是一次字典查表。

lint 的 R14 / E17 要求「往外来视图注入 UI 必须判 browser layer」。本包
没有 browser layer，也不需要：它随镜像发布，不存在「没装本包的站点」，
E17 防的那种泄漏在这儿不成立（lint 的 scan_ui_gating 对无 layer 的包
直接返回空，不会误报）。真正的门控是数据驱动的：没配置就什么都不注入。

为什么要求 metadata
-------------------
列表的每一行拿到的是**目录 brain**，不是对象本身。字段值要出现在 brain
上，必须建元数据列（配置页上「元数据列」那个开关）。没建的话这里会退回
去唤醒对象读属性 —— 能出结果，但一页 50 行就是 50 次对象加载，所以
校验层要求勾了「列表列」就得勾「元数据列」（validation.v_needs_metadata）。
"""

from zope.interface import implements

from senaite.app.listing.interfaces import IListingViewAdapter
from senaite.app.listing.utils import add_column

from maitux.dynamicfields import config
from maitux.dynamicfields import i18n
from maitux.dynamicfields import storage

try:                                        # pragma: no cover
    from bika.lims import api
except ImportError:                         # pragma: no cover
    api = None

try:                                        # pragma: no cover
    string_types = (str, unicode)           # noqa: F821  (py2)
except NameError:                           # pragma: no cover
    string_types = (str,)


#: brain 上没有、也唤不醒对象时显示的东西。空串而不是 "N/A"：
#: 列表里一片 N/A 比一片空白更吵，而且 N/A 还得翻译。
EMPTY = u""


def _as_unicode(value):
    if value is None:
        return u""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return value.decode("utf-8", "ignore")
    if isinstance(value, unicode):          # noqa: F821  (py2)
        return value
    try:
        return u"%s" % value
    except Exception:
        return u""


class DynamicFieldsListingAdapter(object):
    """给列表视图补上自定义字段的列"""

    implements(IListingViewAdapter)

    # 排在既有列后面。不插队：用户自己加的字段没理由挤掉原生列。
    priority_order = 99

    def __init__(self, view, context):
        self.view = view
        self.context = context
        self._records_cache = None

    # ------------------------------------------------------------------
    # 判断要不要动手
    # ------------------------------------------------------------------

    def _portal_types(self):
        """这个列表在列哪些类型的对象

        contentFilter 里的 portal_type 可能是字符串、也可能是列表/元组，
        还可能压根没有（有些列表按别的条件查）。都当没有处理。
        """
        content_filter = getattr(self.view, "contentFilter", None)
        if not isinstance(content_filter, dict):
            return []
        types = content_filter.get("portal_type")
        if not types:
            return []
        if isinstance(types, string_types):
            types = [types]
        try:
            return [str(t) for t in types]
        except Exception:
            return []

    def _records(self):
        """当前列表该显示的自定义字段配置，按组内排序排好"""
        if self._records_cache is not None:
            return self._records_cache
        found = []
        for portal_type in self._portal_types():
            try:
                records = storage.get_records_for_type(portal_type)
            except Exception:
                continue
            for record in records:
                if record.get("show_list"):
                    found.append(record)
        found.sort(key=lambda r: (r.get("order") or 0, r.get("name") or ""))
        self._records_cache = found
        return found

    # ------------------------------------------------------------------
    # IListingViewAdapter
    # ------------------------------------------------------------------

    def before_render(self):
        records = self._records()
        if not records:
            # 绝大多数列表走这条路：一次 portal_type 查表就返回
            return

        language = self._language()
        state_ids = [s.get("id") for s in getattr(self.view, "review_states", [])
                     if s.get("id")]
        for record in records:
            name = str(record.get("name") or "")
            if not name:
                continue
            column = {
                "title": i18n.pick_text(record.get("labels") or {},
                                        language, fallback=name),
                # 不声明 index：自定义字段不一定建了目录索引，声明了却排不了
                # 序，前端点表头会静默无反应，比不给排序更糟。
                "sortable": False,
                "toggle": bool(record.get("list_default")),
            }
            try:
                add_column(self.view, name, column, review_states=state_ids)
            except Exception:
                # 某个列插不进去不该让整张列表 500
                continue

    def folder_item(self, obj, item, index):
        records = self._records()
        if not records:
            return item
        for record in records:
            name = str(record.get("name") or "")
            if not name:
                continue
            try:
                item[name] = self._render(record, obj)
            except Exception:
                item[name] = EMPTY
        return item

    # ------------------------------------------------------------------
    # 取值与呈现
    # ------------------------------------------------------------------

    def _language(self):
        request = getattr(self.view, "request", None)
        if request is None:
            return i18n.get_default_language()
        return i18n.get_request_language(request)

    def _raw_value(self, record, obj):
        """先从 brain 取；brain 上没有才唤醒对象

        勾了「列表列」就要求勾「元数据列」，所以正常情况下第一步就命中，
        不会有 N 次对象加载。
        """
        name = str(record.get("name") or "")
        value = getattr(obj, name, None)
        if value is not None:
            return value
        if api is None:
            return None
        try:
            target = api.get_object(obj)
        except Exception:
            return None
        if target is obj:
            return None
        accessor = getattr(target, "get%s" % name, None)
        if callable(accessor):
            try:
                return accessor()
            except Exception:
                return None
        return getattr(target, name, None)

    def _render(self, record, obj):
        value = self._raw_value(record, obj)
        if value is None or value == "":
            return EMPTY

        field_type = record.get("type")

        if field_type == config.TYPE_BOOL:
            # 用勾号而不是 True/False：列表里一列 True/False 既不好看
            # 也不用翻译得动
            return u"✓" if value else EMPTY

        if field_type == config.TYPE_CHOICE:
            return self._render_choice(record, value)

        if field_type == config.TYPE_REFERENCE:
            return self._render_reference(value)

        if field_type in (config.TYPE_DATE, config.TYPE_DATETIME):
            return self._render_date(value, field_type)

        if isinstance(value, (list, tuple)):
            return u", ".join(_as_unicode(v) for v in value if v is not None)

        return _as_unicode(value)

    def _render_choice(self, record, value):
        """存的是 ASCII key，列表里要显示对应语言的标签"""
        language = self._language()
        options = {}
        for option in (record.get("options") or []):
            key = (option or {}).get("key")
            if key is None:
                continue
            options[_as_unicode(key)] = i18n.pick_text(
                option.get("labels") or {}, language, fallback=_as_unicode(key))
        values = value if isinstance(value, (list, tuple)) else [value]
        out = []
        for one in values:
            key = _as_unicode(one)
            if not key:
                continue
            # 配置里删掉过的选项，对象上可能还留着旧 key —— 原样显示，
            # 总比显示空白让人以为没填强
            out.append(options.get(key, key))
        return u", ".join(out)

    def _render_reference(self, value):
        """存的是 UID，显示被指向对象的标题"""
        if api is None:
            return _as_unicode(value)
        uids = value if isinstance(value, (list, tuple)) else [value]
        out = []
        for uid in uids:
            uid = _as_unicode(uid)
            if not uid:
                continue
            try:
                target = api.get_object_by_uid(uid, default=None)
            except Exception:
                target = None
            if target is None:
                # 指向的对象被删了。显示 UID 而不是空白：至少看得出
                # 「这里有个坏引用」，不然像是没填。
                out.append(uid)
                continue
            try:
                out.append(_as_unicode(api.get_title(target)))
            except Exception:
                out.append(uid)
        return u", ".join(out)

    def _render_date(self, value, field_type):
        if api is None:
            return _as_unicode(value)
        long_format = field_type == config.TYPE_DATETIME
        try:
            return _as_unicode(
                api.to_localized_time(value, long_format=long_format))
        except Exception:
            return _as_unicode(value)
