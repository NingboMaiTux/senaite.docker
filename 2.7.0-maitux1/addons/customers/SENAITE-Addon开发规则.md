# SENAITE Addon 开发规则（MaituxLIMS 产品环境）

> 从实际踩坑中沉淀的规则，适用于本产品环境下所有自研 addon
> （`medai.*` / `maitux.*`）。每条都注明**依据**与**违反后果**。
>
> 环境前提：SENAITE 2.x + Plone 5.2 + Python 2.7。客户 addon 通过
> 运行时自动生成的 `custom-addon.cfg` 接入 buildout；显式 ZCML 最终体现为
> `package-includes/` slug 的加载顺序。

## 机器检查

下面多条规则标了「机器判据：`lint_addon.py` 的 `Exx`」。检查器就在本目录：

```bash
python 2.7.0-maitux1/addons/customers/lint_addon.py --addon maitux.xxx   # 查一个
python 2.7.0-maitux1/addons/customers/lint_addon.py                      # 全量
```

从哪个目录跑都行，它按自身位置找 `addons` 根。**改完 addon、重启容器之前跑一遍**；
`ERROR` 为 0 才进部署。当前覆盖 R1 / R4 / R4b / R5b / R5c / R5d / R14 / R16
以及若干 Python 2.7 编码陷阱。

> 这份 `lint_addon.py` 有两份拷贝，内容保持一致：本仓库这份是给团队用的，
> 另一份在维护者的个人工具库里。改任一份都要同步另一份 —— 文件头的注释里
> 也记了这件事。

---

## 一、ZCML 加载顺序（最容易踩、且症状最吓人）

### R1. 用到 SENAITE 自定义权限的注册，必须写在 `overrides.zcml`

**规则**：`browser:page` / `adapter` 等带 `permission=` 的注册，若权限来自
`senaite.core.permissions` 或 `bika.lims.permissions`（如
`ManageAnalysisRequests`、`ViewResults`、`FieldEditAnalysisResult`），
**只能写在 `overrides.zcml`，不能写在 `configure.zcml`**。

**依据**：容器内 `parts/instance/etc/site.zcml` 的加载顺序：

```
11  <include files="package-includes/*-meta.zcml" />
12  <five:loadProducts file="meta.zcml"/>
15  <include files="package-includes/*-configure.zcml" />        ← addon 的 configure
16  <five:loadProducts />                                        ← SENAITE 权限在这里才注册
19  <includeOverrides files="package-includes/*-overrides.zcml" />  ← addon 的 overrides
```

SENAITE 的自定义权限声明分散在 `bika/lims/browser/**/configure.zcml` 等文件里，
全部由**第 16 行**的 `five:loadProducts` 加载。而 addon 的 `configure.zcml` 在
**第 15 行**就执行了，此时权限尚未注册。

**违反后果**：`protectClass` 提前执行 → `ComponentLookupError(IPermission, ...)`
→ **Zope 直接启动失败**，整个站点起不来。

**安全的例外**：Zope 内置权限（`zope2.View`、`zope.Public`、
`cmf.ModifyPortalContent` 等）由第 6 行的 `Products.Five` 注册，
在 `configure.zcml` 阶段已可用，无此限制。

> 判断口诀：**权限字符串以 `zope2.` / `zope.` 开头 → configure 可用；
> 以 `senaite.core.` / `bika.lims.` 开头 → 必须 overrides。**

---

**等价写法（推荐给已经写在 `configure.zcml` 里的注册）**：在本包的 `configure.zcml`
顶部 `<include package="senaite.core.permissions" />`，把权限的注册顺序钉在自己前面。
`custom-addon.cfg` 的显式 slug 和 autoinclude **都不保证**本包排在 `senaite.core`
之后（2026-08-28 实测两种都会炸），所以这一行是 addon 自己的责任。
`maitux.esignature` / `maitux.instrument_acquisition` 一直这么写；
`maitux.audittrail` / `groupmanagement` / `reviewerassignment` / `worksheet`
当天补上后启动恢复。

---

### R2. 新增 `overrides.zcml` 内容时，必须同步补 package-includes slug

**规则**：addon 首次往 `overrides.zcml` 写入实际内容时，
必须在 `package-includes/` 下补一个 `-overrides.zcml` slug，与 configure 成对。

**依据**：本环境每个 addon 需要**两个** slug 文件，缺一不可：

```
package-includes/
  10-<pkg>-configure.zcml   →  <include package="<pkg>" file="configure.zcml" />
  10-<pkg>-overrides.zcml   →  <include package="<pkg>" file="overrides.zcml" />
```

**违反后果**：整个 `overrides.zcml` **完全不被加载**，且
**不报任何错误**——viewlet 覆盖、视图注册全部静默失效，
表现为"改了没生效"，极难定位。

