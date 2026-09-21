# MaiLIMS 动态字段管理 Add-on 需求文档

| 项 | 值 |
|---|---|
| 包名（建议） | `maitux.dynamicfields` |
| 存放位置 | `2.7.0-maitux1/addons/common/maitux.dynamicfields` |
| 目标环境 | SENAITE 2.7.0 / Plone 5.2 / Python 2.7 |
| 发布方式 | 编译进镜像，**随镜像发布，站点侧无需安装** |
| 版本 | v1 草案 |
| 日期 | 2026-09-20 |

---

## 1. 背景与目标

### 1.1 现状问题

目前每次客户提出"加几个字段"的需求，都要新开一个 add-on：`INNOCARE.arextension`
（样品字段）、`INNOCARE.labid`（实验室字段）、`maitux.worksheetfields`（工作表字段）……
每个都要重复一遍同样的样板：

- 判断目标类型是 Archetypes 还是 Dexterity，选不同的扩展机制；
- 写 schemaextender 或 behavior、写 profile、写 ZCML、写浏览器层；
- 写四份 locale 目录（`en` / `zh` / `zh-cn` / `zh_CN`）做中文标签；
- 部署要改配置、重建镜像、重启容器、后台装 profile。

结果是：**加一个字段的成本 ≈ 开一个新包的成本**，而且包与包之间产生依赖，
迁移和裁剪都变困难。

### 1.2 目标

提供一个**平台级**的字段管理能力：管理员在后台配置页上完成字段的增删改，
**不写代码、不重建镜像、不重启容器**。

### 1.3 非目标

- 不追求覆盖 SENAITE 全部 portal_type（见 §3.1 白名单）；
- 不追求字段自动出现在 SENAITE 所有定制界面（见 §9.1）；
- 不做字段级工作流、不做字段级审计（审计由 `maitux.auditjournal` 负责）。

---

## 2. 关键约束：随镜像发布、无需安装

这是本 add-on 与仓库内所有既有 add-on **最大的不同**，它决定了整个架构。

### 2.1 为什么"无需安装"是一个强约束

实测结论（已记录在 `common-addons.cfg` 注释中）：

> `[plonesite] profiles` 那一段是**死代码**。`buildout.cfg` 在 `extends` 之后用
> 普通赋值重新定义了 `profiles =`，于是 `common-addons.cfg` 里写的 6 个 profile
> 一条都进不去。**新建站点不会自动装任何 add-on 的 profile。**

也就是说，本 add-on **拿不到 GenericSetup profile 这个执行时机**。凡是靠 profile
才能生效的东西，全部不可用。

### 2.2 由此导出的架构约束（必须遵守）

| 常规做法 | 本 add-on | 替代方案 |
|---|---|---|
| `browserlayer.xml` 注册浏览器层 | **禁止** | 不使用浏览器层；本包不覆盖任何原生视图，不需要层 |
| `registry.xml` 预置配置记录 | **禁止** | 配置存 portal annotation，首次访问时惰性初始化 |
| `controlpanel.xml` / `actions.xml` 注册入口 | **禁止** | 配置页入口用 viewlet 挂到 Setup 页（纯 ZCML） |
| `catalog.xml` 建索引 | **禁止** | 用户在配置页勾选时，由代码运行时创建索引 |
| `setuphandlers.py` 调 `api.enable_behavior()` 写 FTI | **禁止** | 用 `IBehaviorAssignable` 适配器声明行为归属，**不写 FTI** |
| `profiles/uninstall/` 卸载 | **不提供** | 回滚方式见 §8.4 |

**`IBehaviorAssignable` 这条是关键**：仓库里已有现成范例
`addons/customers/INNOCARE.labid/src/INNOCARE/labid/assignable.py`。它通过注册一个
自定义的 `IBehaviorAssignable` 适配器，让指定类型"认领"某个 behavior，
全程纯 ZCML + 代码，**不写数据库、不需要 profile**。本 add-on 照此实现。

