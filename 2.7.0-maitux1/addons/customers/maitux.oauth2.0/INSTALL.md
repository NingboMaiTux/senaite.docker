# maitux.oauth2 安装与配置

> 下文的 `<站点id>` 指 SENAITE/Plone 站点对象的 id（例如 `lims`）。
> 一个实例可以有多个站点，id 不固定，请按实际情况替换。
> **插件代码本身不依赖站点 id** —— 所有 URL 都从 `api.portal.get().absolute_url()` 推导，只有下面这些靠外部配置（站点外的 nginx / clock-server / 竹云回调地址）的地方需要填它。

## 0. 名字说明

| 项 | 值 |
|---|---|
| 目录名 | `addons/customers/maitux.oauth2.0` |
| egg / 包名 | `maitux.oauth2` |
| Python 包 | `src/maitux/oauth2/` |
| GS profile | `maitux.oauth2:default` |

目录名带 `.0` 是按要求放置的；Python 包名不能出现 `2.0` 这种写法，所以 egg 名是
`maitux.oauth2`。buildout 里 `develop` 用目录名、`eggs` 用 egg 名。

## 1. buildout 接入

在 `addons/customers/custom-addon.cfg` 里需要三项：

```ini
[buildout]
develop +=
    /opt/addons/customers/maitux.oauth2.0
eggs +=
    maitux.oauth2
```

`develop` 让 buildout 认识源码目录（并生成 egg-info），`eggs` 把它加进 instance
的 sys.path。

`[instance] zcml += maitux.oauth2` **不是必须的**：本包在 `setup.py` 里带了
`[z3c.autoinclude.plugin] target = plone` 入口点，而运行时 buildout 会在**挂载目录
里**重新生成 egg-info（实测：宿主机上会出现 `src/maitux.oauth2.egg-info/`），
所以 autoinclude 能正常发现它。

反而走 `[instance] zcml` 有一个坑：`site.zcml` 处理 `package-includes/*-configure.zcml`
的时机在 `<five:loadProducts />` **之前**，那时 `Products.CMFCore` 还没注册
`cmf.ManagePortal`，控制面板页面会以
`ComponentLookupError: (IPermission, 'cmf.ManagePortal')` 让**整站起不来**。
本包已经在 `configure.zcml` 里显式 `<include package="Products.CMFCore"
file="permissions.zcml" />` 兜住了这一点，两种加载方式都安全 —— 但同目录其他插件
若在 ZCML 里引用了 CMF / senaite.core 的权限而没有这一行，就会踩这个坑。

**没有 `[plonesite] profiles` 这一项，是刻意的**：`buildout.cfg` 里写的是
`[plonesite] profiles = senaite.lims:default`（普通赋值），而 extends 别人的那个
文件优先级最高，所以在这里追加的 profile 会被整个丢掉 —— `common-addons.cfg` 里
那几个 `maitux.*:default` 也是同样的命运。所以 profile **必须手动安装**，见下一节。

### ⚠️ 构建时 vs 运行时

- **运行时**：`docker-initialize.py` 会生成 `custom.cfg`，于是
  `docker-entrypoint.sh` 里的 `if [ -e "custom.cfg" ]` 命中，**每次容器启动都会
  重跑 `buildout -c custom.cfg -N`**。那时 bind mount 已生效，挂载的
  `custom-addon.cfg` 和插件源码都在位，一切正常。
- **构建时**：Dockerfile 会把 `custom-addon.cfg` COPY 进镜像，但
  `/opt/addons/customers` 在构建阶段是**空目录**（compose 的挂载在
  `docker build` 期间不存在）。于是 `develop` 只打一条 warning，紧接着
  `instance` part 解析 `${buildout:eggs}` 时抛
  **`MissingDistribution: Couldn't find a distribution for 'maitux.oauth2'`**，
  构建失败。

两种解法，选一个：

