# -*- coding: utf-8 -*-
#
# maitux.glossary - 常量
#
# 命名对照（与 结构定稿.md 的表格列一一对应）：
#   Analysis category  -> category
#   Analysis Service   -> service_title（只读，取自站点，不入库）
#   Analysis Keyword   -> analysis_keyword
#   calc keyword       -> calc_keyword
#   zh                 -> zh（人工填写，**默认为空**）
#   en                 -> en（人工填写，**默认为空**）
#   状态（活跃/未激活） -> sync_state（同步维护）

PROJECTNAME = "maitux.glossary"
PROFILE_ID = "profile-%s:default" % PROJECTNAME

# 中间表容器：放在 **portal.setup 里**（不再放站点根目录）。
# 依据 senaite.core/browser/controlpanel/setupview.py 的 setupitems()：
#     items = self.setup.objectValues() + self.bika_setup.objectValues()
# 即放进 setup 文件夹的内容对象会**自动**出现在 Setup 菜单里，
# 不需要（也因此不再使用）BikaSetup 的 sidebar folders 配置。
FOLDER_ID = "keyword_glossary"
CONTAINER_TYPE = "GlossaryEntries"
ENTRY_TYPE = "GlossaryEntry"

#: 容器所在的 setup 文件夹 id（portal.setup，portal_type = "Setup"）。
#: v1 曾把容器建在站点根目录，所以定位时**两个位置都要找**，setup 里的优先。
SETUP_FOLDER_ID = "setup"

# 容器默认视图名（= listing 注册名）
LISTING_VIEW_NAME = "glossary-listing"
# 手动刷新（重新与站点对账）的视图名；列表页工具栏的「刷新」按钮指向它
SYNC_VIEW_NAME = "glossary-sync"

# 列表页标题图标（必须是 senaite.core 主题里真实存在的图标名，
# 否则 ListingTableTitleViewlet 的 icon 解析会失败并报 LocationError）
LISTING_ICON = "senaite_theme/icon/setup"
REFRESH_ICON = "senaite_theme/icon/retest"

# 同步状态：该组合在站点上还在不在。**同步唯一会改的字段**。
STATE_ACTIVE = u"active"
STATE_INACTIVE = u"inactive"
SYNC_STATES = (STATE_ACTIVE, STATE_INACTIVE)

# 可人工编辑的列（listing 里以输入框呈现）。
# 两个字段**默认为空**，由人工填写；不参与同步回填。
EDITABLE_FIELDS = (u"zh", u"en")

# 同步首次写入、之后不再改动的字段
SEEDED_FIELDS = (u"analysis_keyword", u"calc_keyword", u"category")

# 日志前缀：可 grep 的可观测信号（规则 R9）
LOG_PREFIX = "sync"

# 对账报告里最多打印几条样例，避免刷屏
MAX_SAMPLES = 10

# 确定性 ID：<slug>-<md5 前 8 位>
ID_SLUG_MAX = 32
ID_HASH_LEN = 8