### 2.3 ZCML 加载顺序

`common/` 下的包靠 `z3c.autoinclude.plugin`（`target = plone`）自动加载，
**不写显式 slug，加载顺序不保证排在 senaite.core 之后**。

因此（规则 R1）：

- 本包 ZCML 中若引用 senaite.core 的自定义权限，必须在自己的 `configure.zcml`
  顶部写 `<include package="senaite.core.permissions" />`；
- **更推荐的做法：本包不使用任何 senaite.core 自定义权限**，配置页一律用 Plone
  原生的 `cmf.ManagePortal` 保护。这样从根上绕开 R1 这颗雷。

### 2.4 发布流程

1. 把 `maitux.dynamicfields/` 目录放进 `2.7.0-maitux1/addons/common/`；
2. 在 `common-addons.cfg` 的 `develop +=` 和 `eggs +=` 各加一行；
3. 重建镜像。

关于重建成本：当前 Dockerfile **已是 PR #23 之后的分层版本**（`Dockerfile:182`
有"第二段 buildout"，`common-addons.cfg` 在 `Dockerfile:186` 才 COPY 进来），
所以**改 `common-addons.cfg` 只打到最后几层，几分钟即可**，不是全量重建。

4. 容器启动后，管理员直接访问配置页即可使用。**站点后台不需要安装任何东西。**

---

## 3. 范围

### 3.1 支持的目标对象

SENAITE 2.7.0 的内容类型横跨 Archetypes 与 Dexterity 两套机制，本 add-on
**必须同时支持**。以下清单依据镜像内 senaite.core 2.7.0 的 FTI `meta_type` 实测得出。

**第一优先级（v1 必须支持）**

| 对象 | 业务名 | 机制 |
|---|---|---|
| AnalysisRequest | 样品 / 检验申请 | **AT** |
| Client | 客户 | **AT** |
| Batch | 批次 / 项目 | **AT** |
| AnalysisService | 检验项目 | **AT** |
| Instrument | 仪器 | **AT** |
| Method | 方法 | **AT** |
| Worksheet | 工作表 | DX |
| SampleType | 样品类型 | DX |
| SamplePoint | 采样点 | DX |
| Contact | 客户联系人 | DX |
| Supplier | 供应商 | DX |

> **注意：第一优先级里 6 个是 AT。** AT 那一半不是可选项，它承载了最高价值的目标。

**第二优先级（v1 可支持，按实现成本决定）**

| 对象 | 业务名 | 机制 |
|---|---|---|
| LabContact | 实验室人员 | AT |
| AnalysisSpec | 结果规格 | AT |
| ARTemplate | 样品模板（旧） | AT |
| ReferenceSample / ReferenceDefinition | 标准物质 / 定义 | AT |
| InstrumentCalibration / Certification / Validation / MaintenanceTask | 仪器校准 / 证书 / 验证 / 保养 | AT |
| Attachment | 附件 | AT |
| SampleTemplate | 样品模板（新） | DX |
| WorksheetTemplate | 工作表模板 | DX |
| AnalysisProfile | 分析套餐 | DX |
| Laboratory | 实验室信息 | DX |
| Calculation | 计算公式 | DX |
| Department / AnalysisCategory | 部门 / 检验分类 | DX |
| StorageLocation | 存储位置 | DX |
| SampleContainer / SampleCondition / SamplePreservation / SamplingDeviation / SampleMatrix / SubGroup / ContainerType | 各类字典 | DX |

**明确排除（不得出现在选择列表中）**

| 对象 | 排除原因 |
|---|---|
| Analysis / DuplicateAnalysis / ReferenceAnalysis / RejectAnalysis | 数量级为每样品×每检测项，一年百万量级；且只经 `senaite.app.listing` 渲染，不读 schema，加了也看不见 |
| BikaSetup | 已被 DX 的 `Setup` 取代，属迁移遗留 |
| ARReport | 已被 DX 的 `ResultsReport` 取代 |
| 全部文件夹类型（`AnalysisServices` / `Instruments` / `Methods` / `SampleTypes` / `ClientFolder` / `BatchFolder` / `Samples` / `Worksheets` …） | 容器对象，无业务字段需求 |
| Plone_Site | 非业务对象 |