**易踩场景**：addon 初建时 `overrides.zcml` 往往只有一句
`<!-- Reserved for future overrides -->`，此时没有 slug 也无妨；
等某次真正往里写内容时，很容易忘了它从来就没被加载过。

---

## 二、GenericSetup Profile

### R3. 新增 profile 文件（`registry.xml` 等）必须重跑 profile 才生效

**规则**：往 `profiles/default/` 新增或修改 `registry.xml`、`workflows.xml`
等 GenericSetup 文件后，**对已安装的站点不会自动生效**，必须：

- 在 Add-ons 页面 **Uninstall → Install**，或
- 编写 upgrade step 并执行

**违反后果**：功能看似正常（若代码里有兜底默认值），但**配置项不出现在
控制面板中**——属于"静默降级"，交付方以为做完了，客户以为没做。

**要求**：部署文档中必须写明"已安装站点需重跑 profile"，
不得依赖代码兜底默认值蒙混过去。

---

### R4. `configure.zcml` 里注册的 profile，其目录必须真实存在

**规则**：`genericsetup:registerProfile` 声明的 `directory` 必须存在且含
`metadata.xml`，即使是空的 uninstall profile。

**违反后果**：ZCML 加载报错。

---

### R4b. 合规类 addon 可豁免卸载能力，但**必须**换成强制可升级

**背景**：`CLAUDE.md` §5 把 `profiles/uninstall/` 列为硬要求
（「卸载能力是硬要求」）。**合规类 addon 是唯一的豁免类别。**

**什么算合规类**：功能本身承担 GMP / 21 CFR Part 11 等法规义务，
被关闭即等于违规。典型是审计追踪、电子签名。
**判据不是「重要」，而是「按法规不允许被用户关闭」** ——
不要拿这条给普通功能包开口子。

**豁免的是什么**：可以不提供 `profiles/uninstall/`。理由通常有两条：

1. 法规上该能力不得被用户关闭；
2. 技术上 profile 卸不掉包外的状态（如自建的 PostgreSQL 表、外部文件），
   给一个卸不干净的「卸载」按钮，比没有按钮更危险 ——
   它让人以为卸干净了。

**★ 换来的义务（这半句同样是硬要求）**：

普通 addon 可以靠「Uninstall → Install」回到干净状态（见 R3）。
豁免掉卸载，就等于**放弃了唯一的兜底逃生口**，此后只剩升级一条路。所以：

- **`upgrades/` 必须从第一版就建起来并验证过一次**，
  不能等「真要改了再说」—— 那时已经没有退路了。
  哪怕 v1 无实际变更，也要造一个空 step，确认后台能看到、能执行。
- **profile 的任何后续变更只能走 upgrade step**，
  不得依赖「重装一次就好了」。
- **若包在 ZODB 之外还有状态**（自建表、外部文件），
  必须有**幂等的**迁移机制，且**不能只挂在站点级 upgrade step 上** ——
  多站点 / 多数据库形态下它升不全。
  推荐做成运行时惰性检查（用时比对版本号并补齐）。
- 包 `README` **首段**必须写明「本包不提供卸载能力」及理由、
  停用的正确做法、以及包外状态如何处置。

**违反后果**：
- 只豁免不补升级 → 第一次要改表 / 改 profile 时无路可走，
  只能手工进库改，且各站点状态从此发散。
- README 不写 → 下一个人把缺失的 `profiles/uninstall/` 当疏漏「补」回来，
  合规豁免被静默撤销。

**现有实例**：`maitux.auditjournal`（首例，详见
`Docs/auditlog-journal-实施方案.md` §8.3 / §8.4）。
截至该包引入前，4 个 common addon 与全部 customers addon **都有**卸载 profile。

---

## 三、覆盖 SENAITE 原生组件

### R5. 覆盖同名组件用 `overrides.zcml`，不要用 `configure.zcml`

**规则**：替换 senaite.core 已注册的 viewlet / view / adapter（`name` 与
`manager`/`for` 完全相同）时，注册必须放在 `overrides.zcml`。

**依据**：`configure.zcml` 走 `include`（同名注册视为**冲突**），
`overrides.zcml` 走 `includeOverrides`（同名注册视为**覆盖**）。

**违反后果**：`ConfigurationConflictError`，启动失败。

---

### R6. 覆盖 viewlet 时优先"继承 + 只改必要方法"

**规则**：覆盖原生 viewlet/view 时，继承原类并只重写必需的方法，
不要整体复制实现。

**理由**：标题、图标、`available()`、折叠状态等行为可随 senaite.core
升级自动跟进，减少版本漂移。

