# maitux.globalauditlog — 全局审计日志：默认开启、界面隐藏

SENAITE 2.x（Plone 5.2 / Python 2.7）客户 add-on。把 MAITUX 设置（`站点/setup`）
「安全」页签里的 **Enable global Auditlog / 启用全局审计日志**：

1. **默认开启** —— core 里这个字段的 `default=False`，且**已有站点和新站点的
   值都是关的**；本包在安装时把它设成开，并在运行时钉住；
2. **从界面上隐藏** —— 该字段不再显示在设置页面里，用户无法勾掉它。

> **卸载能力**：本包**正常提供** `profiles/uninstall/`，不属于 R4b 的合规豁免，
> 后台 Add-ons 面板可以直接卸载。
> **但卸载故意不会把审计日志关掉** —— 关掉会清空审计目录（见 §3），
> 且审计开关在法规上不该由卸载动作决定。卸载只是让那个复选框重新显示出来，
> 值仍是「开」，要不要关留给管理员显式决定。
> 包外状态：没有（全部在 ZODB 里）。

---

## 1. 需求与现状

| | core 原生 | 本包 |
|---|---|---|
| 字段默认值 | `default=False`（关） | 安装时置为开 |
| 界面上可见 | 「安全」页签里正常显示 | 隐藏（`.field` 加 `d-none`） |
| 可否被勾掉 | 可以 | 界面够不到；服务端还会把它拨回来 |

现状为什么需要这个包：`senaite.core.content.senaitesetup` 里

```python
enable_global_auditlog = schema.Bool(
    title=_(u"Enable global Auditlog"),
    description=_("The global Auditlog shows all modifications of the system. "
                  "When enabled, all entities will be indexed in a separate "
                  "catalog. This will increase the time when objects are "
                  "created or modified."),
    default=False,
)
```

默认是**关**的。关着的时候 `senaite_catalog_auditlog` 不索引任何东西
（`senaite.core.patches.archetypes.catalog_multiplex` 会按这个开关跳过该目录），
审计页上只会挂着一条 "Global Audit Log is disabled" 警告条 ——
也就是说「装好就有审计」，在原生环境下**不成立**。

---

## 2. 实现：三处，各管一段路

| 文件 | 管哪条路 |
|---|---|
| `browser/senaitesetup.py` | 人打开设置页面时：隐藏字段 + 把它推成勾选 |
| `setuphandlers.py` | 装 profile 时：把值写成开（幂等） |
| `subscribers.py` | 其它任何改写路径（ZMI / jsonapi / 别的 addon 直接调 setter） |

### 2.1 隐藏与勾选都靠 SENAITE 自己的表单适配器

设置页面是 z3c.form，前端 `editform.js` 在表单加载完成后 POST 到
`<设置页>/ajax_form/initialized`，服务端适配器返回一组前端指令。
core 已经为 `ISetup` 注册了一个适配器
（`senaite.core.browser.form.adapters.senaitesetup`，管 `rejection_reasons`
和 `restrict_worksheet_management` 两条联动），本包**继承**它，
只追加两条指令：

```python
self.add_hide_field(AUDITLOG_FORM_FIELD)      # 给 .field 包装加 d-none
self.add_update_field(AUDITLOG_FORM_FIELD, True)   # 复选框 field.checked = true
```

两条都要，理由是分开的：

* **hide 只是 CSS 隐藏，控件仍留在表单里、仍会提交** —— 这是刻意的。
  前端 `toggle_field_visibility()` 加的是 Bootstrap 的 `d-none`，
  不是把元素摘掉。
* **光隐藏不勾选会把审计关掉。** 一个没被勾选的复选框提交时走
  z3c.form 的 `-empty-marker` 分支，布尔字段得到 `False`，
  也就是保存一次设置 = 关掉审计日志。
* 反过来说，只要**勾选**了，提交值就是 z3c.form 认的 token，
  保存后仍是开。`add_update_field(..., True)` 与 SENAITE 自己
  legacy 脚本里的 `i.prop("checked", !0)` 是同一个动作。