### 3.2 新旧类型并存的陷阱

以下三对在 `portal_types` 里**两个 FTI 都真实注册着**，属 AT→DX 迁移中途产物：

- `Setup`(DX) ↔ `BikaSetup`(AT)
- `SampleTemplate`(DX) ↔ `ARTemplate`(AT)
- `ResultsReport`(DX) ↔ `ARReport`(AT)

**要求**：类型清单必须从 `portal_types` 实际读取并标注机制，**不得手写死清单**；
对上述已废弃的一侧做显式屏蔽或"已废弃"标记，防止用户选错后字段死活不显示。

另有几处反直觉的机制归属，配置页上必须明确标注：

- `Instrument` 是 **AT**，但 `InstrumentType` / `InstrumentLocation` 是 **DX**
- `Contact`（客户联系人）是 **DX**，但 `LabContact`（实验室人员）和
  `SupplierContact`（供应商联系人）是 **AT**
- `Supplier` 是 **DX**，但它下属的联系人是 **AT**

### 3.3 支持的字段类型（v1）

| 类型 | 说明 |
|---|---|
| 单行文本 | |
| 多行文本 | |
| 整数 | |
| 小数 | 可配小数位 |
| 日期 | |
| 日期时间 | |
| 布尔 | 是 / 否 |
| 固定选项（Choice） | 单选 / 多选，选项由配置页维护 |
| 对象引用（Reference） | 单值 / 多值，按 portal_type 选择 |

**v1 不做**：DataGrid（表格型）、计算字段、文件 / 图片上传、富文本。
这四类的实现复杂度合计超过上面九种之和。

---

## 4. 功能需求

### FR-1 配置页

- **入口**：SENAITE 后台 Setup 页面上出现"动态字段管理"入口。
  实现方式为 viewlet（纯 ZCML 注册，不写 `actions.xml`）。
- **权限**：`cmf.ManagePortal`。非管理员访问返回 403。
- **风格**：与 SENAITE 原生控制面板一致（Bootstrap 4 + senaite 配色，
  照现有控制面板页模板走）。
- **语言**：配置页自身的界面文案走常规 `.po` / `.mo` 双语（中 / 英）。

### FR-2 对象类型列表

- 列出 §3.1 白名单内的类型，**从 `portal_types` 实测读取**；
- 每个类型显示：业务名（中 / 英）、portal_type、**机制标注（AT / DX）**、
  已添加的自定义字段数量；
- 支持按名称搜索过滤。

### FR-3 展开查看对象的全部字段

选中一个类型后，展开显示该类型**当前的全部字段**，包括原生字段和自定义字段。

- **DX** 取值路径：遍历主 schema + 全部 behavior schema；
- **AT** 取值路径：从 archetype 注册表读该类型的 schema。

每个字段显示：字段名、字段类型、标签、**来源**（原生 / 其它 add-on / 本包添加）、
是否必填。

**来源标注是本页最重要的信息**，它直接决定哪些字段可删（见 FR-5）。

### FR-4 添加字段

见 §5 的完整配置项清单。

约束：

- 字段名必须是 ASCII、小写 + 下划线，**创建后不可修改**；
- 必须校验字段名冲突：与该类型的原生字段、其它 add-on 的字段、
  本包已有字段、以及保留名（`id` / `title` / `UID` / `created` / `modified` /
  `portal_type` / `path` 等）都不得重复；
- 保存后**立即生效**，不需要重启容器。

**入口与导航（不跳新页）**：