**实例**：`LabAnalysesGroupedViewlet` 继承 `LabAnalysesViewlet`，
仅重写 `get_listing_view()` 与 `contents_table()`。

---

### R5b. 跨 addon「同接口+同名」adapter 必须进 `overrides.zcml`，避免双注册冲突

**规则**：两个（或多个）addon 若为**同一 interface + 同一 name** 注册 adapter
（如都注册 `IStockBatches → IGetStickerTemplates`），这些注册**只能放在
各自的 `overrides.zcml`**，不能都写在 `configure.zcml`。

**依据**：`configure.zcml` 走 `include`，同名注册视为**冲突**；只有
`overrides.zcml`（`includeOverrides`）才会把后者当作**覆盖**而非冲突。

**违反后果**：`ConfigurationConflictError` → **容器重启循环、Zope 启动失败**，
且是在 ZCML 加载阶段直接崩，站点完全起不来（易误判为镜像/网络问题）。

**实例**：`INNOCARE.labeldesign` 与 `maitux.stock` 同时为
`IStockBatches` 注册 `IGetStickerTemplates` 适配器，两套 `configure.zcml`
同时加载即冲突。把该注册移入 `overrides.zcml` 并补 `-overrides` slug 后恢复。

---

### R5c. 分发名与目录名大小写必须一致，且依赖 autoinclude 入口点而非手动 include

**规则**：addon 的 **egg 分发名（`setup.py` 的 `name`，如 `INNOCARE.Reportdesign`）
与代码目录名（如 `INNOCARE/Reportdesign`）必须大小写一致**；同时，若
`setup.py` 已配置 `z3c.autoinclude.plugin` 入口点，**不要再在
`custom-addon.cfg` 的 `[instance] zcml +=` 里手动 include 该包**。

**依据**：Windows 文件系统大小写不敏感。分发名与目录名大小写不一致时，
`meld`/buildout 可能把同一包识别成两个实例，导致 zcml 里的静态资源
（如 `plone:static type="worksheets"`）被加载两次。

**违反后果**：同资源重复注册 → `ConfigurationConflictError` → 启动失败；
或手动 include 与 autoinclude 双路加载导致重复注册。移除手动 include、
仅保留 autoinclude 入口点后恢复。

---

### R5d. `custom-addon.cfg` 是自动生成的，不要手工改

**规则**：客户 add-on 的 buildout 配置**不再手工维护**。当前产品环境仍然使用
`custom-addon.cfg`，但它是运行时自动生成文件，不应作为仓库里的手工维护清单。
addon 作者要做的只是把目录结构、`setup.py`、`configure.zcml` / `overrides.zcml`
写对：

| 生成项 | 来源 |
|---|---|
| `develop +=` | 一级子目录名（必须含 `setup.py`，否则整个目录被跳过） |
| `eggs +=` | `setup.py` 的 `name=`（不是目录名） |
| `[instance] zcml +=` | 每个有 `configure.zcml` 的包都写；分发名与代码目录大小写不一致的除外（R5c） |
| `<egg>-overrides` slug | 包里存在 `overrides.zcml` 就自动补（R2 / R5b） |

**依据**：`buildout.cfg` 仍然 `extends = custom-addon.cfg`，而运行时配置由容器环境
自动生成。手工维护这份 cfg 的典型事故包括：写错包名、漏写 `-overrides` slug、
物理删掉 add-on 目录但忘了从 cfg 剔除（→ buildout 失败 → 容器无限重启）。

**违反后果**：手改的内容下次启动就被覆盖；更严重时会让人误以为运行配置来源于
仓库，排查方向被带偏。

**注意**：`[plonesite] profiles` 不会被生成，profile 一律在后台
`prefs_install_products_form` 手工安装（原因见 `README.md`）。

---

## 四、部署（8085 Docker 环境）

### R7. 同步用 `/E` 不要用 `/MIR`

```powershell
robocopy "<源>" "<目标>" /E /XF *.pyc /NFL /NDL /NJH /NJS
```

**理由**：`/MIR` 会删除目标端多出的文件，包括容器编译产生的 `.pyc`。
本场景只需增量更新，`/E` 足够且无删除风险。

**注意**：robocopy 退出码 0–7 均为成功，PowerShell 会将非零码判为失败，
可忽略或用 `if ($LASTEXITCODE -lt 8)` 判断。

---

### R8. 改动生效方式因文件类型而异

| 改动内容 | 生效方式 |
|---------|---------|
| `.py` | **必须重启容器** |
| `.zcml` | **必须重启容器** |
| `.pt` 模板 | 重启即可（Chameleon 按内容摘要自动失效缓存） |
| `.js` / `.css` | 重启 + **浏览器硬刷新 `Ctrl+Shift+R`** |
| `profiles/*.xml` | 重启 + **重跑 GenericSetup profile**（见 R3） |

