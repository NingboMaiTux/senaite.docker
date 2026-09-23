# -*- coding: utf-8 -*-
"""maitux.stock 的翻译助手：把界面文案按"当前请求语言"翻译。

背景（这是本项目"中英双语"的统一做法，参考 maitux.hazardcategories）：

* ``zope.i18n.translate(msgid, domain="maitux.stock", context=request)``
  会按当前语言查本包的目录：英文站显示英文 msgid，中文站显示 ``locales/zh*/`` 里的中文。
* SENAITE 列表的 **列名 / 页签名 / 按钮名** 是在 Python 里拼进 JSON 的，
  渲染阶段不会再过一遍翻译 —— 所以必须**在构造视图时**就翻译好。
* ``senaite.core.i18n.translate`` 会先 ``safe_unicode(msgid)``，把 Message 自带的
  domain 丢掉，然后固定按 "senaite.core" 域查；所以这里直接调 zope.i18n，
  显式带上本包域，避免依赖 senaite 的实现细节。
"""

from zope.i18n import translate as _ztranslate

from maitux.stock import stockMessageFactory as _


# 目录里查不到时的兜底语言顺序（先按当前语言，再中文，最后英文）
FALLBACK_LANGUAGES = ("maitux.stock", )


def to_unicode(value):
    """任意值 -> unicode（py2 的 str 按 utf-8 解）。"""
    if value is None:
        return u""
    if isinstance(value, unicode):  # noqa: F821
        return value
    try:
        return value.decode("utf-8")
    except AttributeError:
        return u"{}".format(value)
    except Exception:
        try:
            return unicode(value)  # noqa: F821
        except Exception:
            return u""


def translate_stock(msgid, default=None, context=None):
    """按当前请求语言翻译 ``msgid``。

    :param msgid: 英文原文（同时就是目录里的 msgid）
    :param default: 目录里查不到、且 msgid 也不是可用文案时的兜底值
    :param context: 翻译上下文（默认取当前请求，用于确定目标语言）
    :returns: unicode 文案
    """
    if msgid is None:
        return to_unicode(default)
    request = context
    if request is None:
        try:
            from bika.lims import api
            request = api.get_request()
        except Exception:
            request = None
    try:
        translated = _ztranslate(msgid, domain="maitux.stock", context=request)
    except Exception:
        translated = None
    translated = to_unicode(translated)
    if translated and translated != to_unicode(msgid):
        return translated
    # 没命中目录：优先返回 default，否则原样返回英文 msgid
    if default is not None:
        return to_unicode(default)
    return translated or to_unicode(msgid)


def message(msgid, default=None):
    """构造本包域的 Message（用于需要把 domain 跟着数据走的场景，例如标题）。"""
    if default is None:
        return _(msgid)
    return _(msgid, default=default)