- 添加字段用**同页右侧抽屉**，不跳转到新页面；
- 从**对象页**（按对象浏览 tab）进入：目标对象由左侧当前选中项带入并锁定，不给下拉框。
  理由：目标对象决定了字段名冲突校验的范围、AT / DX 生成路径、以及「可编辑工作流状态」能列出哪些状态——
  填到一半换对象，前面填的全得重算；
- 从**全部自定义字段 tab** 进入：没有当前对象上下文，抽屉第一项为**必选的目标对象下拉框**，选定后才能填后续内容；
- 保存后**回到进来时那一页**（对象页或总览页），新增行出现在「本包添加」分组里，顶部给状态消息。
  按仓库既有做法（参考 `maitux.worksheetfields` 的保存路径），整页 POST + 回原页 + 门户状态消息即可，不必上 AJAX。

### FR-5 删除字段：原生字段不可删

**这是结构性保证，不是 UI 层的校验。**

本包添加的字段，在物理上就与原生 schema 分离：

- DX 侧位于本包独立的 behavior schema 内；
- AT 侧位于本包 extender 返回的字段列表内。

因此"可删除"的集合天然只有配置库里登记过的那些。原生字段和其它 add-on 的字段
**在界面上根本渲染不出删除按钮**，不需要额外的白名单或校验去防。

删除时的处理：

- 从配置库移除定义 → schema 重新生成 → 字段消失；
- 对象上已写入的属性值：**v1 保留不清理**（快速、无风险），并在删除确认框中
  明确提示"已有数据将保留但不再显示"；
- 若该字段建过索引 / metadata 列：**必须同步摘除**，否则目录里留下死索引；
- 提供一个可选的"彻底清理残留数据"动作（独立按钮，二次确认，长任务）。

### FR-6 多语言标签（本包自闭环，不依赖 senaite.core）

**标准的 gettext 路线在这里走不通**：本包的字段是运行时创建的，不可能预先准备
`.po`；运行时写 `.po` / `.mo` 也没用——已注册的 catalog 不重新加载，
按规则 R8 需要重启容器才生效。

**实现方式：注册本包自己的 `ITranslationDomain` utility。**

- 翻译域在 Zope 里就是一个实现了 `translate()` 的 utility，接口并未规定必须查
  `.mo`。本包注册一个域（如 `maitux.dynamicfields`），其 `translate()` 转而查
  本包的配置库；
- 字段的 `title` / `description` 不给纯字符串，给
  `Message(msgid, domain="maitux.dynamicfields", default=...)`；
- 回报：z3c.form 标签、AT widget label、模板 `i18n:translate`、控制面板——
  整条渲染链自动正确，这些渲染器一行都不用改。本包只用到 `zope.i18n`，
  与 senaite.core 无关。

**必须遵守的两条硬约束：**

1. **不得在构建 schema 时把当前语言的文案烤进 `title`。**
   schema 是构建一次然后缓存的，不是每请求构建。烤进去的后果是
   "第一个发起请求的人的语言变成之后所有人看到的语言"，且开发机上单人测试
   百分之百测不出来。`Message` 是延迟求值对象，查表发生在渲染那一刻、
   带着当时那个 request 的语言，这才是正确的做法。

2. **msgid 和 `default` 一律用 ASCII 英文，中文只活在配置库里。**
   两个理由：漏翻的地方至少显示正常英文而非乱码；更要紧的是 Py2 下非 ASCII 的
   msgid 撞上 `str()` 或 ascii 解码会直接抛异常
   （参见 `INNOCARE.arextension/patches.py` 里专门写的 `UnicodeDecodeError` 兜底）。

**附带收益**：schema 里存的只是 msgid，文案在库里，**改标签实时生效，
不需要触发 schema 重建**；只有增删字段、改字段类型才需要失效 schema 缓存。

**语言归一化**：入库统一一种写法；查表前把请求语言 lower + 连字符 / 下划线互换，
查不到退到基础语言（`zh-cn` → `zh`），再退站点默认，最后兜底显示字段名。
**绝不允许标签渲染成空白。**（这一段逻辑写一次，即可替代现有每个包铺四份
`en` / `zh` / `zh-cn` / `zh_CN` 目录的做法。）

