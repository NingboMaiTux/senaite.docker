# -*- coding: utf-8 -*-
"""浏览器层定义

本包的 ZCML 一旦被 `package-includes/` 收录就是**全局加载**的，跟
profile 装没装、跟哪个站点毫不相干。所以凡是注册到 senaite.core 内容接口
上的东西都必须门控到本包的 layer 上（开发规则 R14）——
`browser/configure.zcml` 里的编辑表单适配器就是这么做的。
"""

from senaite.core.interfaces import ISenaiteCore
from zope.publisher.interfaces.browser import IBrowserRequest


class IGlobalAuditLogLayer(ISenaiteCore, IBrowserRequest):
    """全局审计日志强制开启 —— 浏览器层

    ★ 两个基类都是承重的，不是随手写的。

    **为什么要继承 `IBrowserRequest`**（本包能不能生效的关键）：

    core 的设置表单适配器注册在

        for="senaite.core.interfaces.ISetup
             zope.publisher.interfaces.browser.IBrowserRequest"

    上；本包注册在 `(ISetup, IGlobalAuditLogLayer)` 上。两对 required
    不是同一个 discriminator，所以走 include **不会**
    `ConfigurationConflictError`（R5 不触发），代价是同一个请求上
    **两条注册都匹配**，由 Zope 挑「更具体」的那条。

    本包这一对要严格更具体，就必须让请求槽上的接口是 core 那个
    `IBrowserRequest` 的**真子接口** —— 所以这里直接继承它。
    反例：只写 `class IGlobalAuditLogLayer(ISenaiteCore)`
    （`ISenaiteCore` 与 `IBrowserRequest` 互不为子接口），谁被选中就变成
    实现细节；一旦没选中，`FormView.adapter` 是 `None`，
    `initialized()` 直接 `return {}` —— **页面照常打开、什么也不发生、
    日志里一个字都没有**，正是 R9 说的静默失效。

    这一步在本环境有现成的同类先例（同一机制、已在生产跑通）：
    `bika.lims` 把 `@@auditlog` 注册在 `layer="IBikaLIMS"` 上，
    `maitux.audittrail` 用 `IAuditTrailLayer(ISenaiteCore, IBikaLIMS)`
    覆盖它 —— 同样靠「请求槽上的接口是对方的子接口」取胜。
    视图与适配器在 Zope 里走的是同一套 `queryMultiAdapter` 解析。

    **为什么要继承 `ISenaiteCore`**：让本层自足。设置页发出的
    `ajax_form/initialized` 请求打到挂在 `ISenaiteCore` 层上的页面，
    本层带上它就与站点是否另外注册过该层无关。

    没装本 profile 的站点，请求上不带这个层，core 那条照旧命中，
    设置页面**与原生完全一致**（R14 要的「不泄漏」）。
    """
