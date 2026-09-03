from zope.i18nmessageid import MessageFactory


stabilityMessageFactory = MessageFactory("maitux.stability")
_ = stabilityMessageFactory

# 自包含翻译回退：保证侧边栏/菜单文件夹标题（纯字符串）在 senaite.core
# 域未命中时，总是额外查询 maitux.stability 域，不依赖 INNOCARE.arextension
# 附加域补丁列表是否已包含本 addon。
from maitux.stability import i18n_fallback  # noqa: F401,E402


def initialize(context):
    """Initializer called when used as a Zope 2 product."""
    from maitux.stability import content
    content.initialize(context)