### FR-7 前端显示控制

见 §5.2。核心是让管理员逐项决定字段在哪些界面出现，而不是"加了就到处都是"。

**能力边界见 §9.1，必须在配置页上对用户明示。**

### FR-8 检索支持

- 可选择为字段创建目录索引（可搜索 / 可过滤）与 metadata 列（列表显示的前提）；
- 索引由代码在用户勾选时运行时创建，**不走 `catalog.xml`**；
- 创建后提供"重建该索引"动作（对存量数据补索引，长任务，带进度提示）。

### FR-9 配置导出 / 导入

因为不走 GenericSetup，配置**不会**随 profile 导出导入，所以必须自带：

- 导出全部字段定义（含多语言文案、选项列表）为 JSON 文件下载；
- 导入 JSON，支持"合并"与"覆盖"两种模式，导入前显示差异预览；
- 用途：开发环境配好 → 导到生产；多站点之间同步配置。

---

## 5. 添加字段时的配置项清单

### 5.1 基础信息（必填）

| 配置项 | 类型 | 默认 | 说明 |
|---|---|---|---|
| 目标对象 | 只读 / 下拉 | — | 入口决定：从对象页进入时由当前选中类型**带入并锁定**（只读）；从「全部自定义字段」页进入时为**必选下拉框**。两种形态都显示业务名 + portal_type + **AT / DX 标注**，且**保存后不可更改** |
| 字段名 | 文本 | — | ASCII、小写 + 下划线；全局唯一；**创建后不可修改** |
| 字段类型 | 下拉 | 单行文本 | §3.3 九选一；**创建后不可修改**（需改则删除重建） |
| 中文标签 | 文本 | — | 界面上显示的中文名 |
| 英文标签 | 文本 | — | 至少中英填一个；留空则回退到另一种语言 |
| 中文说明 | 多行文本 | 空 | 字段下方的帮助文字 |
| 英文说明 | 多行文本 | 空 | |

> 语言输入框的数量应按**站点实际启用的语言**动态生成，不写死中 / 英两种。

### 5.2 前端显示控制

| 配置项 | 类型 | 默认 | 说明 |
|---|---|---|---|
| 在编辑表单显示 | 开关 | 是 | 关闭后字段仍存在，但只能由接口 / 脚本写入 |
| 在查看页显示 | 开关 | 是 | |
| 在列表页作为列显示 | 开关 | 否 | 需先勾选"创建 metadata 列"，否则此项置灰 |
| 列表页默认可见 | 开关 | 否 | 关闭时该列折叠在"显示更多列"里 |
| 在检验报告中显示 | 开关 | 否 | **二期**，v1 置灰并标注"暂未支持" |
| 显示分组 | 下拉 / 新建 | 默认 | 对应 fieldset / schemata |
| 组内排序 | 数字 | 自动 | 同组内按此升序排列 |

### 5.3 数据约束

| 配置项 | 类型 | 默认 | 说明 |
|---|---|---|---|
| 是否必填 | 开关 | 否 | **对已有数据的对象要谨慎**：开启后旧对象编辑时会被强制补填 |
| 默认值 | 随类型变化 | 空 | |
| 是否只读 | 开关 | 否 | 界面只显示不可改，仅接口 / 脚本可写 |
| 可编辑的工作流状态 | 多选 | 不限 | 留空 = 任何状态可改；例如样品可限定为"仅 sample_due / sample_received" |

### 5.4 类型专属配置

**固定选项（Choice）**

| 配置项 | 说明 |
|---|---|
| 选项列表 | 每行一项：**稳定 key（ASCII）** + 中文标签 + 英文标签 |
| 是否多选 | 单选 / 多选 |

> **设计红线：存储值必须是稳定 key，显示文案才是翻译出来的。**
> 一旦让人把中文标签直接存进对象，这份数据就永远翻译不了了，
> 且索引、导出、统计全部锁死在中文上。此项必须第一天定死，事后改要迁数据。