1. 在 Dockerfile 里加 `COPY addons/customers /opt/addons/customers`（和
   `addons/common` 一致）。代价：客户专属代码进了共享镜像。
2. 把这三项从 `custom-addon.cfg` 挪到一个**只在运行时挂载**的
   `custom.cfg`（extends `buildout.cfg`），构建时的 `custom-addon.cfg` 保持空。
   代价：配置不在 `custom-addon.cfg` 里了。

## 2. 构建与启用

```bash
docker compose -f docker-compose.yml up -d --build
```

启动后用管理员登录，进入
`站点地址/prefs_install_products_form`，安装 **MAITUX 竹云统一登录 (OAuth 2.0)**。

安装时会自动完成：

- 注册 7 个 memberdata 属性（`maitux_oauth2_subject` / `_username` / `_disabled` /
  `_disabled_reason` / `_revoked_groups` / `_last_sync` / `_last_login`）
- 创建“待授权”用户组 `oauth2-pending`（无任何角色）
- 生成 `state` 签名密钥
- 在控制面板里加一项 **竹云统一登录 (OAuth 2.0)**

> 控制面板那一项是在 `post_install` 里**用代码**注册的，不是 GS 的
> `controlpanel.xml`。因为 Plone 5.2 的 XML 导入器
> （`Products.CMFPlone.exportimport.controlpanel._initConfiglets`）会对 title 做
> `str()`，Python 2 上遇到中文直接 `UnicodeEncodeError` 并中断整个安装；而
> `registerConfiglet()` 是把 `name` 原样传给 `PloneConfiglet` 的，所以代码注册
> 可以保留中文标题，也不需要额外的翻译目录。

## 3. 配置

配置页：`站点地址/@@oauth2-controlpanel`（控制面板 → 附加产品配置）。

需要手填的只有四项：**竹云 IDaaS 地址、ClientId、ClientSecret**，再把
**“启用统一登录”勾上**。接口路径、scope、字段映射都有可用默认值，
不用动（换非竹云的 IdP 才需要改）。

回调地址（redirect_uri）**不用填** —— 插件按当前站点自动推导，
并且会识别 nginx 终止 TLS 的情况（读 `X-Forwarded-Proto`）自动用 https。
只有当外网访问路径和站点自己的 URL 不一致时（比如套了一层
`/api/sso/callback` 重写）才需要在本页手填。

### 环境变量覆盖（可选，多站点部署请慎用）

每一项都可以用 `MAITUX_OAUTH2_<字段名大写>` 环境变量覆盖，优先级高于本页。

> ⚠️ **环境变量是整个容器共享的，而一个实例可以挂多个 site，
> 每个 site 各自安装本插件。** 所以和站点有关的项（`REDIRECT_URI`、
> `ENABLED`、`AUTO_REDIRECT`、`PENDING_GROUP` …）**不要**用环境变量，
> 否则所有站点被强行用同一个值。环境变量只适合全局性的东西，
> 比如单站点部署时用 `MAITUX_OAUTH2_CLIENT_SECRET` 把密钥从 ZODB 里拿出来。

### 已预置的客户参数（生产环境 = 竹云）

下面四项已经是代码里的 schema 默认值，**全新安装后不用填**：

| 配置项 | 值 |
|---|---|
| 竹云 IDaaS 地址 | `https://passport.innocarepharma.com`（客户说可能有误，以实际为准） |
| AppId | `20260804155456579-E219-3F7069E8F`（仅记录，登录流程不用） |
| ClientId | `3UZLLHBzzxb4uZeKH2GGRxbtZMkqFjaY` |
| ClientSecret | `lAI4L84uKn0MMOnw9qlIYiXSJ9mny4KObo4NrAjy45vxoy46uixB4NfLTyRlGy3h` |

接口路径、`scope=get_user_info`、字段映射也全部预置为竹云的值，
与官方文档逐字一致（见第 11 节对照表）。

