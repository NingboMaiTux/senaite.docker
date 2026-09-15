# -*- coding: utf-8 -*-
from zope.publisher.interfaces.browser import IDefaultBrowserLayer


class IAutoReceiveLayer(IDefaultBrowserLayer):
    """INNOCARE.autoreceive 浏览器层。

    本层同时承担两个职责：

    1. 门控 schema 扩展（Client 的 AutoReceive 字段、AR 的 ReceivedByName
       字段只在装了本 addon 的站点生效）；
    2. 门控运行时注入（样品列表的「接收人」列，见 ``adapters.py``）。

    `package-includes/` 里的 slug 是全局加载的 —— 不判本层的注册会泄漏到
    本机所有站点（含从未装过本 addon 的站点），参见 R14。
    """
