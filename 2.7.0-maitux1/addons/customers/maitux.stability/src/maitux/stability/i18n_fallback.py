# -*- coding: utf-8 -*-
"""maitux.stability 自包含的翻译回退钩子。

背景：SENAITE 侧边栏/菜单渲染文件夹标题时调用 ``senaite.core.i18n.translate``，
它固定按 "senaite.core" 域查询。我们的标题是**英文 msgid 纯字符串**，
在 senaite.core 目录里查不到，于是原样返回 —— 英文站正常，中文站也显示英文。

这里链式包装该 translate：只在"纯字符串且未命中"时，额外按本包域再查一次。
对 Message 对象与其它附加域的行为没有任何影响（与 maitux.stock 的实现一致）。
"""
from zope.i18n import translate as _ztranslate
from zope.i18nmessageid import Message

from bika.lims import api as _bika_api

_DOMAIN = "maitux.stability"


def install():
    try:
        import logging
        logger = logging.getLogger(_DOMAIN)
        import senaite.core.i18n as _senaite_i18n
    except Exception:
        return
    original = getattr(_senaite_i18n, "translate", None)
    if original is None:
        return
    if getattr(original, "_maitux_stability_i18n", False):
        logger.info("i18n fallback for %s already installed", _DOMAIN)
        return

    def translate(msgid, to_utf8=True, **kwargs):
        result = original(msgid, to_utf8=to_utf8, **kwargs)
        if not isinstance(msgid, Message) and result == msgid:
            if isinstance(msgid, str):
                try:
                    msgid.decode("ascii")
                except UnicodeDecodeError:
                    return result
            context = kwargs.get("context") or _bika_api.get_request()
            try:
                translated = _ztranslate(msgid, domain=_DOMAIN, context=context)
            except Exception:
                translated = msgid
            if translated != msgid:
                return _bika_api.to_utf8(translated) if to_utf8 else translated
        return result

    translate._maitux_stability_i18n = True
    _senaite_i18n.translate = translate

    try:
        import senaite.core.browser.viewlets.sidebar as _sidebar_mod
        _sidebar_mod.translate = translate
    except Exception:
        pass

    logger.info("Installed self-contained i18n fallback for %s", _DOMAIN)


install()