> 密钥作为默认值意味着它在 git 里。如果要收紧，把
> `interfaces.py` 里 `client_secret` 的 `default` 改成 `u""`，部署时用
> `MAITUX_OAUTH2_CLIENT_SECRET` 环境变量注入。

**ClientSecret 输入框的行为**：它从不回显已保存的值（避免密钥出现在 HTML 里）。
**留空保存 = 保持原值不变**，要改就直接填新的。（若不做这个处理，
改任何其他设置点保存都会把密钥冲成空。）

`enabled` 默认是 **关闭** 的，确认参数无误后再打开。

> 任何字段清空并保存后就是真的空，页面不会再把默认值显回来
> （z3c.form 本来会在值等于 missing_value 时回退到 `field.default`，
> 控制面板的 `updateWidgets()` 把这个行为纠正了）。

## 4. 需要在竹云侧登记的回调地址

```
https://<你的LIMS域名>/<站点id>/@@oauth2-callback
```

**不用自己拼** —— 配置页顶部第 ① 行会直接把当前站点真正会发送的那个地址印出来，
照抄给客户即可。多站点时每个站点的值不同，分别去各自的配置页抄。

如果客户坚持要用 `/api/sso/callback` 这个路径，不需要改代码，在 nginx 上加一条
重写就行（`nginx/conf.d/default.conf`，放在 `location /` **之前**）：

```nginx
location = /api/sso/callback {
    rewrite ^ /<站点id>/@@oauth2-callback$is_args$args break;
    proxy_pass http://senaite_backend;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
}
```

然后把配置里的“回调地址 redirect_uri”填成
`https://<域名>/api/sso/callback`。

## 5. 登录行为

三种状态，**互斥**，不会出现“本地登录 + 统一登录同时在一个页面”：

| 状态 | 用户看到的 |
|---|---|
| 总开关**关闭** | 原生 SENAITE 登录页，一点没变 |
| 总开关**开启**（默认） | 任何页面、包括 `/login`，全部 302 直接跳竹云，**根本看不到本地表单** |
| 开启 + 管理员豁免 | 只有原生本地表单，无 SSO 按钮 |

具体入口：

| 场景 | 结果 |
|---|---|
| 竹云 Portal 点图标（带 code、无 state） | 直接走回调登录 |
| 匿名访问任意需登录的页面 | 自动跳竹云授权页（`auto_redirect`，默认开） |
| 打开 `/login` | 也直接跳竹云（`redirect_login_form`，默认开） |
| **管理员本地登录** | `站点地址/@@oauth2-local-login` —— 种一个 1 小时的**豁免 Cookie**，只影响这个浏览器，统一登录本身一直开着 |
| 灰度上线（一部分人 SSO、一部分本地） | 关掉 `redirect_login_form` + 开启 `show_login_button` |

> `login` 视图**没有**被覆盖，只有 `require_login` 被覆盖；`/login` 的跳转是在
> traversal 时做的。这是刻意的：替换 Plone 的登录 FormWrapper 是唯一可能把所有
> 管理员锁在门外的改动。

## 6. 账号状态与授权

| 状态 | 判定方式 | 用户看到 |
|---|---|---|
| 待授权 | SSO 建的号，且没有任何非基础角色、也不属于除待授权组以外的任何组 | `@@oauth2-pending` |
| 已授权 | 管理员分配了任意 LIMS 角色，或加进了任意用户组 | 正常进入 LIMS |
| 已停用 | memberdata `maitux_oauth2_disabled = True` | `@@oauth2-disabled` |

管理员的操作就是标准 Plone 流程：**用户与组** → 找到该用户 → 给角色或加组。
不需要手工把用户移出 `oauth2-pending`（移不移都行）。

判定是**保守**的：如果建号时“加入待授权组”失败了，用户依然算待授权，不会被放进来。

## 7. 唯一 ID

配置项“唯一 ID 字段”默认是 `external_id,id`，按顺序取第一个非空值：