### 2.1b 写这个包时踩到的坑（已用单测钉住）

基类 `EditFormAdapterBase` 的 `initialized()` / `modified()` 返回的是
`self.data`（**要发给前端的指令字典**），不是传进去的那份 payload。所以

```python
data = super(EditForm, self).modified(data)
if data.get("name") == AUDITLOG_FORM_FIELD:   # 永远不成立
    ...
```

不报错、页面照常打开，只是那一道兜底静默失效。`name` 必须在调基类
**之前**取出来。（`subscribers.py` / `setuphandlers.py` 不碰这个基类，
没有这个问题。）

### 2.2 值从哪来：安装时就写进 ZODB

安装处理器调用 `setup.setEnableGlobalAuditlog(True)`（只在当前是
`False` 时写，幂等）。这样**连 JS 都没跑**的情况下，服务器渲染出来的
复选框本身就是 `checked`，保存不会把它弄丢 —— 前端那两条指令是
「万一值是 False」的第二道保险，不是唯一依赖。

### 2.3 ★ layer 必须继承 `IBrowserRequest`（本包最容易写错的一处）

core 的注册是

```
for="senaite.core.interfaces.ISetup
     zope.publisher.interfaces.browser.IBrowserRequest"
```

本包把第二个 required 换成自己的 layer（R14 的 ZCML 门控通道）：

```
for="senaite.core.interfaces.ISetup
     maitux.globalauditlog.interfaces.IGlobalAuditLogLayer"
```

两对 required 不是同一个 discriminator，所以**不冲突**（R5 不触发，
也就不需要 `overrides.zcml` / `-overrides` slug，R2 不触发）。
代价是同一个请求上**两条注册都匹配**，由 Zope 挑「更具体」的那条，
所以：

```python
class IGlobalAuditLogLayer(ISenaiteCore, IBrowserRequest):
```

请求槽上的接口必须是 core 那个 `IBrowserRequest` 的**真子接口**，
本包这一对才严格更具体、才一定胜出 —— 所以这里直接继承它。
如果当初只写 `class IGlobalAuditLogLayer(ISenaiteCore)`
（`ISenaiteCore` 与 `IBrowserRequest` 互不为子接口），谁被选中就成了
实现细节；一旦没选中，`FormView.adapter` 是 `None`，
`initialized()` 直接 `return {}` —— **页面照常打开、什么也不发生、
日志里一个字都没有**，正是 R9 说的静默失效。
这条约束在 `interfaces.py` 的 docstring 里也写了一遍。

继承 `ISenaiteCore` 是为了让本层自足：设置页发出的
`ajax_form/initialized` 打到挂在 `ISenaiteCore` 层上的页面。

**同一机制在本环境有现成先例且已在生产跑通**：`bika.lims` 把
`@@auditlog` 注册在 `layer="bika.lims.interfaces.IBikaLIMS"` 上，
`maitux.audittrail` 用 `IAuditTrailLayer(ISenaiteCore, IBikaLIMS)` 覆盖它，
靠的同样是「请求槽上的接口是对方的子接口」。视图与适配器在 Zope 里
走的是同一套 `queryMultiAdapter` 解析，所以这条先例可以直接照搬。

顺带：没装本 profile 的站点，请求上不带这个 layer，core 那条照旧命中，
设置页面**与原生完全一致**（R14 要的「不泄漏」）。

### 2.4 运行时兜底为什么需要另一个入口

订阅器签名里**没有 request**（`ISetup + IObjectModifiedEvent`），
ZCML 无处插 layer，只能在处理函数里做站点级判定：

```python
if not is_installed_in_current_site():
    return
```

`siteinstall.py` 沿用 `maitux.esignature/siteinstall.py` 的判定口径
（先问 `portal_quickinstaller`，再退回 `portal_setup` 的 profile 版本，
`'unknown'` = 没装），只是不需要按请求缓存 —— 本订阅器每次设置对象被
改写才跑一次，不像 guard 那样每行每 transition 跑一遍。

