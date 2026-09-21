# -*- coding: utf-8 -*-
"""字段定义 -> Archetypes 字段（AT 侧）

每个字段都得混入 ``ExtensionField``，否则 schemaextender 不认。

标签同样给 ``Message``，不给已翻译的字符串——AT widget 的模板对 label 和
选项文案都走 ``i18n:translate``，Message 自带 domain，会落到本包的翻译域上。
"""
from maitux.dynamicfields import config
from maitux.dynamicfields import i18n

try:
    from archetypes.schemaextender.field import ExtensionField
    from Products.Archetypes.public import BooleanField
    from Products.Archetypes.public import BooleanWidget
    from Products.Archetypes.public import DateTimeField
    from Products.Archetypes.public import DisplayList
    from Products.Archetypes.public import FixedPointField
    from Products.Archetypes.public import IntegerField
    from Products.Archetypes.public import IntegerWidget
    from Products.Archetypes.public import LinesField
    from Products.Archetypes.public import MultiSelectionWidget
    from Products.Archetypes.public import SelectionWidget
    from Products.Archetypes.public import StringField
    from Products.Archetypes.public import StringWidget
    from Products.Archetypes.public import TextAreaWidget
    from Products.Archetypes.public import TextField
    HAVE_AT = True
except ImportError:  # pragma: no cover - 无 AT 环境
    HAVE_AT = False
    ExtensionField = object

try:
    from bika.lims.browser.fields import UIDReferenceField
    from bika.lims.browser.widgets import DateTimeWidget
    from senaite.core.browser.widgets.referencewidget import ReferenceWidget
    HAVE_SENAITE = True
except ImportError:  # pragma: no cover
    HAVE_SENAITE = False


if HAVE_AT:

    class DynStringField(ExtensionField, StringField):
        pass

    class DynTextField(ExtensionField, TextField):
        pass

    class DynIntegerField(ExtensionField, IntegerField):
        pass

    class DynFixedPointField(ExtensionField, FixedPointField):
        pass

    class DynDateTimeField(ExtensionField, DateTimeField):
        pass

    class DynBooleanField(ExtensionField, BooleanField):
        pass

    class DynLinesField(ExtensionField, LinesField):
        pass

    if HAVE_SENAITE:
        class DynUIDReferenceField(ExtensionField, UIDReferenceField):
            pass
    else:  # pragma: no cover
        DynUIDReferenceField = None


def build_field(record):
    """按记录造一个 AT 字段；造不出来返回 None"""
    if not HAVE_AT:
        return None
    builder = _BUILDERS.get(record.get("type"))
    if builder is None:
        return None
    return builder(record)


# --------------------------------------------------------------------------

def _widget_kwargs(record):
    return {
        "label": i18n.label_message(record),
        "description": i18n.description_message(record),
        "visible": _visibility(record),
    }


def _visibility(record):
    """把「在编辑表单显示 / 在查看页显示」翻译成 AT 的 visible 字典"""
    edit = "visible" if record.get("show_edit") else "invisible"
    if record.get("readonly"):
        edit = "visible"
    view = "visible" if record.get("show_view") else "invisible"
    return {"edit": edit, "view": view}


def _base_kwargs(record):
    return {
        "required": bool(record.get("required")),
        "searchable": False,
        "schemata": record.get("fieldset") or "default",
        "mode": "r" if record.get("readonly") else "rw",
    }


def _text(record):
    kwargs = _base_kwargs(record)
    maxlen = _int_or_none(record.get("maxlen"))
    if maxlen:
        kwargs["max_length"] = maxlen
    if record.get("default"):
        kwargs["default"] = record.get("default")
    return DynStringField(
        str(record["name"]), widget=StringWidget(**_widget_kwargs(record)),
        **kwargs)


def _textarea(record):
    kwargs = _base_kwargs(record)
    if record.get("default"):
        kwargs["default"] = record.get("default")
    widget_kwargs = _widget_kwargs(record)
    widget_kwargs["rows"] = 4
    return DynTextField(
        str(record["name"]), widget=TextAreaWidget(**widget_kwargs), **kwargs)


def _int(record):
    kwargs = _base_kwargs(record)
    default = _int_or_none(record.get("default"))
    if default is not None:
        kwargs["default"] = default
    return DynIntegerField(
        str(record["name"]), widget=IntegerWidget(**_widget_kwargs(record)),
        **kwargs)