1. 优先取 `external_id`（即需求里说的**外部 ID**）
2. 取不到时退回竹云的 `id`

竹云的 `userinfo` 接口默认只返回 `id / userName / name / email / mobile`，没有
`external_id`。**但不需要为此去找客户配属性映射**：

- 登录时取不到 `external_id` 就退回 `id`（竹云用户 ID），一样稳定唯一
- 离职检测时，`sync_user_id_field = "external_id,user_id"` 会把用户详情返回的
  **两个字段都建进索引**，所以用 `id` 存下来的身份能和竹云的 `user_id` 对上

也就是说“用外部 ID 作唯一键”这个需求，靠同步接口那边的双字段匹配就兜住了。

⚠️ 未经真实数据验证的假设：`userinfo` 的 `id` 和用户详情的 `user_id` 是同一个
标识符（两边格式一致，文档里都叫“用户ID”）。第一次同步跑完看 `missing` 计数即可确认
—— 如果 `missing` 等于本地 SSO 账号总数，说明对不上，那时才需要找客户加属性映射。

（生产环境已验证：用户详情的 `external_id` 形如 `602908626`，与 `userinfo` 同源。）

竹云身份和本地账号的对应关系存在 portal 的 annotation 里
（`maitux.oauth2.subjects`，一个 `subject -> userid` 的 BTree），
所以竹云那边改了用户名也不会认错人。

## 8. 每天一次的用户同步（建号 + 离职处理）

流程：`POST /api/v2/tenant/token`（client_credentials）→
`GET /api/v2/tenant/applications/{app_id}/accounts`（谁被授权访问本应用）→
对名单里的每个人 `POST /api/v2/tenant/users/user-by-username`（取详情）。

**刻意不用 `GET /api/v2/tenant/users`。** 那个接口只有 `org_id` /
`updated_at_greater` 两个过滤参数，拿不到应用授权维度，一次会返回全租户几千条
员工档案（含证件号、手机号）——而实际有权访问 LIMS 的只有几十人。按授权名单逐个
查，其余人的个人信息根本不会离开竹云。

拿到名单后：

| 情况 | 处理 |
|---|---|
| 在名单里、本地没账号 | **提前建号**（待授权状态，`sync_create_missing` 控制） |
| 在名单里、本地账号被停用 | 恢复可用，**并把停用时摘掉的用户组还回去** |
| 在名单里，但竹云 `disabled` / `locked` | LIMS 停用 |
| 不在名单里（离职，或被取消授权） | LIMS 停用（`sync_deactivate_missing` 控制） |
| 管理员 | **一律不动**；若之前被误停用，会自动恢复 |

### 账号可用与否，只有一个变量

`maitux_oauth2_disabled`（存在用户身上的一个布尔值）。停用置 `True`，恢复置 `False`。
登录时就看它：

```python
if users.is_disabled(member):          # ← 唯一的「可用 / 不可用」开关
    return 账号已被禁用页面
if users.is_pending(portal, member):   # 另一个维度：管理员分没分权限
    return 待授权页面
```

**「待授权」不是第二个可用标志**，它表示管理员还没给这人分配任何角色。提前建号
建出来的账号就是这个状态：账号可用，但没权限所以进不去；管理员分配角色后自动解除。

别和这两个东西搞混：

| 名字 | 是什么 |
|---|---|
| `maitux_oauth2_disabled` | 账号可用 / 不可用（就是上面这一个） |
| `enabled`（配置项） | 统一登录**总开关**，关掉整个插件 |
| 同步报告里的 `reenabled` 等 | 只是**计数**，见下表 |

### 同步报告里的字段

| 字段 | 含义 |
|---|---|
| `accounts_total` | 竹云授权名单里有几个账号 |
| `remote_total` | 其中有几个在用户目录里查到了详情 |
| `created` | 新建了几个本地账号 |
| `linked` | 有几个绑定到了已存在的同名本地账号 |
| `disabled` | 停用了几个 |
| `reenabled` | 恢复了几个 |
| `missing` | 本地有、但竹云名单里找不到的账号数（会被停用） |
| `protected` | 跳过了几个管理员 |
| `unmatched_sample` | `missing` 的前几个唯一 ID，用来排查字段对不上 |
| `aborted_deactivation` | 安全保护是否触发（触发则本次一个都不停用） |