**易踩点**：静态资源经 `++resource++` 提供，带长缓存头。
只重启容器不硬刷新，浏览器仍用旧 JS/CSS，表现为"代码改了没效果"。

---

## 五、通用原则

### R9. 本环境的失败大多是"静默"的，验证必须给可观测判据

本产品环境（尤其计算引擎）大量采用容错设计：求值失败保留原值、
异常被 `except: pass` 吞掉。因此：

- **不要用"看起来对不对"验收**
- 每项改动必须给出**具体可观测信号**：某个 HTTP 状态码、
  某个 DOM 属性、某个字段是否出值、某条日志

**已知的静默失效清单**（持续补充）：

| 现象 | 根因 |
|------|------|
| overrides 全部不生效 | 缺 package-includes slug（R2） |
| 控制面板无配置项 | 未重跑 profile（R3） |
| 前端改动无效果 | 浏览器缓存静态资源（R8） |
| 某计算字段永远空白 | 公式求值失败被静默吞掉 |
| 页面渲染成旧布局 | ZCML 中 `class` 与 `template` 并用，`__call__` 被 MRO 遮蔽 |
| 容器重启循环 / Zope 启动即崩 | 跨 addon 同接口同名 adapter 冲突（R5b）或分发名与目录名大小写不一致（R5c） |

---

### R9b. `actions.xml` / `controlpanel.xml` 里的 `title` / `description` 必须 ASCII

**规则**：**portal action 类**的 GenericSetup XML（`actions.xml`、
`controlpanel.xml`）里的 `<property name="title">` / `<property name="description">`
**不得包含中文或任何非 ASCII 字符**。要中文界面，写 ASCII msgid +
在 `locales/` 里给 `zh_CN` 翻译（`senaite.impress` 就是这么做的）。

> **范围为什么只到 action 类**：`types/*.xml` 有**活的反例** ——
> `maitux.reviewerassignment` 的 FTI 用中文 title + `i18n:domain`，
> 在生产里正常显示（侧边栏「审核工作表」）。`TypesTool.Title()` 同样会走
> `Message()`，两者的差别在**导入器把值存成 unicode 还是 utf-8 字节串**，
> 未挖到底。**所以本规则只覆盖有实测事故的这一类，不做过度概括** ——
> 宁可范围窄一点，也不要让 lint 对着能跑的代码报警（一旦开始误报，
> 人就会开始忽略它）。

**依据**（2026-08-31 实测事故，含事后订正）：

```python
# Products/CMFCore/ActionInformation.py
80:   i18n_domain = 'cmf_default'          # ← 类默认值，几乎总是真值
161:  elif self.i18n_domain and id in ('title', 'description'):
162:      val = Message(val, self.i18n_domain)
```

`zope.i18nmessageid.Message` 是 **unicode 的子类**，拿它去包一个含中文的
**字节串**，Py2 会隐式按 ASCII 解码 → `UnicodeDecodeError`。

> **★ 订正**：最初以为触发条件是"**你设了** `i18n_domain` + 非 ASCII"。
> 实测不是 —— `Action` 的 `i18n_domain` **有类默认值 `'cmf_default'`**，
> 所以那个 `if` 几乎恒为真，`Message()` 总会被调用。
> **结论更强：`actions.xml` 里的中文标题必炸，没有"不设 domain 就安全"这条路。**

**另一个相关的坑（同日实测）**：`i18n:domain="..."` 这个 **XML 属性设不了域** ——
CMFCore 的 actions 导入器**只在导出时**写 `xmlns:i18n`
（`exportimport/actions.py:110`），导入时根本不读它。
要让标题走本包的翻译，必须显式写：

```xml
<property name="i18n_domain">你的包名</property>
```

不写就用默认的 `cmf_default` 域，于是拿你的 msgid 去别人的域里查 ——
查不到，界面显示英文原文，**而且不报错**。

**违反后果**：若该 action 落在 `user` / `site_actions` 分类，
**personal bar 每个页面都渲染 → 整站多数页面打不开**。
`maitux.auditjournal` 的 v3 profile 就是这么把 `/Care` 站点搞崩的。

**★ 最阴的地方：它是渲染期才炸的。**
lint 过、镜像建成、实例正常起、启动日志干净、`verify` 全绿 ——
**只有真人打开页面才炸**。这是 R9「静默失效」的一个变体：
不是没报错，是**报错时机晚到所有自动判据之后**。

**已有防线**：`lint_addon.py` 的 `E14_NON_ASCII_GS_TITLE` 会扫
`profiles/**/*.xml` 拦下它（2026-08-31 加，已用真实故障回放验证过）。