只在**当前值确实是 False** 时才写，所以不会事件递归：写入本身会再触发
一次本订阅器，那一次读到的已经是 `True`，直接返回。

---

## 3. 没做的事：不 monkey patch core 的 setter

`Setup.setEnableGlobalAuditlog(False)` 在 core 里长这样：

```python
if value is False:
    # clear the auditlog catalog
    catalog = api.get_tool(AUDITLOG_CATALOG)
    catalog.manage_catalogClear()
```

**清空发生在字段被写之后、本包的 `IObjectModifiedEvent` 订阅器之前。**
真有人绕到那条路（伪造 POST / 直接调 API），本包只能把开关拨回来，
目录已经被清了。

要在清空之前拦住，只能 monkey patch core 的 setter。不做的原因：
代价（R10：不碰数据与工作流；随 core 升级漂移；全局代码改动）大于收益 ——
设置页面上该字段已隐藏且强制勾选，正常路径到不了那里。

**万一真被清空了**：`maitux.auditjournal` 有回填能力
（`Backfill Audit Journal` / `backfill.py`），审计目录可以从那套数据重建。

---

## 4. 部署

本包放在 `addons/customers/` 一级目录下，**运行时自动收录**：

```powershell
# 1. 同步源码（增量，不要用 /MIR —— 会删掉容器编译出的 .pyc）
robocopy "<源>\maitux.globalauditlog" `
         "<部署目录>\addons\customers\maitux.globalauditlog" `
         /E /XF *.pyc /NFL /NDL /NJH /NJS

# 2. 确认被收录（应当打印出 maitux.globalauditlog）
docker compose logs instance | grep gen-custom-addon

# 3. 重启
docker compose restart instance
```

| 改动内容 | 生效方式 |
|---|---|
| 新增本 add-on 目录 | **重启容器**（`gen-custom-addon.sh` 重新生成 `custom-addon.cfg`） |
| `.py` / `.zcml` | **必须重启容器**（R8） |
| `profiles/**`（含 `browserlayer.xml`） | 重启 + **在后台重跑/安装 profile**（R3） |
| `.js` / `.css` | 本包没有；无需硬刷新 |

**安装 profile 是必须的一步**：客户 add-on 的 profile 不会被
`[plonesite] profiles` 自动装（`addons/customers/README.md` 有说明）。
登录后台 → `站点/prefs_install_products_form` → 勾选
**Maitux 全局审计日志强制开启** → Install。

> 页面上的标题中文取自 `configure.zcml` 的 `registerProfile/@title`，
> 不走 `actions.xml` / `controlpanel.xml`，因此不涉及 R9b。

已经在用这份 `addons/customers/` 的部署，**只需放目录 + 重启 + 装 profile**，
不用改 `custom-addon.cfg`（它是运行时自动生成文件，R5d）。
若要改成所有客户都吃（打进镜像），则整个目录移到 `addons/common/`，
并按 `common-addons.cfg` 的既有格式补上 `develop +=` / `eggs +=` 两行，
再重建镜像 —— `common/` 是**构建期 COPY**，不能只重启。

---

## 5. 验证判据（可观测）

重启 + 装好 profile 之后，逐条对：