“停用”做了三件事：打 memberdata 标记、移出所有用户组、把本地密码改成随机值。
被摘掉的用户组记在 `maitux_oauth2_revoked_groups` 上，恢复时按原样加回去 ——
否则“恢复”等于“能登录但什么都干不了”，人会退回待授权状态。
另外每个请求都会检查一次标记，已经拿着 Cookie 的离职员工会被立刻踢出去。

⚠️ **管理员保护**：竹云的应用授权名单是给实验室人员的，管理员通常不在名单上。
如果照着名单停用，第一晚就会把管理员自己锁在门外，而且用户组全被摘掉之后，
网页上就没人能改回来了。所以持有 `Manager` / `Site Administrator` 角色的账号
永不被同步停用；只通过用户组间接拿到管理角色的人，补进“永不停用的账号”即可。

⚠️ **首次跑先用 dry run**。判定依据从“全公司名录”换成了“22 人授权名单”，
所以**在职但没有 LIMS 授权的人也会被停用**——这正是想要的效果，但如果 IT 的名单
还没配全，现有用户会被误停。`sync_max_missing_percent`（默认 50%）会兜住，
先看一次结果再放开。

### 触发方式二选一

**A. Zope 自带的 clock-server（推荐，不需要外部 cron）**

`custom-addon.cfg` 里已经写好了注释掉的片段，改掉 `token` 后取消注释重建镜像：

```ini
[instance]
zope-conf-additional +=
    <clock-server>
        method /<站点id>/@@oauth2-sync-users?token=CHANGE-ME
        period 86400
        user
        password
        host localhost
    </clock-server>
```

**B. 外部 cron / 定时任务**

```bash
curl -s "https://lims.example.com/<站点id>/@@oauth2-sync-users?token=你的口令"
```

管理员登录后也可以直接在浏览器打开
`站点地址/@@oauth2-sync-users` 手动跑一次（不需要 token）；
加 `?dry_run=1` 只看结果不改数据。返回的是 JSON：

```json
{
  "remote_total": 1200, "local_total": 83,
  "disabled": 2, "enabled": 0, "missing": 1, "updated": 5,
  "errors": [], "started": "...", "finished": "..."
}
```

最近一次的结果也会写回配置页的“上次同步结果”。

## 9. 电子签名的账号/密码二次验证

GMP / 21 CFR Part 11 要求签名时重新输一次密码，证明人还在电脑前。
`maitux.esignature` 自带的校验走本地 PAS —— 统一登录之后那条路是死的：
本地账号的密码是建号时随机生成的（`users.random_password`），**没有任何人见过**，
所以谁也输不出来。

本插件因此注册了一个走竹云的校验后端。

### 启用方法

1. 确认两个插件都已安装（本插件的注册是条件加载，没装 `maitux.esignature`
   时不会生效，也不会报错）
2. 打开**电子签名控制面板**，把“认证后端”从「Local accounts (Plone PAS)」
   改成「**竹云统一登录**」

下拉框里的选项是自动枚举出来的，`maitux.esignature` 并不知道竹云的存在 ——
依赖方向是单向的：本插件引用签名插件的接口，反过来没有。

### 用的什么接口

```
POST /api/v2/sdk/login    {"user_name": "...", "password": "..."}
```

认证方式是请求头 `X-client-id`（**不是** Basic），用的就是现有 ClientId，
不需要额外开通。文档：<https://docs.bccastle.com/api/eiam/userapi/login/username-pwd>

> 标准 OAuth2 的密码模式（`grant_type=password`）看起来更对路，但本租户实测返回
> `unsupported_grant_type: Unauthorized grant type: password` —— 该应用没被授权
> 使用密码模式，走不通。