**踩到之后怎么救**：坏 action 存在**站点的 ZODB 里**，重建镜像不会清掉它。
Plone 页面全崩时走 ZMI（不渲染 personal bar）：
`<site>/portal_actions/user/manage_main` → 勾选 → Delete；
再用 upgrade step 重新导入修好的 `actions.xml`。

---

### R10. 只改渲染，不碰数据与工作流

**规则**：新增视图/布局时，复用原生的保存端点、计算引擎与工作流适配器，
不自建 save adapter、不绕过 `IDataManager.set()`。

**理由**：计算引擎（含依赖重算）挂在原生保存链路上，绕开它会导致
计算不触发，且该问题不报错。

**实例**：AS-Grouped 布局复用 `ajax_set_fields` 端点与
`workflow_action_submit` 适配器，仅替换渲染模板。

---

### R11. 静态数据维护型 addon 不要注册附加产品配置入口

**规则**：如果 addon 的职责只是维护静态字典、基础资料或站点内数据容器，
并且已有文件夹默认视图、列表页或站点侧边栏入口可完成维护，就**不要**再往
`portal_controlpanel` / `@@overview-controlpanel` 注册独立 configlet。

**理由**：这类 addon 本质上是“站点数据维护”，不是“系统参数配置”。
把它挂到附加产品配置区会让用户误以为这是全站设置项，也会让 overview 页面
出现与实际职责不匹配的入口。

**实例**：`maitux.hazardcategories` 负责维护 Hazard categories 静态字典，
应通过 `HazardCategories` 容器默认视图和侧边栏入口维护，而不是在
附加产品配置区增加入口。

**例外**：只有当 addon 维护的是 registry/控制参数/鉴权开关/外部系统连接等
真正的系统级设置时，才注册 configlet。

---

### R12. 给引用控件传 `query=` 时，必须同时传 `base_query={}`

**规则**：凡是构造 `ReferenceWidget` / `QuerySelectWidget` / `UIDReferenceWidget`
并传了 `query={...}` 的地方，**必须**同时显式传 `base_query={}`。

```python
widget=ReferenceWidget(
    label=_(u"Sample properties"),
    catalog=SETUP_CATALOG,
    base_query={},                      # ← 必须有
    query={
        "portal_type": "HazardCategory",
        "usage_scope": [u"both", u"ar", u"ar_only"],
        "sort_on": "sortable_title",
        "sort_order": "ascending",
    },
)
```

**理由**：`senaite.core` 的
`ReferenceWidget._properties["base_query"]` 是一个**类级共享的可变 dict**。
Archetypes 的 `_process_args` 只做 `self.__dict__.update(self._properties)`
浅拷贝，所以没显式传 `base_query` 的实例，拿到的就是那个共享对象本身；
而 `referencewidget.get_query()` 拿到它以后直接原地改：

```python
base_query = self.get_base_query(context, field)   # 共享 dict
query = getattr(self, "query", None)
if isinstance(query, dict):
    base_query.update(query)                       # ← 原地写，全进程永久生效
```

只要渲染过一次**非拷贝**的原始 widget（打开任意样品的 `view` / `base_edit`
就会），你 `query` 里的**所有**键就永久污染整个 Zope 进程里的所有引用控件。

显式传 `base_query={}` 后，kwargs 覆盖类级默认值，`update` 只改本实例，
既不污染别人，**也免疫别人泼过来的键**（`get_base_query` 返回你自己的 dict）。
这一点很重要：`senaite.core` 自己有 63 处只传 `query=`，我们管不了上游，
但传了 `base_query={}` 的控件不受影响。

**泄漏不等于致命。致命需要两个条件同时成立**：

1. 泄漏的键**是目标 catalog 的索引**
2. 其他 `portal_type` **不具备该属性**（因而不进该索引 → 被过滤成 0 条）

`senaite.core` 泄漏的 6 种键都撞不上第 2 条，所以原生环境一直没事：

| 键 | core 泄漏处数 | 为什么无害 |
|---|---|---|
| `sort_on` / `sort_order` / `sort_limit` | 57 / 56 / 1 | 排序参数，不参与过滤 |
| `is_active` | 57 | 通用索引，**每个内容类型都有该属性** |
| `portal_type` | 2 | `get_query()` 末尾每次都覆写 |
| `is_received` | 1 | 在 `senaite_catalog_setup` 里不是索引，ZCatalog 忽略 |

**addon 天然更容易踩**，因为 addon 的典型动作恰恰是「给自己的内容类型建一个
**专属索引** + 在自己的控件 query 里用它」——这两件事单独看都正常，合起来
就同时满足了上面两个条件。`senaite.core` 从不这么做（它的索引都跨类型通用）。

