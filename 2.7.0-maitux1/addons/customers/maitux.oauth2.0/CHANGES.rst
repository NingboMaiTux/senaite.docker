Changelog
=========

0.1.0 (unreleased)
------------------

- 首个版本：竹云 IDaaS OAuth 2.0 标准授权码模式统一登录，
  含首次登录建号（待授权）、停用拦截、以及每日 EIAM 用户同步。

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
