# -*- coding: utf-8 -*-
"""Dexterity 侧：按配置动态生成 behavior schema

为什么能不写 FTI、不要 profile：``getAdditionalSchemata()`` 拿到 context 时走的是
``IBehaviorAssignable(context).enumerateBehaviors()``，**每次都调、没有缓存**，
而 ``BehaviorRegistration`` 是我们自己构造的对象，它的 ``interface`` 可以是任何
运行时生成的 schema。仓库里 INNOCARE.labid/assignable.py 就是这个套路，
只是它的 schema 是静态的。

所以配置改完下一个请求就生效，不需要重启、也不需要动 ``SCHEMA_CACHE``
（那个缓存的是 FTI 上登记的 behavior，跟我们这条路无关）。
"""
from zope.component import provideAdapter
from zope.interface import Interface
from zope.interface import directlyProvides
from zope.interface.interface import InterfaceClass

from maitux.dynamicfields import dxfields
from maitux.dynamicfields import i18n
from maitux.dynamicfields import storage

try:
    from plone.autoform.interfaces import IFormFieldProvider
    from plone.autoform.interfaces import MODES_KEY
    from plone.autoform.interfaces import OMITTED_KEY
except ImportError:  # pragma: no cover
    IFormFieldProvider = None
    MODES_KEY = "plone.autoform.modes"
    OMITTED_KEY = "plone.autoform.omitted"

try:
    from plone.supermodel.interfaces import FIELDSETS_KEY
    from plone.supermodel.model import Fieldset
except ImportError:  # pragma: no cover
    FIELDSETS_KEY = "plone.supermodel.fieldsets"
    Fieldset = None

try:
    from senaite.core import logger
except ImportError:  # pragma: no cover
    import logging
    logger = logging.getLogger("maitux.dynamicfields")


#: 生成的 schema 放在这个虚拟模块下——introspect 靠它认出"本包添加的字段"
GENERATED_MODULE = "maitux.dynamicfields.generated"

#: {portal_type: (revision, interface)}
_SCHEMA_CACHE = {}

#: 已经 provideAdapter 过的 interface，避免重复注册
_REGISTERED = set()


def get_schema(portal_type):
    """返回该类型的动态 schema；没有字段时返回 None

    按 (portal_type, 配置版本号) 缓存。改一次配置 rev 加一，缓存自然失效——
    不需要任何显式的 invalidate 调用。
    """
    try:
        revision = storage.get_revision()
    except Exception:
        return None

    cached = _SCHEMA_CACHE.get(portal_type)
    if cached is not None and cached[0] == revision:
        return cached[1]

    try:
        interface = _build_schema(portal_type)
    except Exception:
        # NFR-1：一条脏配置绝不许让站点起不来 / 让页面 500
        logger.exception(
            "maitux.dynamicfields: failed to build DX schema for %s",
            portal_type)
        interface = None

    _SCHEMA_CACHE[portal_type] = (revision, interface)
    return interface


def invalidate(portal_type=None):
    """手工清缓存（配置页保存后调一次，省得等下一个 rev 比较）"""
    if portal_type is None:
        _SCHEMA_CACHE.clear()
    else:
        _SCHEMA_CACHE.pop(portal_type, None)


# --------------------------------------------------------------------------

def _build_schema(portal_type):
    records = storage.get_records_for_type(portal_type)
    if not records:
        return None

    attrs = {}
    kept = []
    for index, record in enumerate(records):
        name = record.get("name")
        if not name:
            continue
        try:
            field = dxfields.build_field(record)
        except Exception:
            # 单条脏配置只跳过自己，不连累同类型的其它字段
            logger.exception(
                "maitux.dynamicfields: skipping bad field %r on %s",
                name, portal_type)
            continue
        if field is None:
            continue
        # order 决定表单里的先后。给一个大基数，排在原生字段后面
        field.order = 10000 + int(record.get("order") or 0) * 10 + index
        attrs[str(name)] = field
        kept.append(record)

    if not attrs:
        return None

    interface = InterfaceClass(
        str("IDynamicFields_%s" % portal_type),
        (Interface,),
        attrs,
        __module__=GENERATED_MODULE,
    )

    # 必须 directlyProvides：getAdditionalSchemata 用
    # IFormFieldProvider(schema, None) 取表单 schema，接口自身提供它才会被返回
    if IFormFieldProvider is not None:
        directlyProvides(interface, IFormFieldProvider)

    _apply_form_hints(interface, kept)
    _register_factory(interface, kept)
    return interface


