# -*- coding: utf-8 -*-
from zope.i18nmessageid import MessageFactory

stockMessageFactory = MessageFactory('maitux.stock')

# 中文注释：包内其它模块（browser/__init__.py）会 `from maitux.stock import _`，
# 而下面的 patches 又会在导入期反向导入 browser，两者构成循环导入；
# 因此 `_` 必须在导入 patches 之前就绪，否则 Zope 启动直接失败
# （ImportError: cannot import name _）。
_ = stockMessageFactory

# 自带的 i18n 兜底：模块导入即安装（见 i18n_fallback.py 末尾的 install()）
import maitux.stock.i18n_fallback  # noqa: E402,F401

from maitux.stock.patches import patch_allowed_transitions_for_many  # noqa: E402
from maitux.stock.patches import patch_auditlog_searchable_text_unicode  # noqa: E402

patch_allowed_transitions_for_many()
patch_auditlog_searchable_text_unicode()


def initialize(context):
    """Initializer called when used as a Zope 2 product."""
    from maitux.stock import content
    content.initialize(context)
