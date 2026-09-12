=============
maitux.oauth2
=============

竹云 (Bamboocloud) IDaaS 的 **OAuth 2.0 标准授权码模式** 统一登录插件，用于
SENAITE 2.7 / Plone 5.2 / Python 2.7。

与 ``senaite.oidc`` 的区别：那个插件依赖 ``ftw.oidcauth``，走的是 OIDC
(id_token / discovery / JWKS)。本插件只用纯 OAuth 2.0 接口，不需要 id_token，
也不引入任何新的第三方依赖（HTTP 调用基于标准库）。

功能
====

* **场景 1** —— 用户在竹云 Portal 点击 LIMS 图标，竹云带 ``code`` 直接回调
  ``/@@oauth2-callback``。
* **场景 2** —— 用户直接访问 LIMS，未登录时被送到竹云授权页，认证后带
  ``code`` + ``state`` 回调。
* 用授权码换 ``access_token``（Basic 认证 + 表单提交），再调 ``userinfo``
  取用户身份。
* ``state`` 用 HMAC 签名的 http-only Cookie 校验，防 CSRF；不依赖 Zope
  session（RelStorage 环境下不可靠）。
* 账号路由：

  * 已存在且已授权 → 建立本地会话，进入 LIMS
  * 已存在但已停用 → ``/@@oauth2-disabled``（账号已被禁用）
  * 不存在 → 自动建号并放入“待授权”组 → ``/@@oauth2-pending``
    （待管理员分配权限）

* **每天一次的用户同步**：向竹云要一次“谁被授权访问本应用”的名单，据此
  提前建号、恢复误停用的账号、并把离职或被取消授权的人在 LIMS 里停用
  （解决“员工离职、客户不提供通知接口”的问题）。管理员永不被停用。
* **电子签名的账号/密码二次验证**：给 ``maitux.esignature`` 注册一个走竹云的
  认证后端。统一登录之后本地账号的密码是随机生成的、没人见过，本地校验那条路
  是死的，所以签名复核只能回竹云去问。带账号锁定防护——竹云是公司统一登录，
  连续输错会把人锁在**所有**公司系统之外。见 `INSTALL.md <INSTALL.md>`_ 第 9 节。
* 退出时可同时调用竹云全局退出接口。
* 管理员逃生出口：``/@@oauth2-local-login`` 始终可以打开本地登录表单。

安装与配置
==========

见 `INSTALL.md <INSTALL.md>`_。

测试
====

同步逻辑的测试不需要 Plone、不需要网络、不需要竹云账号，用 Python 2.7 直接跑::

    python src/maitux/oauth2/tests.py
    python src/maitux/oauth2/tests.py -v
    python src/maitux/oauth2/tests.py AdminProtectionTests

它用假对象顶掉 ``plone.api`` / ``Products.CMFCore``，加载**真实的** ``users.py`` /
``sync.py`` / ``client.py`` / ``httputils.py`` / ``reauth.py`` 来跑。53 个用例覆盖：

- 每日同步：建号、停用、恢复还原用户组、管理员保护、三道安全保护、dry run
- 电子签名二次验证：密码校验、竹云各种返回状态、身份核对、账号锁定防护、
  请求头是否带全、本地账号名到竹云登录名的映射

只有最外层的网络调用（``httputils.request_json``）被换成假的，所以拼请求头、
拼 body、解析错误码这些代码跑的都是真的——「设备信息请求头有没有带全」这种事
只有这样才测得到。真实竹云环境的连通性由仓库根目录的 ``zhuyun-api-test`` 验证。

⚠️ 不要在 Zope 进程里跑（``bin/instance run`` 之类）：往 ``sys.modules`` 里塞假的
``plone.api`` 会把正在服务的站点搞坏。检测到那种情况测试会直接拒绝运行。

用到的竹云接口
==============

======================================================  ====================================
接口                                                     用途
======================================================  ====================================
``GET  /api/v1/oauth2/authorize``                        获取标准授权码
``POST /api/v1/oauth2/token``                            授权码换 access_token
``GET  /api/v1/oauth2/userinfo``                         获取用户身份
``POST /api/v1/oauth2/introspect``                       检查 token 有效性（预留）
``GET  /api/v1/logout``                                  全局退出
``POST /api/v2/tenant/token``                            EIAM 鉴权 (client_credentials)
``GET  /api/v2/tenant/applications/{app_id}/accounts``   谁被授权访问本应用（每日同步第一步）
``POST /api/v2/tenant/users/user-by-username``           取单个用户详情（每日同步第二步）
``POST /api/v2/sdk/login``                               电子签名的账号/密码二次验证
======================================================  ====================================

刻意**不使用** ``GET /api/v2/tenant/users``（租户级用户列表）：它没有应用维度的
过滤条件，一次会返回全租户几千条员工档案（含证件号、手机号），而实际有权访问
LIMS 的只有几十人。

文档：https://docs.bccastle.com/
（旧站 https://open.bccastle.com/development/ 没有应用账号那组接口）
