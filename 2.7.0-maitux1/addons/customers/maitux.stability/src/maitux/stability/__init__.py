# -*- coding: utf-8 -*-
from zope.i18nmessageid import MessageFactory


stabilityMessageFactory = MessageFactory("maitux.stability")

# 中文注释：`_` 必须在导入子模块之前就绪，否则 `from maitux.stability import _`
# 会因为循环导入失败（与 maitux.stock 同样的约定）。
_ = stabilityMessageFactory

# 自带的 i18n 兜底：模块导入即安装（见 i18n_fallback.py 末尾的 install()）
import maitux.stability.i18n_fallback  # noqa: E402,F401


def initialize(context):
    """Initializer called when used as a Zope 2 product."""
    from maitux.stability import content
    content.initialize(context)
