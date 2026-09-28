# maitux.stability

MAITUX 稳定性研究（Stability Studies）扩展，提供稳定性研究的基础字典（储存条件、包装规格）、稳定性计划模板、稳定性计划（含时间点/检验标准明细），以及任务看板驱动的样品放置、关联样品、创建样品等流程。

## 功能职责

- 内容类型（见 `src/maitux/stability/content/`）：
  - `StabilityStudies`：稳定性研究根容器（侧边栏入口）。
  - `StorageCondition` / `StorageConditions`：储存条件字典。
  - `PackagingSpecification` / `PackagingSpecifications`：包装规格字典。
  - `StabilityPlanTemplate` / `StabilityPlanTemplates`：稳定性计划模板（样品数量、预留数量、附件等；可一键从模板创建计划，也可复制已有计划）。
  - `StabilityPlan` / `StabilityPlans`：稳定性计划（起算时间 T0、存放数量、Plan Details 明细：包装规格/储存条件/放置方向/时间点/窗口期/检验标准或检验组合/检验数量/关联批次与样品）。
  - `StabilityTimepointTask`：时间点任务对象（由计划明细同步生成）。
  - `Task Board`：任务看板容器（自定义 layout）。
- 任务看板（`@@task_board`）：按计划明细展示时间点任务，支持状态筛选（全部/待放置/进行中/已完成）、计划搜索、按目标日期/窗口排序、逾期高亮与统计卡片，以及批量操作：样品放置、关联已有样品、创建样品。
- 复制计划（Copy Plan，`plan_copy.py`）：列表页勾选方案 → 「复制计划」→ 预填新建表单；
  复制计划字段与时间点明细（明细状态重置为"待放置"、清空样品与库存批次），
  名称后缀一律**只存英文 msgid** `Copy`，显示时按当前语言渲染
  （`title.localize_copy_suffix`，同时兼容历史数据里已经存成"副本"的名称）。
- 流程页面：
  - `@@sample_placement`：为待放置任务选择库存批次（引用 `maitux.stock` 的 `StockBatch`）。
  - `@@link_sample`：为任务关联已有样品（AnalysisRequest）。
  - `@@create_sample`：按任务明细（检验标准/检验组合、批次）创建样品并写回关联。
  - `@@create_plan`：从计划模板跳转到新建计划并预填模板字段/附件。
  - `@@plan_copy_defaults`：复制计划时的表单预填数据（明细已按复制规则清理）。
- 计划同步：`subscribers.sync_plan_timepoint_tasks` 将 Plan Details 与 `StabilityTimepointTask` 双向同步，支持创建/更新/删除。
- 词汇：放置方向（Upright/Inverted/Horizontal）、计划/明细状态、月份时间点等。

## 依赖

- `senaite.core` / `senaite.lims`
- **`maitux.stock`**（样品放置需引用 `StockBatch`，setup.py 已声明依赖）
- `plone.api`、`plone.supermodel`、`plone.namedfile`
- `zope.component`、`zope.interface`、`z3c.form`

## 安装注册（buildout）

```ini
[buildout]
develop += /opt/addons/customers/maitux.stability
eggs    += maitux.stability
[instance]
zcml    += maitux.stability
[plonesite]
profiles += maitux.stability:default
```

安装后自动创建 `stability_studies` 侧边栏入口，及其子表（储存条件 / 包装规格 / 稳定性计划模板 / 稳定性计划 / 任务看板）。

## 双语翻译（i18n）

本 addon 使用独立的 i18n 域 `maitux.stability`，全部用户可见文案（列表标题/列名/按钮、schema 字段、任务看板、流程页面、portal 消息、侧边栏菜单标题）均通过该域的翻译目录解析，支持界面语言在中英文之间切换。

- `configure.zcml`：`<i18n:registerTranslations directory="locales" />` 注册翻译目录。
- 翻译目录：`src/maitux/stability/locales/{en,zh,zh-cn,zh_CN}/LC_MESSAGES/maitux.stability.po`。
  ⚠️ **`.po` 入库、`.mo` 不入库**（仓库根 `.gitignore` 有 `*.mo`，原因见该文件顶部：
  `addons/customers` 是 bind mount，容器里重编译会写脏宿主机工作区），
  但**磁盘上必须有 `.mo`** —— 本环境没开 zope.i18n 自动编译，删了等于所有中文标签变英文。
  改了 `.po` 之后在本包目录跑：**`python tools/compile_mo.py`**（纯标准库 struct，Py2/Py3 通用，本包本轮补齐）。
- 侧边栏菜单标题回退：`INNOCARE.arextension` 的 `senaite.core.i18n.translate` 附加域回退列表已包含 `maitux.stability`。

**写文案的三条硬规矩**（违反任意一条都会"切了语言没反应"，而且不会报错）：

1. 界面上出现的英文一律写成 **英文文本 msgid**，中文只放 `locales/zh*`；msgid 必须 ASCII
   （`Select...` 而不是 `Select…`，否则 lint 判 E15）。
2. Python 里凡是要显示的文案，必须带**本包域**的 Message（`_ = stabilityMessageFactory`），
   或运行期用 `maitux.stability.i18n.translate_stability()`。
   schema 的 `title=` / `description=` / `label=` 尤其容易漏 —— 纯字符串 z3c.form 不翻译；
   列表的标题/列名/页签必须在**构造视图时**翻译好（渲染阶段不会再翻译）。
3. 模板要同时有 `i18n:domain="maitux.stability"` 和 `i18n:translate`；纯 `<script>` 里的文案
   用 `data-msg-*` 挂到元素上再让 JS 读，别直接硬编码。

## 更新说明（2026-09-22 · 复制计划 / 双语完善）