**对象引用（Reference）**

| 配置项 | 说明 |
|---|---|
| 允许的对象类型 | 多选 portal_type |
| 是否多值 | 单值 / 多值 |
| 是否包含非激活对象 | 默认否；追溯类场景（如已过期批次）需要开启 |
| 额外查询条件 | 高级项，可留空 |

**数值（整数 / 小数）**

| 配置项 | 说明 |
|---|---|
| 最小值 / 最大值 | 可留空 |
| 小数位 | 仅小数类型 |
| 单位后缀 | 仅显示用，不参与存储 |

**文本（单行 / 多行）**

| 配置项 | 说明 |
|---|---|
| 最大长度 | 可留空 |
| 校验正则 | 高级项，可留空 |
| 校验失败提示（中 / 英） | 填了正则则必填 |

**日期 / 日期时间**

| 配置项 | 说明 |
|---|---|
| 是否允许未来日期 | 默认是 |

### 5.5 检索

| 配置项 | 类型 | 默认 | 说明 |
|---|---|---|---|
| 创建目录索引 | 开关 | 否 | 开启后字段可搜索 / 可过滤 |
| 索引类型 | 下拉 | 自动 | 按字段类型推荐，一般不用改 |
| 创建 metadata 列 | 开关 | 否 | 列表页显示的前提 |

### 5.6 权限（v1 可选 / 二期）

| 配置项 | 说明 |
|---|---|
| 可见角色 | 留空 = 所有能看该对象的人都能看 |
| 可编辑角色 | 留空 = 所有能改该对象的人都能改 |

---

## 6. 数据存储

| 项 | 方案 |
|---|---|
| 配置存储位置 | portal 上的 annotation（`PersistentMapping`）。**不用 `registry.xml`**，因为拿不到 profile 执行时机 |
| 配置结构 | 一条记录 = 一个字段定义，含目标类型、字段名、类型、各语言文案、全部开关 |
| **机制中立** | 记录中**不得**写入"这是 AT 字段"或"这是 DX 字段"。走哪条生成路径，由运行时查 FTI 的 `meta_type` 决定 |
| 字段值存储 | DX 存对象属性；AT 存 AttributeStorage。两者都是读不到时回落默认值，**添加字段不需要数据迁移** |

**"机制中立"这条的理由**：§3.1 那张 AT 表**每出一个 senaite 版本就会短一截**——
2.7 里 SampleType、SamplePoint、Supplier、Contact、Worksheet 都是刚从 AT 迁过来的，
可以预见 AnalysisRequest、Client、Instrument、AnalysisService 这几个大头迟早也会迁。

机制中立的好处：将来上游把 Client 迁成 DX，只需改生成路径的分支逻辑，
**客户已配好的字段定义一条都不用动**，只要写个数据搬家脚本把旧 AT 存储的值挪到
新 schema 下即可。反过来，如果机制写死在配置里，那就是上游每迁移一个类型，
所有客户站点都要改配置。

---

## 7. 非功能需求

### NFR-1 启动健壮性（最高优先级）

schema 是启动时构建的。**一条脏配置绝不允许让站点起不来。**

- 某条配置引用了已不存在的 portal_type、已卸载的引用目标、或无法解析的类型时，
  必须**跳过该条并记 error 日志**，不得抛异常；
- 配置页上对被跳过的记录显示醒目告警，并给出"删除"或"修复"操作；
- 验收方式：手工往配置库塞一条引用不存在类型的记录，重启容器，
  **站点必须正常启动**。

### NFR-2 缓存失效

- DX 有 schema 缓存，AT 的 schemaextender 也有按类型的 schema 缓存；
  配置变更后两边都必须失效；
- 仅改文案（FR-6）不触发 schema 失效——因为 schema 里只有 msgid。

### NFR-3 性能

