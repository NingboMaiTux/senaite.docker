senaite.smartsearch — 智慧搜索
================================

在权限范围内一键搜索全部 SENAITE LIMS 数据。作为真正的 SENAITE 插件运行，
不是外部工具——装上之后直接用当前登录用户的身份和权限去查。

.. note::
   代码针对 **Python 2.7.18** 校验过：所有含中文的源文件都声明了
   ``# -*- coding: utf-8 -*-``（Python 2 下缺这个会直接 SyntaxError），
   ``search.py`` 加了 ``from __future__ import division`` 防止整数除法踩坑。
   这个包本身没有第三方依赖（只用 SENAITE/Zope 自带的 ``bika.lims.api`` 和
   ``AccessControl``），不存在依赖版本兼容问题。

关于"权限范围内"
-----------------

这是这个插件的核心保证，做了两层：

1. **目录本身的安全过滤**：``portal_catalog`` 是 CMF 的 CatalogTool，它的
   ``searchResults()`` 会按当前登录用户的 ``allowedRolesAndUsers`` 索引自动过滤——
   这是 SENAITE/Plone 的标准行为。比如客户联系人账号默认就只能查到自己
   Client 下的样品，这一层不用额外做什么，是平台自带的。

2. **显式权限二次校验**：不是所有目录都严格维护了安全索引（比如检测结果
   专用的 Analysis 目录，不一定索引 allowedRolesAndUsers）。所以
   ``search.py`` 里对每一条候选结果，都额外用
   ``getSecurityManager().checkPermission('View', obj)`` 显式确认了一遍，
   两层叠加，确保不会因为某个目录的索引配置疏漏而泄露用户本不该看到的记录。

代价是第 2 层需要把对象唤醒出来检查，比纯目录查询慢一些；代码里用
"先多取一批候选、过滤后再截断"的方式控制了这个开销（默认按最终结果数的
3 倍取候选集，可以在 ``search.py`` 的 ``OVERFETCH_MULTIPLIER`` 调整）。

搜索范围
--------

跨这些业务对象类型统一搜索：样品、批次、客户、联系人、仪器、检测项目、
检测结果、样品类型、采样点、方法、工作单、供应商、产品、实验室联系人、部门。

如果你们有自定义内容类型，把它的 portal_type 加进 ``search.py`` 里的
``PORTAL_CATALOG_TYPES`` 列表就会被搜索到。

安装
----

1. 把这个包放进 SENAITE 能加载到的 Python 环境::

       pip install -e /path/to/senaite.smartsearch

   或加进 buildout.cfg 的 eggs / develop，重新跑 bin/buildout。

2. 重启 Zope/SENAITE 实例。

3. 管理员登录后进入 **Site Setup → Add-ons**，找到"SENAITE 智慧搜索"，点击 Activate。

4. 装好之后：
   - 页头会出现一个搜索框，输入两个字开始实时下拉结果
   - 导航栏会多一个"智慧搜索"标签，点进去是完整搜索页 ``@@smartsearch``
   - JSON 接口在 ``@@smartsearch-api?q=关键词``，可以直接在浏览器里试

先验证一下
----------

用两个不同权限的账号分别登录试搜索，确认：

- 管理员账号：能搜到全部机构范围内的样品/批次/客户等
- 某个 Client 联系人账号：只能搜到自己 Client 名下的样品，搜别的客户的样品编号
  应该搜不到

如果客户账号搜到了不该看到的记录，说明你们某个内容类型的权限模型跟标准
SENAITE 不一样，需要检查该对象上的本地角色（local roles）设置，而不是这个
插件的搜索逻辑本身——插件只是如实按 ``checkPermission`` 的结果过滤。

关于 catalog id 的适配
-----------------------

``search.py`` 顶部的 ``ANALYSIS_CATALOG_CANDIDATES`` 是"依次尝试"的候选列表，
不同 SENAITE 版本 catalog id 可能不一样。如果检测结果搜不到，去 ZMI 里确认
真实的 catalog id，加进候选列表即可，不需要改其他代码。
