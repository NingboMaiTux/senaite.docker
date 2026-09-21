# -*- coding: utf-8 -*-
"""字段定义 -> zope.schema 字段（Dexterity 侧）

标签一律给 ``Message`` 对象，**不给已翻译好的字符串**——schema 是构建一次
然后缓存的，把当前语言烤进 title 会让"第一个发起请求的人的语言变成之后所有
人看到的语言"，而且单人测试测不出来。详见 i18n.py 开头。
"""
import datetime
import decimal

from zope import schema
from zope.schema.vocabulary import SimpleTerm
from zope.schema.vocabulary import SimpleVocabulary

from maitux.dynamicfields import config
from maitux.dynamicfields import i18n

try:
    from senaite.core.schema import UIDReferenceField
except ImportError:  # pragma: no cover - 无 senaite 环境
    UIDReferenceField = None


def build_field(record):
    """按记录造一个 zope.schema 字段；造不出来返回 None（调用方跳过该条）"""
    field_type = record.get("type")
    builder = _BUILDERS.get(field_type)
    if builder is None:
        return None

    common = {
        "title": i18n.label_message(record),
        "description": i18n.description_message(record),
        "required": bool(record.get("required")),
    }
    field = builder(record, common)
    if field is None:
        return None
    field.readonly = bool(record.get("readonly"))
    return field


# --------------------------------------------------------------------------
# 各类型
# --------------------------------------------------------------------------

def _text(record, common):
    kwargs = dict(common)
    maxlen = _int_or_none(record.get("maxlen"))
    if maxlen:
        kwargs["max_length"] = maxlen
    default = record.get("default")
    if default:
        kwargs["default"] = _unicode(default)
    return schema.TextLine(**kwargs)


def _textarea(record, common):
    kwargs = dict(common)
    maxlen = _int_or_none(record.get("maxlen"))
    if maxlen:
        kwargs["max_length"] = maxlen
    default = record.get("default")
    if default:
        kwargs["default"] = _unicode(default)
    return schema.Text(**kwargs)


def _int(record, common):
    kwargs = dict(common)
    minimum = _int_or_none(record.get("min"))
    maximum = _int_or_none(record.get("max"))
    if minimum is not None:
        kwargs["min"] = minimum
    if maximum is not None:
        kwargs["max"] = maximum
    default = _int_or_none(record.get("default"))
    if default is not None:
        kwargs["default"] = default
    return schema.Int(**kwargs)


def _decimal(record, common):
    kwargs = dict(common)
    minimum = _decimal_or_none(record.get("min"))
    maximum = _decimal_or_none(record.get("max"))
    if minimum is not None:
        kwargs["min"] = minimum
    if maximum is not None:
        kwargs["max"] = maximum
    default = _decimal_or_none(record.get("default"))
    if default is not None:
        kwargs["default"] = default
    return schema.Decimal(**kwargs)


def _date(record, common):
    return schema.Date(**common)


def _datetime(record, common):
    return schema.Datetime(**common)


def _bool(record, common):
    kwargs = dict(common)
    kwargs["default"] = _bool_value(record.get("default"))
    # 布尔控件不要传 render_own_label（R16）——这里只造 schema，不碰 widget
    return schema.Bool(**kwargs)


def _choice(record, common):
    vocabulary = build_vocabulary(record)
    if record.get("multi"):
        kwargs = dict(common)
        kwargs["value_type"] = schema.Choice(vocabulary=vocabulary)
        kwargs["missing_value"] = []
        return schema.List(**kwargs)
    kwargs = dict(common)
    kwargs["vocabulary"] = vocabulary
    return schema.Choice(**kwargs)


def _reference(record, common):
    if UIDReferenceField is None:
        return None
    kwargs = dict(common)
    allowed = [str(t) for t in (record.get("allowed_types") or []) if t]
    kwargs["allowed_types"] = tuple(allowed)
    kwargs["multi_valued"] = bool(record.get("multi"))
    return UIDReferenceField(**kwargs)


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


# --------------------------------------------------------------------------

def build_vocabulary(record):
    """选项词汇表。

    ★ ``value`` 和 ``token`` 都用 ASCII key，``title`` 才是 Message。
    存进对象的是 key，不是中文标签——一旦存了中文，这份数据永远翻译不了，
    索引、导出、统计也全部锁死在中文上。
    """
    terms = []
    for option in record.get("options") or []:
        key = option.get("key")
        if not key:
            continue
        key = str(key)
        terms.append(SimpleTerm(
            value=key, token=key, title=i18n.option_message(record, key)))
    if not terms:
        # 空词汇表会让表单直接报错，给个占位
        terms.append(SimpleTerm(value="", token="", title=u""))
    return SimpleVocabulary(terms)


def missing_value_for(record):
    """字段未赋值时该返回什么。绝不能让页面炸在 AttributeError 上"""
    field_type = record.get("type")
    if field_type == config.TYPE_BOOL:
        return _bool_value(record.get("default"))
    if record.get("multi") and field_type in config.TYPES_MULTIVALUED:
        return []
    if field_type in (config.TYPE_TEXT, config.TYPE_TEXTAREA):
        default = record.get("default")
        return _unicode(default) if default else None
    return None


# --------------------------------------------------------------------------
# 类型转换小工具：全部吃掉异常，脏配置不许把页面搞挂
# --------------------------------------------------------------------------

def _unicode(value):
    if value is None:
        return u""
    try:
        if isinstance(value, bytes):
            return value.decode("utf-8", "ignore")
        return u"%s" % value
    except Exception:
        return u""


def _int_or_none(value):
    if value in (None, "", u""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _decimal_or_none(value):
    if value in (None, "", u""):
        return None
    try:
        return decimal.Decimal(str(value))
    except Exception:
        return None


def _bool_value(value):
    if isinstance(value, bool):
        return value
    if value in (None, "", u""):
        return False
    return u"%s" % value in (u"1", u"true", u"True", u"on", u"yes")


def parse_value(record, raw):
    """表单提交的原始值 -> 存进对象的值"""
    field_type = record.get("type")
    if field_type == config.TYPE_BOOL:
        return _bool_value(raw)
    if field_type == config.TYPE_INT:
        return _int_or_none(raw)
    if field_type == config.TYPE_DECIMAL:
        return _decimal_or_none(raw)
    if field_type in (config.TYPE_DATE, config.TYPE_DATETIME):
        return _parse_date(raw, field_type)
    if record.get("multi"):
        if raw in (None, "", u""):
            return []
        if isinstance(raw, (list, tuple)):
            return [_unicode(item) for item in raw if item]
        return [item for item in _unicode(raw).split(u",") if item]
    return _unicode(raw)


def _parse_date(raw, field_type):
    text = _unicode(raw).strip()
    if not text:
        return None
    formats = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M",
               "%Y-%m-%d")
    for fmt in formats:
        try:
            parsed = datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
        if field_type == config.TYPE_DATE:
            return parsed.date()
        return parsed
    return None
