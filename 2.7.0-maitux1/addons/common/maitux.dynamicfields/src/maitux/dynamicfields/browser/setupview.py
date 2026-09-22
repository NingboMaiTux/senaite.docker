# -*- coding: utf-8 -*-
"""在 SENAITE 的 Setup 页（``@@lims-setup``）上加一块「动态字段」磁贴

为什么非得覆盖视图
------------------
先试过三条更轻的路，都堵死：

1. **viewlet**：本包原来挂了一个 ``plone.abovecontent`` 的 viewlet。但
   ``@@lims-setup`` 用的是 ``prefs_main_template.pt``，那个模板里**一个
   viewlet manager 都没有** —— 任何 viewlet 在这页都渲染不出来。（那个
   viewlet 只在直接打开 ``/bika_setup`` 对象时才出现，而没人那么走。）
2. **建内容对象**：``SetupView.setupitems()`` 返回的是 ``setup`` /
   ``bika_setup`` 容器里的真实内容对象。要加磁贴就得建对象、写数据库，
   本包的设计是不写。
3. **z3c.jbot 换模板**：这个环境没装。

所以只剩「继承 SetupView，多塞一项」。

覆盖的代价，和为什么可以接受
----------------------------
``overrides.zcml`` 里重注册 ``lims-setup`` 是**全局**替换 senaite.core 的
那条注册。代价是：SENAITE 升级时如果 SetupView 变了，这里可能跟着坏。

控制住的办法是只继承、不抄模板 —— 本类除了 ``setupitems()`` 追加一项，
以及把 ``get_icon_for()`` / ``get_count()`` 里自己那一项拦下来之外，什么
都不碰。``setupitems()`` 还包了兜底：出任何岔子就退回父类的结果，
**宁可少一块磁贴，不能让整个 Setup 页打不开**。

但兜底只管得着 ``setupitems()``。模板渲染阶段对每一项调的方法一旦漏处理
一个，父类照样会抛、整页 500 —— 2026-09-22 漏了 ``get_count`` 就是这么炸
的。所以「模板对每一项调了哪几个方法」必须是**数出来的**，smoke_test
第 16 节直接读 senaite.core 那份 .pt 抓调用逐个验，顺带当 SENAITE 升级的
哨兵：官方模板哪天多调一个方法，测试立刻红，而不是等线上 500。

权限沿用原注册的 ``senaite.core.permissions.ManageBika``，不能换成本包
别处用的 ``cmf.ManagePortal`` —— 那会把整个 Setup 页从 LabManager /
LabClerk 手里收走，为了加个入口把人家的页面弄没了。
"""

from senaite.core.browser.controlpanel.setupview import SetupView

try:                                        # pragma: no cover
    from bika.lims import api
except ImportError:                         # pragma: no cover
    api = None

try:                                        # pragma: no cover
    from AccessControl import getSecurityManager
    from Products.CMFCore.permissions import ManagePortal
except ImportError:                         # pragma: no cover
    getSecurityManager = None
    ManagePortal = "Manage portal"

from maitux.dynamicfields import _


#: 磁贴上的字。用动宾短语而不是「动态字段管理」：Setup 页上一屏几十块
#: 磁贴，实施人员是带着「我要加个字段」的念头来找的，不是来找一个模块名。
TILE_TITLE = _(u"tile_add_fields", default=u"Add Fields")

#: 排序用：磁贴按标题排，这一项不参与，直接追加在最后
VIEW_NAME = "dynamic-fields"


class _Tile(object):
    """假装成一个内容对象，提供模板对每一项要的东西

    ``setupview.pt`` 对循环里的每一项一共用四样：

    - ``item/absolute_url``、``item/Title``      -> 本类提供
    - ``view.get_icon_for(item)``、``view.get_count(item)``
                                                 -> 下面的子类拦下来

    这四样是**从模板里数出来的**，不是凭印象。smoke_test 第 16 节会去读
    senaite.core 那份 .pt 把调用抓出来逐个验 —— 2026-09-22 就是凭印象只
    数了三样，漏掉 get_count，线上整个 Setup 页 500。
    """

    portal_type = "MaituxDynamicFieldsTile"

    def __init__(self, url, title):
        self._url = url
        self._title = title

    def absolute_url(self):
        return self._url

    def Title(self):
        return self._title


class DynamicFieldsSetupView(SetupView):
    """Setup 页 + 一块「动态字段」磁贴"""

    def can_manage(self):
        """当前用户能不能真的打开 @@dynamic-fields

        ★ 磁贴必须按**目标页**的权限渲染，不是按 Setup 页的。两者不一样：

          Setup 页        senaite.core: Manage Bika
                          -> LabClerk / LabManager / Manager
                             （senaite.core rolemap.xml:673）
          @@dynamic-fields  cmf.ManagePortal
                          -> 只有 Manager / Site Administrator

        不判的话，LabClerk 和 LabManager 会看见「添加字段」、点进去吃一个
        Insufficient Privileges —— 给人一个点不开的入口比不给还糟。
        """
        if getSecurityManager is None:
            return False
        try:
            context = api.get_portal() if api is not None else self.context
            return bool(
                getSecurityManager().checkPermission(ManagePortal, context))
        except Exception:
            # 判不出来就当没有。宁可少一块磁贴，不能给出点不开的入口。
            return False

    def _tile(self):
        if api is None:
            return None
        if not self.can_manage():
            return None
        try:
            base = api.get_url(api.get_portal())
        except Exception:
            return None
        return _Tile("%s/@@%s" % (base, VIEW_NAME), TILE_TITLE)

    def setupitems(self):
        items = SetupView.setupitems(self)
        try:
            tile = self._tile()
        except Exception:
            return items
        if tile is None:
            return items
        # 追加在最后：父类是按标题排序的，把一个 Message 混进 cmp 里排序
        # 反而可能炸。少一个排序位置换一份稳。
        return list(items) + [tile]

    def get_icon_for(self, brain, **kw):
        """自己那一项给个内置图标，其余照旧交给父类

        父类走的是 bootstrapview，按 portal_type 查图标注册表；本项的
        portal_type 是假的，查不到会抛，所以必须自己拦下来。
        """
        if isinstance(brain, _Tile):
            css = kw.get("css_class", "icon")
            # 用 senaite.core 自己在用的资源目录（bika/lims/browser/images/
            # 通过 ++resource++bika.lims.images 发布），不自带图片：本包
            # 没有 profile，塞一份自己的静态资源反而多一条要维护的路。
            return (u'<img class="%s" src="%s/++resource++bika.lims.images/'
                    u'gears.png" />' % (css, self._portal_url()))
        return SetupView.get_icon_for(self, brain, **kw)

    def get_count(self, obj):
        """自己那一项没有「里面有几条」可言，返回 0（模板据此不渲染计数）

        ★ 2026-09-22 线上炸在这儿：只看了模板前 50 行，以为每项只调
          absolute_url / Title / get_icon_for 三样，漏了第 73 行的
          get_count(item)。父类的 get_count 会走
          api.get_portal_type(obj) -> APIError，整个 Setup 页 500。

          教训：覆盖别人的视图时，要把**整个模板**里对每一项的调用列全，
          不能读一半就动手。下面 smoke_test 第 16 节加了一条：从
          senaite.core 的 setupview.pt 里正则抓出所有 view.xxx(item)
          调用，逐个断言本类有对应处理 —— 这类遗漏不该靠人眼。
        """
        if isinstance(obj, _Tile):
            return 0
        return SetupView.get_count(self, obj)

    def _portal_url(self):
        if api is None:
            return u""
        try:
            return api.get_url(api.get_portal())
        except Exception:
            return u""