| # | 操作 | 预期信号 |
|---|---|---|
| 1 | 启动日志 | `gen-custom-addon` 段落里列出 `maitux.globalauditlog`（否则目录没被收录：多半是缺 `setup.py` 或套了一层客户目录） |
| 2 | Add-ons 面板 | 出现 **Maitux 全局审计日志强制开启**；Install 后无报错 |
| 3 | 日志搜 `Maitux.Globalauditlog` | 出现 `setup handler [BEGIN]` / `global auditlog enabled` / `[DONE]` |
| 4 | 打开 `站点/setup`（设置页）→ 「安全」页签 | **看不到** Enable global Auditlog 这一项 |
| 5 | 同页打开 devtools → Elements，找 `div.kssattr-fieldname-form.widgets.enable_global_auditlog` | 该元素**带 `d-none` 类**（CSS 隐藏；所以「查看源代码」里仍能看到它，这是预期的） |
| 6 | devtools Console：`document.querySelector("input[name^='form.widgets.enable_global_auditlog']").checked` | `true` |
| 7 | 打开审计日志列表页（core 的 `Audit Log` 动作指向 `站点/bika_setup/auditlog`） | **没有** "Global Audit Log is disabled" 警告条 |
| 8 | 随便改一个样品（或任何对象）保存，再刷新第 7 步页面 | 列表里出现该对象的审计行（证明开关真的是「开」，不只是界面好看） |
| 9 | 在设置页随便保存一次（如改个标题再改回来） | 保存成功，第 8 步的审计行**继续增加** —— 说明保存设置没有把开关冲掉 |
| 10 | **回归 / 反证**：打开**没装本包**的另一个站点（多站点环境）的设置页 | 该复选框照旧显示、行为与原生一致 → 证明 layer 门控生效、没有全局泄漏（R14） |
| 11 | 单测 | 见 §6，20 个用例全绿 |

第 5 步必须用 devtools 看：隐藏是 JS 在 `ajax_form/initialized` 之后加的
CSS 类，服务器渲染的 HTML 里不会有 `d-none`，`curl` 或者「查看源代码」
看不出区别。

---

## 6. 单测

不需要 Plone，本机 Python 2.7 直接跑：

```bash
cd <addon>/src/maitux/globalauditlog/tests
python -m unittest test_sources
```

当前 **20 个用例全绿**。钉的都是「写错也不报错」的点：

* 字段名逐字对齐 core 的 schema（`enable_global_auditlog`，不是 `audit_log`）；
* layer 继承的是 `IBrowserRequest`（core 注册里被替换掉的那个请求槽接口）；
* `browser/configure.zcml` 的 `for=` 里是 `ISetup + 本包 layer`，
  **不含** `IBrowserRequest`（那就是没门控，R14 判 W17）；
* `<subscriber>` 用 `handler=` 且没有 `factory=` / `provides=`（R15）；
* 适配器的 `modified()` 里 `name` 必须在调基类之前取出 ——
  基类返回的是 `self.data`（发给前端的指令字典），不是传进去的 payload，
  写反了判断永远不成立（写这个包时真的踩了，见 §2.1b）；
* 用 AST 扫出所有 `*.setEnableGlobalAuditlog(...)` 调用，
  断言**只出现过 `True`**（写 `False` 会清空审计目录）；
* profile 标记文件与目录齐全。

判定一律读**真实结构**（XML 属性、AST 调用）而不是 grep 注释 ——
本包的注释里就写着反面写法（core 的原注册、`setEnableGlobalAuditlog(False)`
的危害），拿字符串搜索会被自己的说明文字绊倒。

静态检查（宿主机 Python 3）：

```bash
python3 <addons>/customers/lint_addon.py --addon maitux.globalauditlog
# → 0 ERROR / 0 WARN / 0 INFO
```

---

## 7. 目录结构

```
maitux.globalauditlog/
├── setup.py                          # 1.0.0；分发名与目录名一致（R5c）
└── src/maitux/globalauditlog/
    ├── __init__.py                   # 包名 / profile id / 字段名常量（唯一出处）
    ├── interfaces.py                 # IGlobalAuditLogLayer(ISenaiteCore,
    │                                 #                        IBrowserRequest)
    ├── configure.zcml                # 包级注册 + 两个 importStep + 订阅器
    ├── browser/
    │   ├── configure.zcml            # 设置表单适配器（for= 里带本包 layer）
    │   └── senaitesetup.py           # 继承 core 适配器，只加 hide + 勾选
    ├── siteinstall.py                # 「本包装在这个站点上了吗」的运行时判定
    ├── subscribers.py                # 设置被改写后把开关钉回开
    ├── setuphandlers.py              # 安装时置为开（幂等）/ 卸载不动开关
    ├── profiles/
    │   ├── default/{metadata.xml, browserlayer.xml, *.txt}
    │   └── uninstall/{metadata.xml, *-uninstall.txt}
    └── tests/test_sources.py         # 20 个用例，不需要 Plone
```

