from zope.i18nmessageid import MessageFactory

stockMessageFactory = MessageFactory('maitux.stock')
_ = stockMessageFactory

# NOTE: define the message factory *before* importing patches.
# patches -> browser.stockbatchactions -> browser/__init__ imports
# `from maitux.stock import _`; importing it first would raise
# "cannot import name _".
from maitux.stock.patches import patch_allowed_transitions_for_many

patch_allowed_transitions_for_many()

# 自包含翻译回退：保证侧边栏/菜单文件夹标题（纯字符串）在 senaite.core
# 域未命中时，总是额外查询 maitux.stock 域，不依赖 INNOCARE.arextension
# 附加域补丁列表是否已包含本 addon。
from maitux.stock import i18n_fallback  # noqa: F401,E402

def initialize(context):
    """Initializer called when used as a Zope 2 product."""
    from maitux.stock import content
    content.initialize(context)

