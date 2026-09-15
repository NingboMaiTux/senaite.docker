# -*- coding: utf-8 -*-
from zope.interface import Interface
from zope.publisher.interfaces.browser import IDefaultBrowserLayer


class ILabIDLayer(IDefaultBrowserLayer):
    """本 add-on 的浏览器层。

    default profile 的 browserlayer.xml 安装后把它注册到站点上；Laboratory
    的 behavior 适配器据此做运行时门控：没装本 add-on 的站点看不到 Lab ID
    字段（见 R14：指向外来内容接口、且签名里没有 request 的 adapter，
    只能在工厂里做运行时门控）。
    """


class ILabIDMarker(Interface):
    """Lab ID behavior 的 marker。

    plone:behavior 传了 factory 时 marker 为必需项，且不能与 provides 相同。
    本 add-on 不依赖"对象提供该 marker"来判断启用与否 —— 启用与否由
    LabIDBehaviorAssignable 决定。
    """