def _apply_form_hints(interface, records):
    """把「前端显示」那几个开关翻译成 plone.autoform 的 tagged value"""
    omitted = []
    modes = []
    for record in records:
        name = str(record.get("name"))
        if not record.get("show_edit"):
            # 字段仍然存在、仍然能被接口 / 脚本写，只是编辑表单上不出现
            omitted.append((Interface, name, "true"))
        elif record.get("readonly"):
            modes.append((Interface, name, "display"))
    try:
        if omitted:
            interface.setTaggedValue(OMITTED_KEY, omitted)
        if modes:
            interface.setTaggedValue(MODES_KEY, modes)
        _apply_fieldsets(interface, records)
    except Exception:
        logger.exception("maitux.dynamicfields: failed to apply form hints")


def _apply_fieldsets(interface, records):
    """非 default 分组的字段收进各自的 fieldset"""
    if Fieldset is None:
        return
    groups = {}
    for record in records:
        name = str(record.get("name"))
        fieldset = record.get("fieldset") or "default"
        if fieldset == "default":
            continue
        groups.setdefault(fieldset, []).append(name)
    if not groups:
        return
    fieldsets = []
    for label in sorted(groups.keys()):
        fieldsets.append(Fieldset(
            str(label), label=label, fields=groups[label]))
    interface.setTaggedValue(FIELDSETS_KEY, fieldsets)


# --------------------------------------------------------------------------
# behavior 工厂
# --------------------------------------------------------------------------

class DynamicFieldsBehavior(object):
    """behavior 工厂：把字段读写**转发到底层对象**

    ★ 这层转发不能省。z3c.form 的 IDataManager（``z3c/form/datamanager.py``
    的 ``AttributeField``）读写的是 ``self.field.interface(context)`` —— 也就是
    本类的实例，**不是** 内容对象本身::

        context = self.field.interface(context)
        getattr(context, name) / setattr(context, name, value)

    少了转发，保存时值只会写到这个临时实例上，请求结束即丢，页面刷新后字段
    还是空的（表单返回 302 不报错，属静默失效）。这条是 INNOCARE.labid 踩过
    并写进注释的坑。
    """

    def __init__(self, context):
        # 不能走 self.context = context，那会撞上下面的 __setattr__
        self.__dict__["context"] = context

    def __getattr__(self, name):
        if name.startswith("_") or name == "context":
            raise AttributeError(name)
        context = self.__dict__.get("context")
        if context is None:
            raise AttributeError(name)
        marker = object()
        value = getattr(context, name, marker)
        if value is not marker:
            return value
        # 没赋过值：回落到配置里的默认值，绝不抛 AttributeError
        record = _record_for(context, name)
        if record is None:
            raise AttributeError(name)
        return dxfields.missing_value_for(record)

    def __setattr__(self, name, value):
        if name == "context":
            self.__dict__["context"] = value
            return
        context = self.__dict__.get("context")
        if context is None:
            self.__dict__[name] = value
            return
        setattr(context, name, value)


def _record_for(context, name):
    try:
        from bika.lims import api
        portal_type = api.get_portal_type(context)
    except Exception:
        portal_type = getattr(context, "portal_type", None)
    if not portal_type:
        return None
    return storage.get_record_by_name(portal_type, name)


def _register_factory(interface, records):
    """运行时把工厂注册成 ``interface`` 的适配器

    z3c.form 的 data manager 要靠 ``interface(context)`` 适配，而动态 schema
    没法写在 ZCML 里。这里注册的是**进程级**的全局适配器，不写数据库，每次
    重启 / 重建 schema 都会重来一遍。``provides`` 是每次新生成的唯一接口对象，
    所以不会跟别的注册撞。
    """
    key = id(interface)
    if key in _REGISTERED:
        return
    try:
        provideAdapter(
            DynamicFieldsBehavior, adapts=(Interface,), provides=interface)
        _REGISTERED.add(key)
    except Exception:
        logger.exception(
            "maitux.dynamicfields: failed to register schema adapter")


# --------------------------------------------------------------------------

def read_value(context, record):
    """读一个动态字段的当前值（视图 / 导出用）"""
    name = record.get("name")
    if not name:
        return None
    marker = object()
    value = getattr(context, name, marker)
    if value is marker:
        return dxfields.missing_value_for(record)
    return value


def option_labels(record, language):
    """{key: 当前语言的标签}，列表页 / 只读展示用"""
    labels = {}
    for option in record.get("options") or []:
        key = option.get("key")
        if not key:
            continue
        labels[str(key)] = i18n.pick_text(
            option.get("labels") or {}, language, fallback=str(key))
    return labels
