Changelog
=========

0.1.0 (unreleased)
------------------

- 首个版本：竹云 IDaaS OAuth 2.0 标准授权码模式统一登录，
  含首次登录建号（待授权）、停用拦截、以及每日 EIAM 用户同步。

- 新增电子签名的账号/密码二次验证：注册一个走竹云的 ``IReAuthenticationProvider``
  （backend_id ``bccastle``），在电子签名控制面板的“认证后端”里选“竹云统一登录”
  即可生效。统一登录之后本地账号的密码是建号时随机生成的、没有任何人见过，
  ``maitux.esignature`` 自带的本地 PAS 校验从此校验不了任何东西。

  走 ``POST /api/v2/sdk/login``（请求头 ``X-client-id`` 认证，用现有 ClientId，
  不需额外开通）。标准 OAuth2 密码模式本租户实测被拒：
  ``Unauthorized grant type: password``。
  三个设备信息请求头是必填的，只带 ``X-client-id`` 会收到
  ``SDK.COMMON.1003 设备信息不完整``。

  **带账号锁定防护。** 竹云是公司统一登录，密码连错会锁定账号，锁的是该员工
  所有公司系统——而签名是高频操作，手滑很正常。两道防护：本地连错 N 次进入冷却
  （不再发请求），以及竹云自己返回的“剩余登录尝试次数”降到保护线时立即停手。
  剩余次数会原样提示给签名的人。

  验证通过后会解开 ``id_token``（两层：JWT payload → ``api`` 字符串 → ``userName``）
  核对身份，对不上就拒绝——签名归错人是审计追溯最致命的错误。

  新增 member 属性 ``maitux_oauth2_username`` 记录竹云登录名：本地用户名是
  ``normalize_username`` 推导出来的，反推不回去。老账号退回“去掉前缀”。

- 新增 ``tests.py``：53 个用例覆盖同步与电子签名二次验证，不需要 Plone、网络或竹云账号。
  用假对象顶掉 ``plone.api`` / ``Products.CMFCore``，加载真实的 ``users.py`` 和
  ``sync.py`` 来跑。``python src/maitux/oauth2/tests.py`` 即可。
  检测到在 Zope 进程里运行会直接拒绝——替换活站点的 ``plone.api`` 会出事。

- 每日同步改为按**应用授权名单**进行，不再拉取租户级用户列表。
  ``GET /api/v2/tenant/users`` 只有 ``org_id`` / ``updated_at_greater`` 两个
  过滤条件，拿不到应用维度，实测一次返回 2717 条全公司员工档案（含身份证号、
  手机号），而被授权访问 LIMS 的只有 22 人。现在先调
  ``GET /api/v2/tenant/applications/{app_id}/accounts`` 拿名单，再对名单里的
  每个人调 ``POST /api/v2/tenant/users/user-by-username`` 取详情——
  23 次请求、22 条记录，其余 2695 人的个人信息不再落到本地。
  （GS profile 2 → 3）

- 新增“为名单里的人提前建号”：竹云里被授权但还没登录过的人，同步时就把本地账号
  建好（同样是“待授权”状态），管理员可以提前分配权限，不必等对方先登录一次。
  由 ``sync_create_missing`` 控制，默认开启。

- 修复“恢复账号”其实恢复不了：``disable_user`` 会把用户移出所有用户组，而
  ``enable_user`` 只清停用标记、不还原用户组，结果“恢复”等于“能登录但什么都
  干不了”，人直接退回待授权状态。现在停用时把摘掉的组名记在
  ``maitux_oauth2_revoked_groups`` 上，恢复时原样加回去；组若已被删除则只报告、
  不重建。

- 管理员永不被同步停用。竹云的应用授权名单是给实验室人员的，管理员通常不在名单
  上，照着名单停用会在第一晚把管理员自己锁在门外——而且用户组全被摘掉之后，网页
  上就没人能改回来。持有 ``Manager`` / ``Site Administrator`` 的账号现在直接跳过，
  且之前若被误停用会自动恢复；只通过用户组间接拿到管理角色的人可以补进新增的
  ``sync_protected_users``。

- 修复 ``logout`` 覆盖从未生效：CMFPlone 把它注册在 ``INavigationRoot`` 上，
  多适配器查找先比 context 再比 request，``for="*"`` 加浏览层也赢不过。
  于是「退出时同时注销竹云会话」和 state Cookie 清理一直是死代码。

- 修复退出后的落地页是 404：Plone 的视图名叫 ``logged-out``（连字符），
  不是 ``logged_out``。同时按 CMFPlone 的做法支持 ``next`` 参数。