**实例**：`INNOCARE.arextension` 的 `SampleProperties` 字段 query 带
`usage_scope`，而 `maitux.hazardcategories` 往 `senaite_catalog_setup` 建了
`usage_scope` KeywordIndex。结果 Care 站样品登记页（`ar_add`）**所有**引用
控件搜不出内容 —— 样品类型、模板、客户、联系人、批次全部空白。

决定性 A/B（同一进程、同一次污染）：

```
Care      usage_scope in SampleType query: True  → 命中 0
MaiLIMS   usage_scope in SampleType query: True  → 命中 13
InnoCare  usage_scope in SampleType query: True  → 命中 13
```

三个站点被污染程度完全一致，唯一差别是 Care 建了那个索引 —— 变量是索引，
不是 core。修法就是给该 widget 加 `base_query={}`，一行。

**机器判据**：`lint_addon.py` 的 `E16_WIDGET_QUERY_LEAK` /
`W16_WIDGET_QUERY_LEAK`。传了 `query=` 没传 `base_query=` 时：

- query 含**通用键白名单之外**的键（或 query 不是字面量 dict，无法判定）→ **ERROR**
- query 只含通用键（`sort_on` / `sort_order` / `sort_limit` / `portal_type` /
  `is_active` / `is_received` / `review_state`）→ **WARN**

拿出事前的代码回测过：`ec92400` 版本的 `analysisrequest.py` 第 488 行准确报
ERROR、非通用键 `usage_scope`——这条规则会在重启前拦下那次事故。

**排查提示**：怀疑中招时，先打开任意样品详情页把污染触发出来，再看
`ar_add` 页面各控件的 `data-query`。判断某个键是不是真索引，**不要**用
jsonapi（它对 `is_active` 等有自己的处理，`=true` 和 `=false` 会返回相同结果，
根本区分不了），要读活 catalog 的索引表：
`/<site>/senaite_catalog_setup/manage_catalogIndexes`。
`senaite.core` 源码里的 `INDEXES` 是**出厂定义**，各站 ZODB 里的实际索引可能
被 addon 改过。

---

### R13. `except` 里不许重复刚刚失败的那个调用；Py2 转字符串一律用安全函数

**规则**：两条，第二条是第一条的常见成因。

1. **`except` 分支不许再调用刚在 `try` 里失败的那个函数。** 兜底路径要么换一种
   做法，要么就直接接受失败 —— 重复一遍必然再抛一次，而这次没人接。
2. **Python 2 下把可能含非 ASCII 的值转成字符串，一律用 `_safe_text()`
   之类的安全函数，不要用 `str()`。**

```python
# ✗ 错：兜底重复了刚失败的 str()，第二次没人接 —— 整页 500
try:
    parsed = json.loads(str(value))          # UnicodeEncodeError
except (ValueError, TypeError):              # 接住了（它是 ValueError 的子类）
    value = json.dumps([str(value)])         # ← 再抛一次，冒到 publisher

# ✓ 对：先安全转换一次，try/except 只负责"是不是 JSON"
text = _safe_text(value)                     # 见 patches.py:798
try:
    parsed = json.loads(text)
    ...
except (ValueError, TypeError):
    value = json.dumps([text])
```

**为什么 `except (ValueError, TypeError)` 会接住编码错误**：
`UnicodeEncodeError` → `UnicodeError` → **`ValueError`**。所以它看着像"只接
解析失败"，实际把编码失败也吞了 —— 然后兜底再炸一次。

**这一族在本环境已经出过三次**（`maitux.calcenhance/patches.py`）：

| 时间 | 位置 | 表现 |
|---|---|---|
| 早期 | listing 的 `get_formatted_interim` | 已修 |
| 2026-08-26 | 报告渲染的 `format_interim` / `format_supsub` | **整份 PDF 生成不出来**；实测 MaiLIMS 23 个字段、InnoCare 8 个、Care 6 个命中 |
| 2026-09-07 | `patched_folderitem` 的 `calculatedlist` 分支（PR #48） | 分析项**提交后**整个 `manage_results` 页面 500，AS-Grouped 与 Classic 都打不开 |
| 2026-09-07 | **同一处的另一半**（PR #50） | 修掉崩溃**不等于修好**：兜底仍把显示文本包成 `json.dumps([text])`，于是**撤回后**那些计算列渲染成 `["1.0\n1.0"]` / `["—\n—"]` 这样的裸数组。#48 只是把「崩」换成了「显示垃圾」 |

### R13b. 「不可编辑」时 core 会把值换成显示文本 —— 别把它当数据

这是上面那张表最后两行的共同成因，单独拎出来，因为它**同时**是崩溃和数据错乱的源头：