### 1. 复制计划（Copy Plan）

- 列表页新增「复制计划」按钮（`workflow_action_copy_plan`）+ `plan_copy.py` 统一实现复制规则：
  计划字段整体复制；时间点明细整体复制但**状态重置为"待放置"**、清空样品与库存批次关联
  （新方案必须重新排样）。
- 复制出的名称后缀**只存英文 msgid** `Copy`，显示时按语言渲染
  （`title.localize_copy_suffix`），并兼容历史数据里已存成「副本」的名称 ——
  否则"在中文站复制出来的方案"切到英文站会永远显示中文。
- 新增 `@@plan_copy_defaults` 供新建表单预填；后端兜底补明细时给出提示。

### 2. 双语完善（本轮重点）

此前"切英文还有中文 / 切中文还是英文"的根因有几类，逐个修掉：

- **消息工厂域**：`browser/view.py` 等模块原先用 `bika.lims` 域的 `_()`，
  我们的译文在 `maitux.stability` 域里查不到 —— 中文站直接落回英文。
  现在视图/列表/看板/动作页统一走 `translate_stability()`。
- **内容类型**：字段标题与词表切到 `stabilityMessageFactory`；
  `StabilityPlan`、`StabilityTimepointTask` 加 `TranslatableTitleMixin`
  （无请求时不翻译，保证安装/编目时索引到英文 msgid）。
- **时间点任务标题**：`TP 1 (3 Months)` 是生成时写死并存进 ZODB 的英文，
  按形态识别后按语言重建为 `TP 1（3 个月）`（`title.localize_task_title`）。
- **模板 i18n**：`sample_placement.pt` 整页此前**没有任何 i18n**；`task_board.pt` 的统计卡片、
  `Timepoint Tasks`、空态、`aria-label`、placeholder、三个批量按钮、JS 弹窗提示全部补齐
  （JS 文案改从 `data-msg-*` 读，避免译文里的引号破坏脚本）；
  `create_sample.pt` / `link_sample.pt` 的中文提示改成英文 msgid。
- **datagrid / 表单**：Plan Details datagrid 的 `Add row` 补 `i18n:translate`；
  计划模板表单里那段纯 JS 的 "Basic Information" 由 `viewlet.get_labels()` 翻译后挂在
  `<script data-msg-basic-information>` 上供 JS 读取。
- **R9b 合规**：`Select…` 里的 U+2026 改成 ASCII `Select...`（msgid 必须 ASCII）。
- **翻译目录**：四个语言目录共 123 条 msgid，用 AST 逐条比对 **0 缺失**；
  新增 `tools/compile_mo.py`（本包此前没有），改了 `.po` 就在包目录跑它重新生成 `.mo`；
  `python lint_addon.py --addon maitux.stability` 当前 **0 ERROR / 0 WARN**。

### 3. 部署提示（依赖 senaite.core 的一处译文修正）

`senaite.core` 的 `zh_CN` 目录把 `View` 错译成「示图」，方案模板页的 View 页签会显示它。
已在 `senaite.core` 侧改成「查看」，**这一处不在本 addon 内**：docker 部署的
`senaite.core` 由 buildout 从上游 fork 构建，需要把该改动一并推到 `senaite.core` 仓库
（`src/senaite/core/locales/zh_CN/LC_MESSAGES/senaite.core.po` + 重新编译 `.mo`），
否则方案模板页会一直显示「示图」。

## 更新说明（2026-08-31 · 双语翻译支持）

本次更新为该 addon 补充了完整的双语（中 / 英）翻译支持，遵循 `maitux.hazardcategories` 的 i18n 模式：

- `configure.zcml` 增加 `<i18n:registerTranslations directory="locales" />`。
- `__init__.py` 增加 `_` MessageFactory 别名（`maitux.stability` 域）。
- 全部 browser / content 模块的消息工厂由 `senaiteMessageFactory` 切换到本 addon 自有域（`from maitux.stability import _`），字符串按自身目录翻译。
- 新增中文翻译条目：列表标题/列名/状态页签（Active/Inactive/All）、任务看板（Expired/Pending Placement/In Progress/Completed、列头、搜索、批量按钮、TP 任务标题）、流程页面（Sample Placement / Link Existing Sample / Create Sample 及字段与提示）、schema 字段标题（时间点/窗口期/检验标准/检验组合/存放数量等）、portal 消息、文件夹/侧边栏标题（Stability Studies、Storage Conditions、Packaging Specifications、Stability Plan Templates、Stability Plans、Task Board 等），共 116 条 msgid。
- 模板补 `i18n:translate`：`task_board.pt`、`sample_placement.pt`、`create_sample.pt`、`link_sample.pt`、Plan Details datagrid；并修复了 `create_sample.pt` / `link_sample.pt` 中的乱码文本（原 GBK 乱码替换为可翻译的英文文案）。
- `setuphandlers.py` 的模块/子表标题改为 Message 对象，随界面语言翻译。
- 翻译目录 `locales/{en,zh,zh-cn,zh_CN}` 及**磁盘上已编译的 `.mo`**（`.mo` 不入库，见上）；重启实例即生效，无需重装 profile。

## 卸载

- 执行 `maitux.stability:uninstall` profile：仅从侧边栏移除 `stability_studies` 注册，不删除业务数据。

## 备注

- 任务看板直接读取计划（Plan）的 Plan Details 明细渲染，不依赖已生成的 Task 对象；Task 对象用于历史兼容与显式状态同步。
- 时间点按“月 × 30 天”计算目标日期，窗口期按天计算（`window_days`）。
- 样品放置 / 关联样品 / 创建样品页面均做服务端权限与状态校验。