- 配置页打开时间 < 2 秒（类型清单 + 字段内省）；
- 字段数量上限按**每类型 50 个、全站 500 个**设计，超过给出告警；
- schema 生成结果必须缓存，不得每请求重建。

### NFR-4 兼容性

- Python 2.7 / Plone 5.2 / SENAITE 2.7.0；
- 与仓库内既有 add-on 共存：本包**不覆盖任何原生视图**，不注册浏览器层，
  因此不参与 `reviewerassignment → instrument_acquisition → worksheetfields`
  那条层继承链，不会产生冲突；
- 若某字段名与既有 add-on（如 `INNOCARE.arextension`）已加的字段重名，
  FR-4 的冲突校验必须拦下。

---

## 8. 部署与运维

### 8.1 安装

无。随镜像发布，容器启动即生效。

### 8.2 升级

替换镜像即可。配置数据在数据库里，不随镜像走，升级不丢。

### 8.3 配置迁移

用 FR-9 的 JSON 导出 / 导入。

### 8.4 回滚

本包**不提供卸载 profile**（对应规则 R4b 的豁免情形），回滚方式：

1. 从 `common-addons.cfg` 摘掉两行 → 重建镜像 → 重启；
2. 已写入对象的字段值作为孤儿属性保留在数据库中，不影响站点运行；
3. 若建过目录索引，**回滚前**应先在配置页上逐个关闭索引开关，
   否则目录里会留下无人维护的死索引。

> 这一条必须写进发布说明：**先关索引，再回滚。**

---

## 9. 已知限制（必须对用户明示）

### 9.1 加了字段 ≠ 界面上一定看得见

这是本 add-on 最重要的能力边界。

**能自动生效的：**

- DX 类型的标准 `@@edit` / `@@add` 表单（z3c.form 按 schema 渲染）；
- AT 类型的 `base_edit` / `base_view`（按 schema + widget 渲染）。

**不会自动生效的**——SENAITE 把最关键的几个界面全部重写过，它们**不读 schema**：

| 界面 | 渲染依据 |
|---|---|
| 样品新建页 `ar_add2` | 字段清单写在代码里 |
| 样品 / 工作表顶部 `header_table` viewlet | 按配置好的字段列表渲染 |
| 全部列表页（`senaite.app.listing`） | 列来自 `self.columns` 字典，与 schema 无关 |
| 工作表结果录入页 `manage_results` 页头 | 手写模板 |

`INNOCARE.arextension` 除了字段定义还必须带一个 `patches.py`，正是因为光加字段，
样品新建页上根本不出现。

**结论**：v1 交付的是"schema + 存储 + 标准编辑 / 查看表单 + 可选列表列"，
**不是**"字段自动出现在 SENAITE 所有界面上"。

**二期方向**：为 `header_table` 和 `senaite.app.listing` 各做一个读同一份配置的
通用挂载点。这部分才是这个 add-on 真正值钱的地方，工作量也比字段生成那半更大。

### 9.2 Message 对象的泄漏点

凡是代码里对 `Message` 做 `str()`、或不经 translate 直接塞进 JSON 的地方，
出来的是 `default` 值而非翻译。SENAITE 里这种地方确实存在——
`INNOCARE.arextension/patches.py` 那个补丁就是为此打的（侧边栏对文件夹标题调
`translate(str)`，纯字符串没有 domain，只查 `senaite.core` 域）。

`senaite.app.listing` 把列标题序列化成 JSON 给前端，这条路上有没有先 translate
**需要实测**，漏了要为它单加一个小适配。

### 9.3 其它

- 字段类型创建后不可修改，需变更类型只能删除重建（数据不迁移）；
- 不支持字段级的历史版本 / 变更追溯（由 `maitux.auditjournal` 另行负责）；
- 多 ZEO 客户端部署时，schema 缓存失效需跨客户端传播；当前单容器部署不受影响。

---

## 10. 验收判据

依据规则 R9，每项须给出**可观测**信号。