⚠️ `X-device-fingerprint` / `X-operating-sys-version` / `X-agent` 三个请求头**是必填的**。
只带 `X-client-id` 会被拒：`SDK.COMMON.1003 设备信息不完整`（实测）。

### ⚠️ 账号锁定风险（这是本节最重要的部分）

密码错误时竹云会返回「剩余登录尝试次数:N」，**次数耗尽会锁定账号**
（`SDK.LOGIN.1003`）。竹云是公司统一登录，**锁的不只是 LIMS，是这个人所有公司
系统** —— 邮箱、OA 一起进不去。

而签名是高频操作（每次复核、审批都签），手滑输错完全正常。所以做了两道防护，
刻意是两种不同性质的：

| 防护 | 机制 | 局限 |
|---|---|---|
| 本地限流 | 连续错 `esign_max_attempts` 次（默认 3）后进入冷却，期间**根本不发请求给竹云** | 存在进程内存里。两个 Zope 实例就有两份，额度翻倍 |
| 竹云剩余次数 | 竹云返回的 N 降到 `esign_min_remaining_attempts`（默认 3）时立即停手 | 权威、共享、不需要我们存状态 |

第二道才是真正兜底的：那个数字是竹云自己算的，不管请求打到哪个实例都准。

剩余次数还会**原样告诉签名的人**：

> 密码错误，还可尝试 8 次；次数用尽将锁定您的竹云账号（公司所有系统一并无法登录）

（`maitux.esignature` 会把 `failure_reason` 直接显示出来，所以提示能送到真正
能处理它的人眼前。）

### 身份核对

竹云验证通过后返回的 `id_token` 里带着**实际通过认证的是谁**。插件会解开它
（`id_token` → JWT payload → `api` 字段是个 JSON 字符串 → 再解一层 → `userName`），
和请求的账号比对，**对不上就拒绝**。签名归错人是审计追溯最致命的错误。

### 本地账号名 ≠ 竹云登录名

本地用户名是**推导**出来的（`normalize_username`：转小写、替换非法字符、可加前缀），
反推不回去。所以建号和登录时会把竹云登录名原样存在 `maitux_oauth2_username` 上，
验证时用它。

属性是后加的，老账号上没有 —— 这种情况退回「去掉前缀」，对目前见过的所有竹云
登录名（`mengc`、`duj2` 这种）都成立。这个回退刻意不做得更聪明：猜错了就等于
把别人的登录名发给竹云。

## 10. 排错

```bash
docker compose logs -f instance | grep maitux.oauth2
```

| 现象 | 原因 |
|---|---|
| `state 签名校验失败` | 浏览器禁 Cookie，或中途换了域名 |
| `安全校验未通过` | 直接手工访问了回调地址，或 state 过期（>15 分钟） |
| `Bad client credentials` | ClientId / ClientSecret 不对 |
| `Invalid redirect: ... does not match` | 竹云侧登记的可信回调地址和 `redirect_uri` 不一致 |
| 竹云返回的用户信息中没有唯一标识 | 见第 7 节，改配置或让客户加属性映射 |
| 自签证书报 SSL 错误 | 配置里关掉“校验 HTTPS 证书” |

**万一被锁在外面**：`https://<域名>/<站点id>/@@oauth2-local-login`
永远可以打开本地登录表单；再不行就把 `enabled` 用环境变量置为 `false` 重启。

## 11. 与竹云官方文档的对照（默认值来源）

**生产环境是竹云,所有默认值以竹云官方文档为准。**

竹云有**两个文档站**,内容不一样:

- <https://docs.bccastle.com/> —— **新站,以它为准**。应用账号那组接口只有这里有。
- <https://open.bccastle.com/development/> —— 旧站,页面顶部自己挂着「访问新开放平台 →」。
  旧站**没有**应用账号接口,只照着它找会漏掉,最后只能用租户级用户列表把全公司拉下来。

