# -*- coding: utf-8 -*-
"""maitux.stability 自包含的翻译回退钩子。

SENAITE 侧边栏/菜单渲染文件夹标题时调用 ``senaite.core.i18n.translate``，
默认只按 "senaite.core" 域查询。纯字符串标题未命中时，INNOCARE.arextension
的补丁会按 ``_EXTRA_TRANSLATION_DOMAINS`` 附加域回退翻译。为避免依赖
arextension 补丁列表是否已包含本 addon 域，这里链式包装该 translate，
保证 ``maitux.stability`` 域总是被额外查询（对其它附加域/Message 行为无影响）。
"""
from zope.i18n import translate as _ztranslate
from zope.i18nmessageid import Message

from bika.lims import api as _bika_api

_DOMAIN = "maitux.stability"


def install():
    try:
        import senaite.core.i18n as _senaite_i18n
    except Exception:
        return
    original = getattr(_senaite_i18n, "translate", None)
    if original is None or getattr(original, "_maitux_stability_i18n", False):
        return

    def translate(msgid, to_utf8=True, **kwargs):
        result = original(msgid, to_utf8=to_utf8, **kwargs)
        # Message 对象自带 domain，走原生逻辑；仅对纯字符串未命中做附加回退
        if not isinstance(msgid, Message) and result == msgid:
            # 原生 str 含非 ASCII 时 zope.i18n 按 ascii 解码会抛错，直接返回
            if isinstance(msgid, str):
                try:
                    msgid.decode("ascii")
                except UnicodeDecodeError:
                    return result
            context = kwargs.get("context") or _bika_api.get_request()
            try:
                translated = _ztranslate(
                    msgid, domain=_DOMAIN, context=context)
            except Exception:
                # 附加域查找异常不得影响主流程
                translated = msgid
            if translated != msgid:
                return _bika_api.to_utf8(translated) if to_utf8 else translated
        return result

    translate._maitux_stability_i18n = True
    _senaite_i18n.translate = translate

    # 若 sidebar 模块已加载旧引用，同步替换
    try:
        import senaite.core.browser.viewlets.sidebar as _sidebar_mod
        _sidebar_mod.translate = translate
    except Exception:
        pass


install()
