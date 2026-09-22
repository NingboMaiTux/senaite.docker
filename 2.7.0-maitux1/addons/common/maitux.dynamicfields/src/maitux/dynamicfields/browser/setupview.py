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

控制住的办法是只继承、不抄模板 —— 本类除了 ``setupitems()`` 追加一项、
``get_icon_for()`` 认一下自己那一项之外，什么都不碰。而且两个方法都包了
兜底：出任何岔子就退回父类的结果，**宁可少一块磁贴，不能让整个 Setup 页
打不开**。

权限沿用原注册的 ``senaite.core.permissions.ManageBika``，不能换成本包
别处用的 ``cmf.ManagePortal`` —— 那会把整个 Setup 页从 LabManager /
LabClerk 手里收走，为了加个入口把人家的页面弄没了。
"""

from senaite.core.browser.controlpanel.setupview import SetupView

try:                                        # pragma: no cover
    from bika.lims import api
except ImportError:                         # pragma: no cover
    api = None

from maitux.dynamicfields import _


#: 磁贴上的字。用动宾短语而不是「动态字段管理」：Setup 页上一屏几十块
#: 磁贴，实施人员是带着「我要加个字段」的念头来找的，不是来找一个模块名。
TILE_TITLE = _(u"tile_add_fields", default=u"Add Fields")

#: 排序用：磁贴按标题排，这一项不参与，直接追加在最后
VIEW_NAME = "dynamic-fields"


class _Tile(object):
    """假装成一个内容对象，只提供模板要的那三样

    模板对每一项只调 ``item/absolute_url``、``item/Title`` 和
    ``view.get_icon_for(item)``。不需要真对象。
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

    def _tile(self):
        if api is None:
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

    def _portal_url(self):
        if api is None:
            return u""
        try:
            return api.get_url(api.get_portal())
        except Exception:
            return u""
