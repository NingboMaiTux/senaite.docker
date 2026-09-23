# -*- coding: utf-8 -*-
"""maitux.stability 的翻译助手（与 maitux.stock.i18n 同一套路）。

约定：**界面文案在代码/模板里一律写英文 msgid**，译文放在
``locales/<lang>/LC_MESSAGES/maitux.stability.po``：

* 英文站 -> ``locales/en`` 的同义条目（msgid == msgstr）
* 中文站 -> ``locales/zh*`` 的中文

SENAITE 列表的标题/列名/页签是 Python 里拼进 JSON 的，渲染阶段不会再翻译，
所以必须在这里（构造视图时）就翻译好。
"""

from zope.i18n import translate as _ztranslate

from maitux.stability import stabilityMessageFactory as _

DOMAIN = "maitux.stability"


def to_unicode(value):
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


def translate_stability(msgid, default=None, context=None):
    """按当前请求语言翻译 ``msgid``（英文原文即 msgid）。"""
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
        translated = _ztranslate(msgid, domain=DOMAIN, context=request)
    except Exception:
        translated = None
    translated = to_unicode(translated)
    if translated and translated != to_unicode(msgid):
        return translated
    if default is not None:
        return to_unicode(default)
    return translated or to_unicode(msgid)


def message(msgid, default=None):
    """构造本包域的 Message（需要 domain 跟着数据走时使用）。"""
    if default is None:
        return _(msgid)
    return _(msgid, default=default)