def _decimal(record):
    kwargs = _base_kwargs(record)
    precision = _int_or_none(record.get("precision"))
    if precision is not None:
        kwargs["precision"] = precision
    return DynFixedPointField(
        str(record["name"]), widget=StringWidget(**_widget_kwargs(record)),
        **kwargs)


def _date(record):
    return _datetime_field(record, show_time=False)


def _datetime(record):
    return _datetime_field(record, show_time=True)


def _datetime_field(record, show_time):
    kwargs = _base_kwargs(record)
    widget_kwargs = _widget_kwargs(record)
    if HAVE_SENAITE:
        widget_kwargs["show_time"] = show_time
        widget = DateTimeWidget(**widget_kwargs)
    else:  # pragma: no cover
        widget = StringWidget(**widget_kwargs)
    return DynDateTimeField(str(record["name"]), widget=widget, **kwargs)


def _bool(record):
    kwargs = _base_kwargs(record)
    kwargs["default"] = _bool_value(record.get("default"))
    widget_kwargs = _widget_kwargs(record)
    # R16：布尔控件不要传 render_own_label=True
    return DynBooleanField(
        str(record["name"]), widget=BooleanWidget(**widget_kwargs), **kwargs)


def _choice(record):
    kwargs = _base_kwargs(record)
    vocabulary = build_vocabulary(record)
    kwargs["vocabulary"] = vocabulary
    widget_kwargs = _widget_kwargs(record)
    if record.get("multi"):
        widget_kwargs["format"] = "checkbox"
        return DynLinesField(
            str(record["name"]),
            widget=MultiSelectionWidget(**widget_kwargs), **kwargs)
    widget_kwargs["format"] = "select"
    if record.get("default"):
        kwargs["default"] = str(record.get("default"))
    return DynStringField(
        str(record["name"]), widget=SelectionWidget(**widget_kwargs), **kwargs)


def _reference(record):
    if not HAVE_SENAITE or DynUIDReferenceField is None:
        return None
    kwargs = _base_kwargs(record)
    kwargs["multiValued"] = bool(record.get("multi"))
    allowed = [str(t) for t in (record.get("allowed_types") or []) if t]
    kwargs["allowed_types"] = tuple(allowed)
    widget_kwargs = _widget_kwargs(record)
    widget_kwargs["catalog"] = "portal_catalog"
    query = {
        "portal_type": allowed,
        "sort_on": "sortable_title",
        "sort_order": "ascending",
    }
    if not record.get("include_inactive"):
        query["is_active"] = True
    widget_kwargs["query"] = query
    # R12：传 query= 时必须同时传 base_query={}。base_query 是类级共享 dict，
    # get_query() 会原地 update(query)——不给本实例一个独占 dict，这些键会
    # 污染整个进程里所有 ReferenceWidget
    widget_kwargs["base_query"] = {}
    return DynUIDReferenceField(
        str(record["name"]), widget=ReferenceWidget(**widget_kwargs), **kwargs)


_BUILDERS = {
    config.TYPE_TEXT: _text,
    config.TYPE_TEXTAREA: _textarea,
    config.TYPE_INT: _int,
    config.TYPE_DECIMAL: _decimal,
    config.TYPE_DATE: _date,
    config.TYPE_DATETIME: _datetime,
    config.TYPE_BOOL: _bool,
    config.TYPE_CHOICE: _choice,
    config.TYPE_REFERENCE: _reference,
}


def build_vocabulary(record):
    """DisplayList((ASCII key, Message))

    ★ 存的是 key，显示的是 Message。AT 的 selection 模板对 option 文案走
    ``i18n:translate``，Message 自带 domain，会落到本包的翻译域上——所以
    **不能**在这里就把当前语言的中文塞进去（字段对象是跨请求缓存的）。
    """
    pairs = []
    for option in record.get("options") or []:
        key = option.get("key")
        if not key:
            continue
        key = str(key)
        pairs.append((key, i18n.option_message(record, key)))
    if not pairs:
        pairs = [("", u"")]
    return DisplayList(pairs)


def _int_or_none(value):
    if value in (None, "", u""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_value(value):
    if isinstance(value, bool):
        return value
    if value in (None, "", u""):
        return False
    return u"%s" % value in (u"1", u"true", u"True", u"on", u"yes")