```python
# bika/lims/browser/analyses/view.py, _folder_item_calculation
if not is_editable:
    interim_field["value"] = interim_formatted     # ← 不再是 JSON！
```

**存的值**是 `json.dumps` 出来的、ASCII 安全的数组；**显示文本**两者都不是 ——
`list` 用 `", "` 连接、`calculatedlist` 用 **`"\n"`** 连接（见
`patched_get_formatted_interim`）。所以任何在 `folderitem` 之后读 `item[kw]["value"]`
的代码，拿到的东西**取决于该分析项能不能编辑**。

两个必须遵守的推论：

1. **别对它做 `str()`** —— 它可能含中文或 em dash（R13 第 2 条）
2. **解析失败时别把它包成数组** —— 它是显示文本，不是数据。包了就会得到
   `["1.0\n1.0"]` 这种假单元素数组，控件再原样渲染出来

`list` 分支一直是对的（注释写着 *Already formatted display text — keep as-is*），
`calculatedlist` 分支曾经是错的 —— **同一个函数里两个分支对同一种情况处理相反**，
这种不一致本身就是信号。

**要真正拿到数据而不是显示文本**，得绕过这次替换去读对象：
`maitux.worksheet` 的 `_raw_interim_values()` 就是干这个的，它的 docstring 记着
为什么必须这么做（否则多行列在评审阶段会塌成一行）。

第三次尤其说明这一族多难发现：**存的值是 ASCII 安全的**（`json.dumps` 默认
`ensure_ascii=True` 会把中文转义），触发它需要 core 在"分析项不可编辑"时把值
换成**格式化显示文本**：

```python
# bika/lims/browser/analyses/view.py, _folder_item_calculation
if not is_editable:
    interim_field["value"] = interim_formatted     # ← u"—<br/>—" 或中文，不是 JSON
```

所以它只在**提交之后**才现形 —— 潜伏了整整两周没人撞到。

**★ 只 `pass` 掉的兄弟同样有害，只是不崩。** `patches.py` 里另有 7 处
`json.loads(str(...))` 的 `except` 是 `pass`/吞掉：不会 500，但**整列会被静默
丢弃**。2026-09-07 用真模块实测（`scratchpad/s1919/test_ascii_drop.py`）：

| 位置 | escaped CJK | **literal CJK** |
|---|---|---|
| `3492` 标量引擎收集器 | `20.0` | **丢 → `---`** |
| `3963` 数组引擎收集器 | `[20.0]` | **丢 → `["---","---"]`** |
| `1508` 跨 AS LOOKUP 收集器 | `[10.0, 20.0]` | **丢 → `["---"]`** |

它们目前**不触发**，因为线上 663 个有值的 list 字段里字面非 ASCII 的是 0 个 ——
也就是说 **"`json.dumps` 默认 `ensure_ascii=True`" 这件事现在是承重的，而且没人
显式声明过**。唯一的字面非 ASCII 生产者是 `patches.py:1221`
（`_normalize_list_value_once` 的最后兜底支，`ensure_ascii=False`），它在分析员
往 list 字段里直接打/粘中文时触发。

**写代码时的自查**：任何 `str(` 出现在可能含中文的值上就是嫌疑；任何 `except`
里出现和 `try` 里同名的调用就是嫌疑。

---

### R14. 注入外来 UI / 注册外来内容的适配器，必须 layer 门控

**规则**：包一旦声明了自己的 browser layer，凡是 `<subscriber>` / `<adapter>`
指向**外来**内容或视图接口（`senaite.*` / `bika.lims.*` / `plone.*`）的注册，
都必须门控到本包的 layer 上。两条通道，按适配签名里有没有 request 二选一：

```xml
<!-- 签名里有 request → ZCML 门控：把 IBrowserRequest 换成自己的 layer -->
<adapter
    name="workflow_action_xxx"
    for="senaite.core.interfaces.IWorksheets
         maitux.xxx.interfaces.IXxxLayer"     <!-- ← 不是 IBrowserRequest -->
    factory="..."
    provides="bika.lims.interfaces.IWorkflowActionAdapter"
    permission="zope.Public" />
```

```python
# 签名里没有 request（IListingViewAdapter 是 (view, context)）
# → ZCML 无处插 layer，只能运行时门控
def before_render(self):
    if not IXxxLayer.providedBy(self.view.request):
        return                               # ← 必须有，否则全站点泄漏
    ...
```

**理由**：`package-includes/` 里的 slug 一进去，ZCML 就是**全局加载**的，
跟 profile 装没装、跟哪个站点毫不相干。`browser:page` 有 `layer=` 属性所以
大家都记得写；`subscriber` / `adapter` **没有** `layer=` 属性，门控只能靠上面
两条通道 —— 于是最容易漏，而漏了以后**没装这个 addon 的站点照样吃到注册**。