| # | 检查点 | 预期信号 |
|---|---|---|
| 1 | 新镜像启动后，**不做任何安装动作**，访问 Setup 页 | 出现"动态字段管理"入口 |
| 2 | 非管理员账号访问配置页 | 403，不泄漏任何配置内容 |
| 3 | 类型列表 | 显示 §3.1 白名单类型，每个带 AT / DX 标注；`Analysis`、各文件夹类型、`BikaSetup` / `ARTemplate` / `ARReport` **不出现** |
| 4 | 展开 AnalysisRequest（AT） | 列出全部原生字段 + `INNOCARE.arextension` 已加字段，来源标注正确，**均无删除按钮** |
| 5 | 展开 Worksheet（DX） | 列出主 schema + 全部 behavior 字段（含 `maitux.worksheetfields` 的 `instruments` / `stock_batches`），来源标注正确 |
| 6 | 给 Client（AT）加一个文本字段，填中英标签 | 保存后**无需重启**；打开任一客户的编辑页，字段出现，中文站点显示中文标签 |
| 7 | 给 SampleType（DX）加一个 Choice 字段 | 同上；选项按当前语言显示；**存储值是 key 不是标签**（在 ZMI 或日志中核验） |
| 8 | 把站点语言切到英文 | 同一字段标签变英文，**且不需要重启，不需要清缓存** |
| 9 | 只修改标签文案后保存 | 实时生效；日志中**不出现** schema 重建记录 |
| 10 | 删除自建字段 | 字段从表单消失；对象上旧值保留；若建过索引，索引同步消失 |
| 11 | 字段名填 `title` 或填一个已存在的字段名 | 保存被拒绝并给出明确原因 |
| 12 | 勾选"创建索引"后重建 | 该字段可在对应列表页搜索 / 过滤到 |
| 13 | **脏配置容错**：手工塞一条引用不存在 portal_type 的记录，重启容器 | **站点正常启动**；配置页对该条显示告警；日志有 error |
| 14 | 导出 JSON → 清空配置 → 导入 | 字段定义与多语言文案完整恢复 |
| 15 | 两个浏览器分别用中 / 英登录，同时打开同一编辑页 | 各自看到各自语言的标签（验证 FR-6 的"语言烤进 schema"陷阱未发生） |

> 第 15 条是**单人测试测不出来**的，必须双会话验证。

---

## 11. 风险

| 风险 | 影响 | 对策 |
|---|---|---|
| 客户期望"加了字段就到处显示"，实际只在标准表单生效 | 验收争议 | 需求评审阶段就把 §9.1 讲清；配置页上对"在列表页显示""在报告中显示"两项给出明确说明文字 |
| 语言被烤进缓存的 schema | 生产上串语言，开发机测不出 | 强制走 `Message` + 自注册翻译域；验收第 15 条必须双会话验证 |
| Choice 存了中文标签而非 key | 数据永久锁死在一种语言，事后要迁数据 | 第一天在代码层强制 key 为 ASCII，界面上不给"用标签当值"的选项 |
| 脏配置导致站点起不来 | 生产宕机 | NFR-1；验收第 13 条 |
| 上游 senaite 把 AT 类型迁成 DX | 已配字段失效 | 配置机制中立（§6）；预留数据搬家脚本 |
| 回滚时忘记先关索引 | 目录留死索引 | 写进发布说明；配置页回滚指引 |

---

## 12. 待确认事项

1. **配置页入口位置**：挂在 SENAITE Setup 页，还是单独进 Plone 控制面板？
   （建议前者，与其它 maitux 模块一致。）
2. **第二优先级类型**是否纳入 v1，还是先只做第一优先级的 11 个？
3. **`senaite.app.listing` 列标题的翻译路径**需实测，结果决定 §9.2 是否要加适配。
4. **权限配置项（§5.6）**是否放进 v1。
5. 字段数量上限（NFR-3 暂定每类型 50 / 全站 500）是否合适。