---

## 8. 已知边界

* **不回溯**。开关是「从此刻起记录所有改动」；打开之前的历史不在
  `senaite_catalog_auditlog` 里（core 打开时不做任何重建索引）。
  要补历史用 `maitux.auditjournal` 的回填。
* **有性能代价**。字段自己的 description 就写着启用后
  「objects are created or modified」会变慢 —— 这是审计的固定成本，
  本包把它从「可选项」变成「默认项」。
* **只隐藏这一个字段**，不动「安全」页签的其余项，也不改 core 的任何
  文件；`restrict_worksheet_users_access` → `restrict_worksheet_management`
  那条既有联动由 core 的实现继续负责（本包继承它、不复制）。
* **`<subscriber>` 的站点判定依赖 `portal_quickinstaller` / `portal_setup`**。
  极端情况下（装了 profile 但两个记录都被人工清掉）会判成「未安装」，
  此时运行时兜底不生效，但界面隐藏仍然生效（那一条走 browser layer）。
* **卸载不关开关**（见首段，以及 `setuphandlers.py` 里
  `uninstall_handler` 的 docstring）。要真正关掉，只能在原生设置页面
  显式取消勾选 —— 而那时必须先卸载本包，否则会被钉回来；
  注意取消勾选会**清空审计目录**。
* 本包没有 `upgrades/`：它不承担 R4b 的合规豁免（提供了卸载能力），
  后续若改 `profiles/**`，按 R3 走「重装一次 / 写 upgrade step」。

---

## 9. 开发规则符合性自查

- [x] 覆盖 core 同名注册用的是**本包 layer 换掉 REQUEST 槽**，不是同名冲突（R5 / R14）；`for=` 里出现 layer，`lint_addon.py` 的 `scan_ui_gating` 判定为已门控
- [x] 无 `overrides.zcml`，因此不需要 `-overrides` slug（R2 不触发）
- [x] 覆盖适配器是「继承 + 只改必要方法」，core 的两条既有联动原样保留（R6）
- [x] ZCML 里没有任何 `permission=`，故不适用 R1；`configure.zcml` 里写明了「将来若加 permission= 必须同时补 `senaite.core.permissions` include」
- [x] `registerProfile` 声明的两个目录都存在且含 `metadata.xml`；提供 `profiles/uninstall/`（R4）
- [x] 不属合规豁免，但 README 首段仍写明「卸载不关开关」及其理由（R4b 的引申）
- [x] 分发名 / 目录名 / 包名三者一致，只用 autoinclude，不手改 `custom-addon.cfg`（R5c / R5d）
- [x] 部署说明区分了「重启」与「重启 + 装/重跑 profile」（R3 / R8）
- [x] 每项功能都给了可观测判据，并明确「隐藏是 JS 加的 CSS 类，必须用 devtools 看」（R9）
- [x] 未新增 `actions.xml` / `controlpanel.xml`；profile 的中文标题走 `registerProfile/@title`（R9b 不适用）
- [x] 未注册 configlet（R11 不适用）；无引用控件（R12 不适用）
- [x] 指向外来内容接口的注册做了门控：适配器走 ZCML（`for=` 里带 layer），订阅器走运行时站点判定（R14 两条通道各用一条）
- [x] `<subscriber>` 指向普通函数，用 `handler=`；没有 `factory=`，也没有 `@adapter`（R15）
- [x] 无布尔 `BooleanWidget`，`render_own_label=True` 不适用（R16）
- [x] 所有 `.py` 都有 PEP 263 声明；中文字面量一律带 `u""` 前缀（本包的中文只出现在注释与 docstring 里），`lint_addon.py` 的 `E06` / `W07b` 均不触发
- [x] `python3 lint_addon.py --addon maitux.globalauditlog` → **0 ERROR / 0 WARN / 0 INFO**；全量 `--summary` 亦为 0 ERROR
- [x] 未被跳过、也没往 `lint_baseline.json` 加条目