**事故实例**（`maitux.instrument_acquisition`，2026-09-07 测试时发现）：
Worksheets 列表底部的「仪器采集」按钮由 `IListingViewAdapter` 订阅者注入，
`before_render()` 无条件往 `review_states` 里塞 `custom_transitions`，
结果**四个站点全都显示这个按钮**，包括从未装过该 addon 的。
同一个 `browser/worksheet/configure.zcml` 里两个 `browser:page` 都规规矩矩写了
`layer=`，唯独 subscriber 和 adapter 没有 —— 而且注释还把它当成优点：

```
不覆盖视图、不声明 permission、不依赖 browser layer，
避免 Zope 4 的 ZCML 加载顺序 / 权限注册冲突问题
```

作者是**刻意**绕开 layer 去躲 R1 那类加载顺序问题的。躲开的办法是对的
（`IListingViewAdapter` 确实不该覆盖视图），但代价被忽略了：不依赖 layer
＝ 不受 layer 约束 ＝ 全局生效。R1 的正解是补
`<include package="senaite.core.permissions" />`，不是弃用 layer。

**机器判据**：`lint_addon.py` 的 `E17_UI_INJECTION_UNGATED` /
`W17_FOREIGN_ADAPTER_UNGATED`。前置条件是**本包声明过 layer**（没 layer 的包
无从门控，不报）：

- `<subscriber>` 的 `provides` 是 UI 注入类接口（`IListingViewAdapter` 等），
  `for=` 里没 layer，且工厂模块里也搜不到 layer 名 → **ERROR**（必现泄漏）
- `<adapter>` / `<subscriber>` 的 `for=` 是「外来内容接口 + 任意请求接口」
  （`IBrowserRequest` / `IHTTPRequest` / `IRequest`）→ **WARN**
  （要够到它得手工构造 POST，不像上一条那样打开页面就看见）

三条收窄条件，缺一条就会误报（初版打 17 处、其中 15 处是误报）：
① 本包必须声明过 layer；② `for=` 里出现 layer 即算已门控；
③ 只认指向外来内容接口的，`for="*"` 配自有动作名不报。
自测在 `lint_addon.py` 的 R14 段注释里有说明，合成用例覆盖这三条各自的边界。

**排查提示**：怀疑某个按钮/菜单泄漏时，**别看 profile 装没装** —— 那是无关变量。
直接去没装该 addon 的站点打开对应列表页：能看见就是 ZCML 全局注册没门控。
反过来，`prefs_install_products_form` 里显示"未安装"却仍有功能出现，
基本都是这一条。

---

## 附：新建 addon 检查清单

- [ ] `package-includes/` 下 configure + overrides **两个** slug 都建了
- [ ] 用到 senaite 自定义权限的注册，写在 `overrides.zcml`
- [ ] 覆盖原生同名组件的注册，写在 `overrides.zcml`
- [ ] 跨 addon 同接口同名 adapter，全部只落在 `overrides.zcml`（R5b）
- [ ] `setup.py` 分发名与代码目录名大小写一致；不手动 include 已配 autoinclude 入口点的包（R5c）
- [ ] 不新增、不提交、不手工维护仓库里的 `custom-addon.cfg`（R5d）
- [ ] `setup.py` 有正确的 `name=`（egg 名由它生成，不是目录名），目录直接放在 `addons/customers/` 一级下（R5d）
- [ ] `registerProfile` 声明的每个目录都真实存在且含 `metadata.xml`
- [ ] 有 `profiles/uninstall/`；**若属合规类要豁免，则 `upgrades/` 已建起并验证过一次，且 README 首段写明理由（R4b）**
- [ ] 包在 ZODB 之外若有状态（自建表 / 外部文件），迁移机制幂等且不只挂在站点级 upgrade step 上（R4b）
- [ ] 新增 profile 文件后，部署文档写明"需重跑 profile"
- [ ] 部署说明区分了"重启"与"重启 + 硬刷新"
- [ ] 每项功能给出了可观测的验证判据
- [ ] 静态数据维护型 addon 只提供内容/列表维护入口，不往附加产品配置区注册 configlet（R11）
- [ ] 引用控件（ReferenceWidget / QuerySelectWidget）传了 `query=` 的地方，都同时传了 `base_query={}`（R12）
- [ ] 指向外来内容/视图接口的 `subscriber` / `adapter` 都做了 layer 门控：签名里有 request 的换成自己的 layer，没 request 的（`IListingViewAdapter`）在工厂里判 `providedBy(request)`（R14）