| 配置项 | 默认值 | 竹云文档原文 |
|---|---|---|
| 授权页 | `/api/v1/oauth2/authorize` | `GET  {your_domain}/api/v1/oauth2/authorize` |
| 换取 Access Token | `/api/v1/oauth2/token` | `POST {your_domain}/api/v1/oauth2/token` |
| 获取用户信息 | `/api/v1/oauth2/userinfo` | `GET  {your_domain}/api/v1/oauth2/userinfo` |
| 检查 Token 有效性 | `/api/v1/oauth2/introspect` | `POST {your_domain}/api/v1/oauth2/introspect` |
| 全局退出 | `/api/v1/logout` | `GET  {your_domain}/api/v1/logout` |
| EIAM 鉴权 | `/api/v2/tenant/token` | `POST {your_domain}/api/v2/tenant/token` |
| 应用账号列表 | `/api/v2/tenant/applications/{app_id}/accounts` | `GET  {your_domain}/api/v2/tenant/applications/{app_id}/accounts`（权限码 `account_read`） |
| 按用户名查用户 | `/api/v2/tenant/users/user-by-username` | `POST {your_domain}/api/v2/tenant/users/user-by-username`（权限码 `user_read`） |
| `scope` | `get_user_info` | 文档:「此值固定为 get_user_info」 |
| 唯一 ID 字段 | `external_id,id` | 需求:外部 ID 作唯一 ID;userinfo 无 external_id 时退回 `id` |
| 同步比对字段 | `external_id,user_id` | 用户详情同时返回 `external_id` 和 `user_id` |

文档链接:
[应用账号列表](https://docs.bccastle.com/api/eiam/api/account/obtain-accountlist) ·
[按用户名查用户](https://docs.bccastle.com/api/eiam/api/user/username) ·
[API 权限码](https://docs.bccastle.com/api/eiam/api/permission-range)

**token 端点的客户端认证方式**:竹云文档明确要求
「使用 client_id 和 client_secret 进行 basic64 认证,格式为 base64(client_id:client_secret)」,
本插件就是**只发 HTTP Basic**,与文档完全一致。

**未实现的接口**(按需求,确认不需要):刷新 Token、撤销 Token。
`introspect` 有配置项但代码中未调用,预留。

### 兼容其他统一登录(次要目标)

竹云优先。其他 IdP 属于「能兼容就兼容」,不影响竹云的前提下支持:

| 部分 | 可移植性 |
|---|---|
| 登录链路(authorize / token / userinfo / logout) | ✅ 端点路径、scope、claim 字段全部可配,标准授权码模式通用 |
| state 防护、账号解析、待授权、停用拦截、控制面板 | ✅ 与身份源无关 |
| token 端点认证方式 | ⚠️ 只发 HTTP Basic(竹云要求的方式)。若某 IdP 只接受 `client_secret_post`,需加约 10 行 |
| 每日用户同步(离职处理) | ❌ 按竹云 EIAM 的响应结构写死(`{total, users:[...]}`、`disabled`/`locked`、`user_id`/`external_id`)。换 IdP 需要一个适配层;不适配时把「启用用户同步」关掉即可 |

已实测可用的非竹云 IdP:**Casdoor**(仅改配置,登录链路全通;用户同步关闭)。
对应配置见下表,仅供测试环境参考,**不要用于生产**:

| 配置项 | Casdoor 的值 |
|---|---|
| 授权页 | `/login/oauth/authorize` |
| 换取 Access Token | `/api/login/oauth/access_token` |
| 获取用户信息 | `/api/userinfo` |
| 全局退出 | `/api/logout` |
| `scope` | `openid profile email` |
| 唯一 ID 字段 | `sub` |
| 登录名字段 | `preferred_username,name,sub` |
| 姓名字段 | `displayName,name,fullname` |
| 启用用户同步 | 关闭 |
