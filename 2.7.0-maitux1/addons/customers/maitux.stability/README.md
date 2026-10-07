# maitux.stability

MAITUX 稳定性研究（Stability Studies）扩展，提供稳定性研究的基础字典（储存条件、包装规格）、稳定性计划模板、稳定性计划（含时间点/检验标准明细），以及任务看板驱动的样品放置、关联样品、创建样品等流程。

## 功能职责

- 内容类型（见 `src/maitux/stability/content/`）：
  - `StabilityStudies`：稳定性研究根容器（侧边栏入口）。
  - `StorageCondition` / `StorageConditions`：储存条件字典。
  - `PackagingSpecification` / `PackagingSpecifications`：包装规格字典。
  - `StabilityPlanTemplate` / `StabilityPlanTemplates`：稳定性计划模板（样品数量、预留数量、附件等；可一键从模板创建计划，也可复制已有计划）。
  - `StabilityPlan` / `StabilityPlans`：稳定性计划（起算时间 T0、存放数量、Plan Details 明细：包装规格/储存条件/放置方向/时间点/窗口期/检验标准或检验组合/检验数量/关联批次与样品/**行标识 `detail_uid`**）。
  - `StabilityTimepointTask`：时间点任务对象（由计划明细同步生成，记同一个 `detail_uid`）。
  - `Task Board`：任务看板容器（自定义 layout）。
- 时间点行的增删（`timepoints.py` + `browser/edit.py`）：
  **任何方案（含进行中）都可以新增时间点行**；**只有「待放置」的行可以删除**，
  「进行中」「已完成」的行不允许删除（服务端拦下并提示，前端隐藏删除按钮）。
  明细行带稳定标识 `detail_uid`，删中间行/拖动排序都不会错位。
- 任务看板（`@@task_board`）：按计划明细展示时间点任务，支持状态筛选（全部/待放置/进行中/已完成）、计划搜索、按目标日期/窗口排序、逾期高亮与统计卡片，以及批量操作：样品放置、关联已有样品、创建样品。
- 复制计划（Copy Plan，`plan_copy.py`）：列表页勾选方案 → 「复制计划」→ 预填新建表单；
  复制计划字段与时间点明细（明细状态重置为"待放置"、清空样品与库存批次），
  名称后缀一律**只存英文 msgid** `Copy`，显示时按当前语言渲染
  （`title.localize_copy_suffix`，同时兼容历史数据里已经存成"副本"的名称）。
- 流程页面：
  - `@@sample_placement`：为待放置任务选择库存批次（引用 `maitux.stock` 的 `StockBatch`）。
  - `@@zero_point_candidates`：**0 点关联往期样品**（阶段 3）——候选查询 + 关联动作，
    看板的「关联已有样品」与登样页上零点行的入口都指向它（**唯一实现**）。
  - `@@link_sample`（全站样品下拉）、`@@create_sample`（按检验标准/套餐建样）**已删除**
    （分别被上面这个与 `@@generate_sample` 取代，访问旧地址是 404）。
  - `@@generate_sample`：**按样品模板登样**（阶段 2）——客户/样品类型/检验项取样品模板、
    联系人取方案，批量建样并回写明细（含 `generated_at` / `generated_by` 审计）。
  - `@@create_plan`：从计划模板跳转到新建计划并预填模板字段/附件。
  - `@@plan_copy_defaults`：复制计划时的表单预填数据（明细已按复制规则清理）。
- 计划同步：`subscribers.sync_plan_timepoint_tasks` 将 Plan Details 与 `StabilityTimepointTask`
  按 `detail_uid` 对账（新增行建任务、被删的待放置行删任务；进行中/已完成的任务**永不删除、不覆盖**）。
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

## 更新说明（2026-09-30 · 阶段 6a + 6b + 6c：方案状态、时间点过期、行作废）

> 这三轮的**详细说明在 `项目文档/稳定性模块/`**（口径、改动清单、真机踩坑、验证清单）：
> * 《方案状态与过期规则-需求确认稿》（需求定稿，实施的唯一依据）
> * 《方案状态与过期规则-阶段6a-实施说明》（工作流 / 三状态 / 冻结 / 留痕 / 审计基础设施）
> * 《方案状态与过期规则-阶段6b-实施说明》（过期规则 / 看板筛选 / 编辑页锁定 / 写点补审计 / 界面层冻结）
> * 《方案状态与过期规则-阶段6c-实施说明》（行作废 / 软删除 / C1 前置条件 / 任务标注）
>
> 这里只记**改这个包的人必须知道的五件事**。

### 1. ★ 方案状态是**工作流**，不是普通字段

`StabilityPlan` 从 `senaite_one_state_workflow` 改绑到
`senaite_stability_plan_workflow`（`in_progress` / `paused` / `terminated`）。
**读状态一律用 `automation.get_plan_state(plan)`**，判"能不能写"用
`automation.can_modify_plan(plan)` —— 直接读 `review_state` 会漏掉
`normalize_state()` 的"空 = 进行中"容错（存量方案在迁移跑到之前是空串）。

### 2. ★ 时间点"过期"是**计算状态**，判据只有一个

```
过期 ⟺ 今天 > 窗口结束日  且  这一行还没登样
唯一实现：sampleautomation.row_is_expired() / window_end()
对象层透出：automation.row_is_expired() / automation.window_end()
```

`detail_status` 词表**没有**第 5 个值，过期**不落库**（确认稿 2.2 定稿）。
四处（看板显示 / 登样预览 / 登样写库 / 到期扫描）+ 零点关联 + 编辑页行锁
**必须都走它**；自己写一遍 `target + timedelta(days=n)` 或 `now > target`
就会出现"看板说已过期、登样说能登"（`check_timepoint_expiry.py` 有逐处守卫）。
**注意两层语义不同**：纯逻辑层"读不到 `now` 就放行"，对象层"不传 `now` 就用现在"。

### 3. ★ 写操作必须接审计，且**写点台账**会盯着

登样 / 自动登样 / 关联 / 撤销 / 放置 五个写点都直接改字段 + `reindexObject()`，
**不触发修改事件、不产生快照** —— 必须显式调 `audit.record_write_back(...)`。
`check_audit_coverage.py` 会数每个文件的"写库点"并要求逐个接上（不接就红），
`sync_tasks`（派生数据）在"刻意不审计"清单里**有理由地**豁免。

### 4. ★ 新增自检：属性存在性由机器核对

`tools/checks/check_module_attrs.py`（AST）—— 6b 真机事故（看板 500：
`automation.window_end` 漏写，字符串守卫抓不住）之后加的。
**本地自检全绿 ≠ 页面能打开**：看板/编辑页这类渲染路径只有 HTTP 层才碰得到。

### 5. ★★ 行「作废」= 软删除：方案明细**只增不减**（阶段 6c）

用户"删行"不再真删：行留在方案里，被写上 **`voided_at` / `voided_by` /
`void_reason`** 三个**非 schema 标记键**（与 `revoked_*` 同类，进 `PRESERVED_FIELDS`），
**不新增 `detail_status` 取值**（状态词表与 8 处状态映射一字未改）。

* **两条入口**：编辑页 DataGrid 删行 = 快速作废（原因留空）；
  `@@void_point` 动作页 = 可填原因 + 二次确认（**推荐**）。
* **唯一写入口**：`voiding.void_plan_rows()`（一次只写一次 `plan_details` + 镜像任务 + 审计 `void_timepoint`）。
* **C1 前置条件**：行上有关联样品时，样品必须**已达终态**才允许作废
  （`plan_status.void_precondition`；`dispatched` 按未完成、读不到状态保守拦下）。
* **作废行**：看板默认隐藏（「已作废」筛选可看）、只读、任何操作都不再碰它
  （登样 `row_voided` / 关联 `link_row_voided` / 撤销 `revoke_row_voided` /
  到期扫描跳过桶 `row_voided`）、任务保留并标注、方案复制时跳过。
* ★ 两个**顺序陷阱**（改 `sanitize_submitted_rows` 前必读）：起点必须是
  "全部提交上来的行"（用 `pairing()` 当起点会**丢掉新增行**）；
  作废标记必须**最后**落（否则会被"锁定行还原"用原行盖掉）。
* ★ 作废三件套是**服务端专有字段**：客户端提交的值一律不认（防伪造绕过 C1、
  也防已作废的行被"洗白"）。
* ⚠️ **作废不可逆**（再作废不覆盖时间/人/原因）；要"恢复"请新增时间点。

### 6. ★★ 冻结必须做到**界面层**，不能只在写库时拒（2026-09-30 用户实测）

用户把一份方案点了「终止」之后问："终止的方案明细，不应该能进行操作 ——
我用管理员好像还能进行样品关联、样品放置，是不是没有做限制？"
**服务端 6a 起就拦了**（四条写库路径都拒），但**页面什么都没拦**：
看板的行照样能勾、行级「撤销」链接还在、关联页正常列出候选样品并给 Link 按钮、
放置页照常列出冻结方案的行（保存后只写 0 行，却报一句
"Updated 0 timepoint(s) to Placed."）。**用户看到的就是"没做限制"。**

现在判据（`automation.can_modify_plan` / `samplegeneration.plan_block_reason`）
在页面层也走一遍：冻结行 `disabled` + 三处横幅提示、行级动作链接不出现、
关联页 `can_link=False`（候选列表为空 -> Link 按钮随之 disabled）、
放置页把冻结方案的行摘掉、撤销页不给提交按钮。
`check_plan_status.py` 的 G 段逐处钉住（16 条）。

> 顺带补掉一个 i18n 真空：方案状态的四条文案写在**消息表字典**里，
> 而 `check_msgid_coverage.py` 只扫 `translate_stability(...)` 调用点，
> 于是**一条都没进 .po**（中文站上看到的是英文），而那个自检**只打印不返回退出码**，
> 漏译再多也报全绿。现已加消息表扫描 + 退出码，并做过反向验证。

---

## 更新说明（2026-09-30 · 阶段 5：收尾 —— 自检沉淀 + 编目兜底 + 权限门修复 + 运维交付）

本轮不加功能，清掉技术债并把验证/运维固化：

### 0. ★★★ 权限门修复：`check_permission()` 的权限名必须用 **title 形式**（改权限前必读）

**现象**：新建的 cron 专用账号（角色 `StabilityAdministrator`，rolemap 已授该权限）调
`@@generate_due_stability_samples` 得到 `403 refused: 'ManageSampleAutomation' permission required`。

**根因**：本包有两种权限名，之前**混用了**：

| 形式 | 字符串 | 谁认它 |
| --- | --- | --- |
| ZCML 的 **id** | `maitux.stability.permissions.ManageSampleAutomation` | `queryUtility(IPermission, ...)`、`plone.autoform` 的 `directives.write_permission()` |
| ZCML 的 **title** | `maitux.stability: Manage Sample Automation` | **站点权限映射（rolemap/角色管理）与 `checkPermission()`** |

`bika.lims.api.security.check_permission()` 内部**不做** `queryUtility`，它直接
`SecurityManager.checkPermission(name, obj)`；传 id 形式时映射里没有这个键 →
**非 Manager 用户一律 False**。admin 之所以一直"看起来正常"，是 **Zope 的
`ZopeSecurityPolicy` 对 Manager 角色硬编码放行** —— 前四个阶段全用 admin 验证，所以没照出来。

**修复**（`permissions.py`）：

```python
def permission_name(permission):
    """id 形式 -> Zope 真正认的权限名（= IPermission 的 title）；取不到就原样返回。"""
```

`browser/generation.py`、`browser/revoke.py`、`browser/controlpanel.py` 三处权限门改成
`check_permission(permission_name(ManageSampleAutomation), self.context)`。

**⚠️ 别改过头**：schema 上的 `directives.write_permission(auto_create_samples=ManageSampleAutomation)`
必须**继续用 id 形式** —— `plone.autoform/utils.py::_process_permissions` 会自己
`queryUtility(IPermission).title` 再判（这正是仓库规则 R1 的出处）。实测：LabManager/admin
能看到「自动登样」开关，**LabClerk 看不到**（字段级本来就是对的）。

> **一句话**：`check_permission()` 传 **title**（先 `permission_name()` 解析），
> `write_permission()` 传 **id**。两者刚好相反。
> 教训：**权限/角色相关的验证不要只用 admin 跑**。
> 回归守卫：`tools/checks/check_permissions.py`（31 项，含源码守卫）。

### 1. `indexing.py`：编目兜底与遗留 Title 索引噪音（★ 改这块前必读）

* **`normalize_title_encoding(obj)`**：编目前先把**字节串标题**归一成 unicode（幂等、不抛）。
  不这么做，我们自己就会往 `uid_catalog` 的 `Title` 索引里塞非 ASCII 字节键。
* **`is_legacy_title_index_failure(catalog_id, exc)` + `LEGACY_TITLE_INDEX_HINT`**：
  只把「`uid_catalog` + Unicode 类错误」这一种**已知遗留故障**降级成一句 WARNING
  （不再写整段 ERROR + traceback），提示里写明"**不影响 UID 解析**"与修复脚本位置；
  其他异常照旧 `logger.exception` 带堆栈。
* 背景（实测）：`uid_catalog.Title` 是 Archetypes **FieldIndex**，键就是标题值本身。
  py2 里 ASCII 标题**本来**就是 bytes 键（924 个键里 724 个 bytes，无害）；
  危险的是**非 ASCII 字节键**（本站 58 个）。**结论：不改数据，只兜底**
  （UID 解析三条路实测都正常，只是这些对象在 Title 关键字索引里查不到）。
* 可选体检/修复：`项目文档/稳定性模块/tools/repair_uid_catalog_title.py`（默认 dry-run）。

### 2. 4 个 `content/*.py` 去掉 UTF-8 BOM

`packagingspecifications` / `stabilitystudies` / `stabilitystudytemplates` / `storageconditions`
开头原本带 `EF BB BF`。py2.7 能跑，但**首行的 `# -*- coding: utf-8 -*-` 会因此失效**，
diff/工具也会把 BOM 当正文。已去掉，**正文零差异**。

### 3. 自检与运维交付（都在 `项目文档/稳定性模块/`）

| 交付物 | 说明 |
| --- | --- |
| `tools/run_checks.py` | 一键跑 11 个纯逻辑自检，自动挑本机 py2.7/py3 各跑一遍（**22/22 ALL GREEN**） |
| `tools/checks/` | 自检**唯一来源**（9 个既有 + `check_indexing.py` + `check_permissions.py`）；`.tmp_deploy` 下的工作副本已删除 |
| `tools/checks/_bootstrap.py` | stdout 编码保护（py2 管道下打印中文不再 `UnicodeEncodeError`）+ py2 版 `glob_recursive` |
| `tools/README.md` | 自检怎么跑 / 为什么两个解释器 / **不覆盖什么** / 加新自检的规矩 |
| `稳定性模块-使用与运维说明.md` | 客户与运维一页说明：开关清单、cron 与专用账号、日志→原因→处理排障表、清理与备份 |
| `样品模板与自动登样-阶段5-实施说明.md` | 本轮全部证据与已知边界 |

### 4. cron 凭据：不再用 `admin:admin`

| 项 | 改后 |
| --- | --- |
| 账号 | 专用账号 `stability-scheduler`（角色 `Member` + `StabilityAdministrator`，**不是** Manager） |
| 口令 | `~/.stability_scheduler.cred`（**0600**，格式 `用户名:口令`）；crontab 用 `-u "$(cat ...)"` 读 → `crontab -l` 里没有明文口令 |
| 权限来源 | `profiles/default/rolemap.xml` 新增把 `Manage Sample Automation` 授给 `StabilityAdministrator`（改后需重跑 profile 的 rolemap 步骤） |
| 实测边界 | 定时入口 200、本模块设置页 200；用户/组管理、portal_setup、其它控制面板全部 302；方案编辑页 302（不该有的编辑权拿不到） |
| 换口令/换账号 | 只改凭据文件（或重建同名账号），**crontab 不用动** |

### 5. 部署与验证（2026-09-30）

| 验证 | 结果 |
| --- | --- |
| 纯逻辑 11 项 × 2 解释器 | **22/22 ALL GREEN**（`check_indexing`：py2.7 28/28、py3 24/24；`check_permissions`：31/31） |
| 应用级（停机 `bin/instance run`） | `_stage4_app_check.py` **48/48**、`_verify_zeropoint_app.py` 与 `_verify_plan_copy_app.py` **ALL CHECKS PASSED** |
| 权限名诊断（停机） | 非 Manager：`checkPermission(id)`=**None**、`checkPermission(title)`=**1**（修复后页面 200） |
| cron 凭据验收（只读） | **13/13 PASS**：凭据 600、专用账号 200、匿名/错口令拒、4 个管理页全拒、crontab 无明文口令、admin 未回归 |
| HTTP 冒烟（只读） | **10/10**：5 个入口 200、看板按钮与 4 处撤销入口在、**剥掉 HTML 注释后** `tal:/metal:/i18n: = 0`、`dry_run` 不建样品 |
| 定时任务 | cron 每 10 分钟有新日志行；`skipped` 桶齐全（`disabled_plan`/`not_due`/`already_generated`/`zero_point`） |
| 日志 | 重启后 Traceback / `UnicodeDecodeError` / ERROR 均 **0** |
| 一致性 | 本轮部署文件（含 `permissions.py` 等 5 个）本地/远端 md5 **全一致** |

## 更新说明（2026-09-30 · 阶段 4：到期自动登样 + 撤销登样 + 定时入口）

### 1. 新能力与最终口径

| 机制 | 入口 | 说明 |
| --- | --- | --- |
| **定时自动登样** | `@@generate_due_stability_samples`（供 cron 调用） | 每 10 分钟问一次"有到期的吗"；**crontab 不写死时刻**，由站点配置 `auto_create_time`（默认 08:00）决定 |
| **看板人工触发** | 看板「生成到期样品」按钮（`bulk_action=generate_due`） | 人工触发、**不等配置时刻**（目标日期到了就生成）；范围 = 勾选行所属方案；仍要求方案开着自动登样 |
| **懒触发兜底** | 打开看板时顺带扫一次 | **进程内限流 10 分钟**、只在站点总开关打开时做、失败不影响页面 |
| **撤销登样** | 看板行「撤销」→ `@@revoke_sample` 确认页 | 行级动作；**必填原因**、**「已完成」不许撤**、**不删样品对象** |

口径细节：

* **幂等**：判据只看"这一行有没有样品"（`analysis_request` 有值 / `generated_at`），
  不引入"上次跑到哪"的游标；重复调用第二遍 `created=0`；并发由 ZODB 冲突检测兜住。
* **撤销的状态退回**：放过库存批次的回 `placed`（已放置），否则回 `pending_placement`（待放置）
  —— 撤销的是"登样"那一步，"放置"的事实还在；两种状态**都允许删除**。
* **★ 撤销之后自动化不再碰这一行**：撤销会把行变回"到期 + 没样品"，cron 10 分钟内就会把它
  建回来 —— 那样"撤销"等于没用。所以撤销留痕 `revoked_at`，**自动扫描跳过带该标记的行**
  （摘要里记 `revoked` 桶）；要重新登样请**人工**点「创建样品」（不受影响）。
* **审计三处**：行上 `revoked_at` / `revoked_by` / `revoke_reason`（**非 schema 键**，
  靠 `timepoints.PRESERVED_FIELDS` 保命）+ 行备注里一行 `[Sample revoked <时间> by <人>] 原因`
  （界面上看得见）+ 日志一条。
* **权限**：定时入口与撤销页在 ZCML 里都用 `zope2.View`（本包有 slug，`cmf.*` 不能写进 ZCML），
  真正的门在 Python 侧要求 **`ManageSampleAutomation`**（与自动登样开关同一个权限）。
* **部署**：没有新增 schema 字段 → **不用重跑 profile**；新增两个 ZCML 注册 → **必须重启实例**。

### 2. ★ 本轮新踩的三个坑（改这块前必读）

1. **直调 `generate_samples_for_plan()` 不带 `expected_uids` 会被判 `row_changed`**：
   它默认 `{}`，而 `new_detail_row()` 造的行**天生带 `detail_uid`** → 每一行都会被判"行身份不符"，
   **自动登样会一声不响地什么都不做**（第一轮自检抓到：`created=0 / failed=2 / row_changed:2`）。
   定时扫描必须回填自己刚读到的 `detail_uid`；页面路径由 `submitted_detail_uids` 提供
   （缺字段给空串 → 拒绝，手写 POST 绕不过去）。
2. **`check_undefined_names.py` 原本是空操作**（验证工具本身有 bug）：它拿 `get_identifiers()`
   当"已绑定名字"，而 symtable 把"只被引用、从未绑定"的名字也算进去，还把未定义的名字标成
   `is_global()` 又被 `free` 集合排掉 → 两处真 `NameError`（漏 import 的常量、漏 import 的 `time`）
   全被放过。已修好（只认 assigned/imported/namespace/parameter，`free` 只排除闭包变量），
   现在全包扫 **problems: 0**。
3. **验证脚本的两个"看走眼"**：① 本站页面是中文，而且**中文在 HTML 里是 `&#NNNNN;` 数字实体**，
   `grep 中文` 查不到 → 判据一律用**语言无关标记**（`value="generate_due"` / `button_revoke` /
   `stability-revoke-link`）；② **脚本上下文不能渲染整页模板**（`metal:use-macro` 里的 viewbar
   viewlet 需要完整请求环境）→ 应用内自检改核对模板**源码**，页面渲染交给 HTTP 验证。

### 3. 部署与验证（2026-09-30）

* **部署**：换代码 + 模板 + 文案 → **重启实例**（ZCML 新增两个页面）；不用重跑 profile。
* **crontab**：✅ **已装**（2026-09-30；原 crontab 备份在 `$HOME/crontab.bak.20260930-031009`，
  新增任务带标记、脚本幂等；按 cron 方式跑过一次，`/var/log/senaite/stability_autocreate.log` 正常写出）：
  ```cron
  */10 * * * * curl -s -u admin:admin \
    "http://127.0.0.1:8081/lims/stability_studies/200_stability_plans/@@generate_due_stability_samples" \
    >> /var/log/senaite/stability_autocreate.log 2>&1
  ```
  建议改用**只授 `ManageSampleAutomation` 的调度账号**，或叠加 `?local_only=1`。
  注意：**站点上目前没有任何方案开着自动登样**（6 份都是关的），所以这条任务现在什么都不做，
  等打开某个方案的「自动登样」开关才生效。
* **手工排查**：`curl -s -u admin:admin ".../@@generate_due_stability_samples?dry_run=1&verbose=1"`
  → 只看"会做什么"，不写库。
* **验证**：纯逻辑 `_check_stage4.py` **33/33**（py2.7 + py3，未回归 27/27/79/138 全绿）；
  应用内自检 `_stage4_app_check.py` **48 项 / 0 失败**（全程 abort）；模板良构 28 项 0 失败；
  漏译审计 0；未定义名检查全包 0；i18n 4 语言各 **219 条**、fuzzy=0；
  HTTP：定时入口（关/开两态 + 匿名 302）、看板按钮随总开关出现/消失、撤销页
  （空原因被拒且数据不动 → 填原因 302 且行退回 + 审计）、没样品的行禁撤；
  站点 **6 方案 / 8 样品前后一致**，总开关已恢复关闭，日志 Traceback **0**。

---

## 更新说明（2026-09-30 · 阶段 3：0 点关联往期样品）

### 1. 新能力与最终口径

看板勾中**零点行** → 「关联已有样品」→ 候选页挑一个**往期真实样品**关联过去。
**0 点不建样**：关联的是"这批样品的基线"。

| 项目 | 口径 |
| --- | --- |
| 页面 | `@@zero_point_candidates`（`browser/zeropoint.py` + `templates/zero_point_link.pt`） |
| 窗口 | `[T0 - N 天, T0]`，**含 T0 当天**；`N` = 站点配置 `zero_point_lookback_days`（默认 30），`≤0` 按 0 处理（只认 T0 当天） |
| 没有 T0 | 页面标不可关联；服务端 `link_no_target_date`（**值刻意与登样的 `no_target_date` 不同**，两套码各取自己的文案） |
| 候选日期 | `DateSampled` 优先；为空（或 z3c.form 哨兵 `<NO_VALUE>`）退回 `created`，**列表必须标明用的是哪个** |
| 候选范围 | 默认只列**方案客户**的样品；页面开关可切「全部客户」 |
| 列表列 | 样品编号 / 客户 / 样品类型 / 日期（含来源）/ 状态 / **已关联到** |
| 唯一性 | **强制唯一**：一个样品只能被关联一次（同方案其它行、跨方案都拦），冲突目标显示在列表里 |
| 成功后 | 与登样**同一套写回**：`analysis_request` + `detail_status=active` + `generated_at`/`generated_by` + 时间点任务镜像 + 显式编目 |
| 候选上限 | 单次 200 条（`CANDIDATE_LIMIT`） |
| 服务端判据 | 行存在 → **行身份 `detail_uid`** → 是零点行 → 有 T0 → 样品存在 → 日期在窗口内 → 未被任何方案关联 |
| 部署 | **不需要重跑 profile**（没有新增字段 / 权限 / registry） |

实现分工：**窗口与日期口径**在 `sampleautomation`（`zero_point_window` / `choose_sample_date` /
`in_zero_point_window` / `row_links_sample`，纯逻辑、可脱机自检）；**关联动作**在
`samplegeneration.link_sample_to_row()`（唯一实现，含 `find_link_conflict()` 强制唯一）。

### 2. ★ 本轮新踩的六个平台坑（改这块前必读）

1. **取样日期是工作流字段**：`setDateSampled(...)` / 字段 setter **都不落库** →
   自检与 HTTP 夹具**造不出"指定取样日期"的样品**，只能用站点上真实样品。
   推论：**"窗口内恰好有可关联样品"不能当断言前提**（否则换台干净站点就假失败）。
2. `bika.lims.api` **没有** `get_field_value()`（写了 → `AttributeError`，整页 500），
   而且字段**可能是值、也可能是访问器方法**（`Client` 取到的是对象不是 uid）→
   统一走自写的 `field_value()` / `_field_value()`。
3. **显示用的格式化字符串不能参与日期比较**（`can't compare datetime to unicode`）→
   目标行 dict 里同时放"给人看的字符串"（`window_start`/`window_end`）与
   "给判定用的真 `datetime`"（`window`）；比较前一律 `to_naive_datetime()` 归一。
4. 样品目录**没有** `DateSampled` 索引（照字段名写 `sort_on` → `CatalogError: Unknown sort_on index`），
   实际索引名是 **`getDateSampled`** → `sampled_index_name()` 按"存在的那个"选。
5. `DateIndex` 的范围查询**必须传 `DateTime`**：传 `"2026-07-19 11:22"` 这种格式化字符串
   **不报错、候选恒为 0 个**（真机被骗了一轮）。判据：窗口对、候选恒 0 → 先怀疑这里。
6. 脚本（`bin/instance run`）上下文里**带权限过滤的目录查询常常返回 0 条** →
   `_search()` 先过滤查询、空结果退回 `unrestrictedSearchResults`；
   **盘点/对账脚本一律用不限制查询**，否则会误判"数据没变"。

> 另有两条**验收口径**上的坑（2026-09-30 复核时踩到，详见
> `项目文档/稳定性模块/样品模板与自动登样-阶段3-实施说明.md` §6）：
>
> * **模板命名空间必须写 `http://xml.zope.org/...`**（不是 `http://xmlns.zope.org/...`）——
>   写错时 TAL/METAL **完全不执行**，浏览器看到的是模板源码（该页恒为 7111B），
>   **而 HTTP 依然是 200**、关键词断言还全能命中。所以页面验收要断言"**渲染后**才算过"：
>   响应体里**未执行的 `tal:` / `metal:` 指令残留必须为 0**（约 25 KB），
>   且渲染出的窗口区间 / 候选编号能查到。
>   注意别在模板注释里写那些属性名 —— 注释会进响应体，断言会把它数进去（真踩过）。
> * **验证夹具不能删"借用的真实样品"**：关联只写方案明细行，临时方案删掉后样品自动回到未关联；
>   清理脚本只允许删夹具自建对象（夹具文件里 `owned_sample=1` 的）。

### 3. 部署与验证（2026-09-30）

* **部署**：只换代码与模板，**不用重跑 profile**；模板改动重启实例即可（PageTemplate 会按 mtime 重编）。
* **验证**：纯逻辑 `_check_zero_point.py` **27/27**（py2.7 + py3）；应用内 `_verify_zeropoint_app.py`
  **21 项 / 0 失败**（全程 abort）；HTTP 端到端 `_zp_http_confirm.sh`（夹具 → 真实点按钮 → 清理）
  候选页 200 / 约 25 KB / 未执行的 `tal:` 指令残留 0、POST 302 + 行 `active` + 审计、
  重复 POST 报「这个时间点已经关联过样品了」、旧 `@@link_sample` 404；
  回归：阶段 2 应用内 77/0、时间点规则 68/0；
  站点数据前后 **5 方案 / 样品未减**，日志 Traceback 0。

### 4. ★ 2026-09-30 补记（B 方案）：0 点**不强制** → 预置 + 四处提示 + 删除二次确认

背景：0 点（基线点）在代码里**不强制**（无 invariant、模板不维护时间点、未登样的 0 点行还能删），
站点上 5 份方案一度只有 1 份有 0 点 —— 那 4 份**永远没有基线样品**，方案上还看不出来。

口径（客户选定，只做提示不阻断）：

| # | 做什么 | 落在哪 |
| --- | --- | --- |
| ① 预置 | **新建方案默认带一行 0 点**（可删、可改成别的时间点）；**复制方案不预置**（忠实复制源明细） | `browser/add.py` + `plandetails.new_detail_row()`；前端 `applyPlanInitialRowDefault()`；模板走 `_template_plan_details()` |
| ② 提示 | 方案页 / 任务看板 / 登样页 / 关联候选页 四处提示"没有 0 点 = 没有基线样品" | `browser/viewlets/stabilityplanzeropoint.py`（新）、看板 `plans_without_zero_point*()`、登样页 `lacks_zero_point`、候选页 `get_notice()` |
| ③ 二次确认 | 删 0 点行时弹确认；0 点行挂「0 点」徽标 | `z3cform/widgets/plandetails_datagrid_input.pt` |

**★ 改这块前必读（本版本 DataGrid 的两个坑）**：

1. **DataGrid 不渲染字段默认值**：给 `plan_details` 设 `field.default` 之后，渲染出来的新建表单里
   `plan_details.count = 0`、**一个真实行都没有**（只有 `TT` 原型行）—— 明细行是**前端 JS**
   填进表格的（`viewlets/templates/stabilityplantemplate_form.pt` 的 `populatePlanDetails()`）。
   所以"预置一行"要落到"前端 JS + 模板默认值 + 服务端兜底（`add.py::create()`）"三条路径上，
   只写 `set_default("plan_details", ...)` 是**没用的**（那只是别的渲染路径的兜底）。
2. **别手工拼 datagrid 提交体**：自己拼 `form.widgets.plan_details.N.widgets.*` 很容易踩
   `PicklingError: Can't pickle <class 'z3c.form.interfaces.NO_VALUE'>`（select token 读错 →
   `SequenceWidget.extract` 返回哨兵 → 整行变哨兵值 → 提交时炸）。验证要用**平台自己渲染的表单原样回放**。
   顺带：这个哨兵 `NO_VALUE` 会以字面量 `<NO_VALUE>` 落进明细行，所以 `sampleautomation.is_blank()` 必须把它当空。

实现上还顺手消掉一处重复：明细的**列清单与行构造**收到新模块 `plandetails.py`
（`DETAIL_ROW_KEYS` / `DETAIL_ROW_DEFAULTS` / `EXTRA_ROW_KEYS` / `new_detail_row()`），
`plan_copy.py` 改为引用它 —— 之前"复制"与"新建"各写一份列清单，**少一列就静默丢字段**。

**验证（2026-09-30）**：纯逻辑新增 27/27（py2.7 + py3，未回归 27/79/138 全绿）；应用内自检 26 项全 PASS；
模板良构 24 项 0 失败；i18n 4 语言各 198 条、fuzzy=0；新建方案端到端三条路径全过（裸 POST → 兜底 1 行 0 点；
datagrid 提交为空 → 0 行；带 0 点行的编辑表单原样回放 → 200 且明细不变）；站点前后 5 方案 / 7 样品未变。
详见 `项目文档/稳定性模块/样品模板与自动登样-阶段3-实施说明.md` §十一。

---

## 更新说明（2026-09-29 · 阶段 2+：按**时间点行上的**样品模板创建样品）

### 1. 新能力与最终口径（**需求订正后的版本**）

任务看板的批量入口 **「创建样品」**（`@@generate_sample`）：勾时间点行 →
按**每一行自己的样品模板**建样品，并写回明细行。

| 项目 | 口径 |
| --- | --- |
| **样品模板** | **逐个时间点**维护在方案明细行上（`plan_details[*].sample_template`）—— 不同时间点验的项目不同就选不同模板 |
| 样品类型 / 检验项 | 取自**该行**的模板（模板没填样品类型时退回其分装记录的样品类型） |
| 客户 | 方案上的「客户」（方案模板给默认值；该行模板的归属作兜底） |
| 联系人 | 方案上的联系人（方案级覆盖方案模板） |
| `SamplingDate` | `max(目标日期, 现在)`（目标日期已过期时取"现在"，满足字段 `min=created`） |
| `DateSampled` | **不写**（手工作样，收样时才填） |
| 0 点 | **不建样**（需求是"关联往期样品"，阶段 3 做） |
| 成功后 | `analysis_request` / `detail_status=active` / `generated_at` / `generated_by`；时间点任务镜像为 active 并同步 `sample_template` |
| 判据（服务端） | 行身份（`detail_uid`）→ 待放置 → 未关联 → 非 0 点 → 有 T0 → 配置齐全；页面只是提示层 |

**已删除**：明细行/任务上的 `analysis_specification`、`analysis_profile` 及其"二选一" invariant；
方案模板上的 `sample_template`；旧的 `@@create_sample` 页面（按标准/套餐建样）与它的按钮。

**手建与阶段 4 的自动建样共用同一份实现**（`maitux.stability.samplegeneration`），
且**配置逐行解析**（`automation.get_generation_config(plan, row)`）——
同一方案的不同时间点可以验不同项目。

> 客户解析优先级（`automation.get_client(plan, row)`）：**方案 `client` → 方案模板 `client` →
> 该行模板自身归属**。三处都取不到才报 `no_client`；若该行模板是"客户级"的、
> 且与方案客户不是同一家，报 `client_template_mismatch` 拦下（防止串客户数据）。

### 2. ★ 本轮新踩的四个平台坑（改这块前必读）

1. **`DateTime + timedelta` 会抛 `TypeError: float() argument must be a string or a number`**
   —— 而"日期是什么类型"取决于谁写进去的：走添加/编辑表单存的是标准库 `datetime`（正常），
   脚本/导入直接赋 Zope `DateTime(...)` 才会炸（`DateTime.__add__` 把参数当"天数"去 `float()`）。
   **用界面建的方案永远复现不了**，所以"界面点过没问题"不能作为正确性依据。
   处理：`sampleautomation.shift_days()` 一律先归一成朴素 `datetime` 再算；
   自检里用 `HostileDateTime` 桩把这条路径钉住（`_check_sample_generation.py`）。
2. **程序化创建的对象不会自动进 `uid_catalog`**（编目订阅者挂在"对象初始化事件"上，
   只有走添加表单才触发）→ 脚本造数据后必须 `api.catalog_object(obj)`，
   否则页面按 uid 解析就是 `APIError: No object found for UID ...`。
3. **`api.get_object_by_uid(uid)` 解析不到时是抛异常，不是返回 None**
   → "先取对象再判 None"是**假防御**（目录陈旧/引用失效直接 500）。
   本包所有 uid 解析统一 `api.get_object_by_uid(uid, None)`，
   解析不到就给一行明确提示（`unknown_plan`），不静默少一行。
4. **`plone.autoform` 的 `directives.mode` 存的是三元组列表**
   `[(interface, 字段名, 模式), ...]`，**不是** `{字段名: 模式}` dict
   （阶段 1 的 `directives.write_permission` 才是 dict）。写校验脚本时两种形态都要认。
5. **引用字段的 `catalog` 查错目录 = 下拉框空白，而且不报错**
   （2026-09-29 修：方案模板「样品自动化 → 联系人」下拉一直没数据）。
   平台按域把类型编目在**不同目录**里（见 `senaite/core/catalog/__init__.py` 的
   `CATALOG_TYPE_MAPPING`）：

   | 类型 | 目录 |
   | --- | --- |
   | `Client` | `senaite_catalog_client` |
   | `Contact` / `LabContact` / `SupplierContact` | `senaite_catalog_contact` |
   | `AnalysisRequest` / `Sample` | `senaite_catalog_sample` |
   | `Batch` 等 | `senaite_catalog` |
   | setup 类字典（SampleType / SampleTemplate / AnalysisSpec / 包装规格 / StockUnit…） | `senaite_catalog_setup` |

   本包原先「联系人」写成 `catalog=SETUP_CATALOG` → 联系人气目录里明明有 7 条却一条都查不到；
   同查询换到 `CONTACT_CATALOG` 立刻 7 条。另外 `query` 里的 `portal_type` 是**无用**的
   （widget 会用 `field.allowed_types` 覆盖它），决定查得到查不到的是 `catalog`。
   排查手法：看页面 HTML 里该控件块的 `data-catalog`
   （⚠️ 属性用**单引号**、值是 JSON 字符串：`data-catalog='"senaite_catalog_contact"'`，
   按 `data-catalog="..."` 正则会永远取到空）。规则已收入 `SENAITE-Addon开发规则.md` R11。

环境常识：`bin/instance run` 里删样品时，内核订阅者会在对象**已经删掉之后**抛
`AttributeError: 'RequestContainer' object has no attribute 'guard_handler'`
（要跑工作流 guard 但脚本环境没有请求）——对象其实删掉了，
所以清理脚本按"容器里还在不在"判定成败。

### 3. 明细行的隐藏列与行上的样品模板

- **登样审计**：`generated_at`（`YYYY-MM-DD HH:MM`）/ `generated_by`（用户名），
  与 `detail_uid` / `detail_status` / `analysis_request` / `stock_batch` 一起进
  `timepoints.PRESERVED_FIELDS` —— DataGrid 只提交 schema 里声明过的列，
  不保留就会"编辑一次方案丢一次审计"。
- **样品模板**（2026-09-29 需求订正）：放在**明细行**上，不在方案模板上；
  行上原有的「检验标准 / 分析套餐」已删除。
- **客户**：放在**方案**上（方案模板给默认值），建样时自动带过去。

### 4. 部署与验证

- 生效方式：重启实例即可，**不需要重跑 profile**（字段在 schema 里，不涉及 FTI/权限/registry）。
- 纯逻辑自检：`py -3 .tmp_deploy/_check_sample_generation.py`（72 项，py2.7 同样通过）。
- 应用内自检：`.tmp_deploy/_verify_stage2_app.py`（77 项，需停实例，全程 abort）。
- HTTP 端到端：`.tmp_deploy/_verify_stage2_http_full.sh`
  （造 3 行夹具 → 真实点按钮 → 校验 → 删测试数据并逐类盘点还原）。
- 表单可见性与控件目录：`.tmp_deploy/_stage2_check_client_field_http.sh`。
- 死文案扫描：`.tmp_deploy/_prune_msgids.py`（列出"翻译目录里有、源码里已无引用"的 msgid）。
- 实施说明：`项目文档/稳定性模块/样品模板与自动登样-阶段2-实施说明.md`。

## 更新说明（2026-09-28 · 时间点增删：只允许删"未开始"的）

### 1. 规则

| 操作 | 规则 |
| --- | --- |
| 新增时间点行 | **任何方案都可以**，包括已经开始的方案；新行状态一律「待放置」 |
| 删除时间点行 | **只有「待放置（Pending Placement）」可以删**；「进行中」「已完成」不允许 |
| 拖动排序 | 允许，行身份跟着 `detail_uid` 走，不误判成删除 |

### 2. 为什么引入 `detail_uid`

明细行的**行号不是身份**：DataGrid 允许删行与排序，删掉中间一行后后面所有行的行号都会平移，
而 `StabilityTimepointTask.sequence` 是照行号写的 —— 按序号把「明细行」和「任务对象」配对，
删中间行会**删错对象**（3 行删第 2 行时，被删掉的是第 3 行那条待放置任务，
第 2 行"进行中"的任务反被留下并错配）。

现在每行带一个 `detail_uid`（32 位 uuid hex，隐藏列，生成后永不变），
任务对象记同一个值，两边靠它配对。历史数据（无该列）按"没 id 的行按出现顺序"兜底配对，
并在**第一次打开/保存方案时自动补齐**（`subscribers.ensure_plan_detail_uids`）。

### 3. 两道防线

| 层 | 位置 | 行为 |
| --- | --- | --- |
| 前端（体验） | `z3cform/widgets/plandetails_datagrid_input.pt` | 受保护行的删除按钮隐藏 + 状态徽标；捕获阶段拦截删除点击并弹提示 |
| 服务端（判据） | `browser/edit.py` 的 `StabilityPlanEditForm.applyChanges` | 保存前用「库里的行」与「提交的行」对账；受保护的行若被删掉，**按原位置放回**并给明确提示 |

服务端这一道是判据：绕过 JS 直接 POST 一样删不掉。前端那道失效只影响体验。

### 4. 顺带修掉的两个静默丢数据

保存方案明细时，DataGrid 只提交 schema 里声明过的列，因此：

- **`stock_batch`**（排样结果）**不在 schema 里** → 编辑一次方案就静默清空；
- `detail_status` / `analysis_request` 是隐藏列，提交值为空时同样会丢。

现在 `timepoints.carry_over_preserved_fields` 会在提交值为空时从原行带回这四个字段
（`detail_uid` / `detail_status` / `analysis_request` / `stock_batch`），只认配对上的那一行，不会串行。

### 5. 同步策略（`sync_plan_timepoint_tasks`）

- **配对**：先按 `detail_uid`；只有"任务自身没有 id"（本次改动前建的历史任务）才按 `sequence` 兜底，
  并在认领时把 `detail_uid` 补给任务（只写身份，不碰业务字段）。
- **创建**：明细里新增的行 → 建任务。
- **更新**：只更新 `pending_placement` 的任务，且**只写真的变了的字段**
  （稳定后 `sync` 返回 `(0, 0, 0)`，不再每次保存都白写一遍）。
- **删除**：只删"明细里已经没有、且自身还是待放置"的任务；**已经开始的永不删除**。
  ⚠️ 删除必须走 `bika.lims.api.security.as_privileged_user()`，原因见下面第 8 条。

### 6. ★ 三个平台级坑（改这块代码前必读）

1. **`@@edit` 的 ZCML 注册不能用 `cmf.ModifyPortalContent`。**
   本包走 `package-includes/*-configure.zcml`（`site.zcml` 第 15 行）加载，
   而 `cmf.*` 权限由 `Products.CMFCore` 在第 16 行 `five:loadProducts` 才注册 →
   `protectClass` 找不到 `IPermission` → `ComponentLookupError` → **Zope 起不来**。
   正确做法（与同文件里 `sample_placement` / `link_sample` / `create_sample` 一致）：
   ZCML 用 `permission="zope2.View"`，真正的编辑权限在
   `browser/edit.py` 的 `StabilityPlanEditView.__call__` 里用 `can_edit()` 二次校验。

   > 注意别过度概括成"`cmf.*` 一律不能用"：**有 slug 的包才踩这个坑**。
   > 没 slug 的包（走 z3c.autoinclude，第 16 行加载）里 `cmf.*` 是好的
   > （`maitux.stock` 的 `cmf.ManagePortal` 一直正常）；
   > 也可以在 `configure.zcml` 顶部写
   > `<include package="Products.CMFCore" file="permissions.zcml" />` 自己钉顺序
   > （`maitux.oauth2` 就是这么做的）。详见
   > 仓库根 `SENAITE-Addon开发规则.md` 的 R1 订正。

2. **真请求下 `ploneapi.content.delete()` 删 Dexterity 容器的子对象一定 Unauthorized。**
   `plone.dexterity` 的 `manage_delObjects` 对子对象做
   `checkPermission(permissions.DeleteObjects, item)`，而 `AccessControl 4.4` 的
   模块级 `checkPermission` 对**字符串**权限名先 `queryUtility(IPermission, name)`，
   查不到就 `return False`；`Delete objects` 是权限**标题**，工具名是 `cmf.DeleteObjects`。
   实测：装了真实 SecurityManager 时**连 Manager 都会被拒**（脚本默认上下文则通过）。
   解法：`as_privileged_user()`（平台自带，docstring 举的例子正是删除对象）。

3. **增删方案的子对象都会触发方案自己的 `IObjectModifiedEvent`** →
   `stability_plan_modified` 会被回调一次（`ContainerModifiedEvent` 是
   `IObjectModifiedEvent` 的子接口，且在 `Container._setObject()` **内部**触发）。

   - **删除方向**：`同步 → 删掉多余任务 → 再次同步 → 给这一行重新建任务 → 再删 → …`，
     任务对象成倍增长（实测一次删行能造出几十个 `tp-00N-xx`）。
   - **新增方向（2026-09-29 真机事故）**：新建方案时按明细生成任务，
     `_generate_plan_timepoint_tasks` 当时**没有**重入锁 → 每建一个任务就嵌套
     进来一次对账 → 对账看到的是"还没写上 `detail_uid` 的半成品任务"，
     判成多余任务**当场删掉** → 回到
     `TypesTool._constructInstance:572 container._getOb(newid)` 时对象已经不在，
     抛 `AttributeError: 'tp-001'`，**界面加方案必 500**。

   解法（两条一起上）：
   - `_plan_sync_scope`：同方案同线程只允许一层，"生成"与"对账"**共用**它
     （日志留 `Skip re-entrant timepoint …`）；
   - 对账的删除阶段：**既没有 `detail_uid`、`sequence` 也不是正数**的任务一律
     不删，只记 `WARNING`（`Keep unidentifiable pending timepoint task …`）——
     这种任务要么是别人正在创建，要么是外来的手工对象，都不该由对账判死刑。

   回归脚本：`.tmp_deploy/_probe_addplan_tasks_app.py`（A：`createContent` →
   写字段（含明细）→ `addContentToContainer`，与添加表单同款路径；
   B：手工往已有方案加任务）。修复前两个用例都抛 `AttributeError: 'tp-…'`。
   另有 `.tmp_deploy/_http_addplan_rows.py` 走真实表单 POST，但**注意**：
   它靠抓 HTML 拼提交体，select 的 token 抓错会让 z3c.form 的
   `SequenceWidget.extract` 返回 `NO_VALUE`、整行明细变成哨兵值、提交事务时
   抛 `PicklingError` —— 那是脚本保真度问题，不是产品缺陷
   （真实浏览器提交的 token 一定合法，用户报的是 `AttributeError` 正好证明
   他那次提交的行是正常解析成 dict 的）。

4. **`reindexObject()` 在本包的类型上是「静默空操作」** ——
   对象建出来了，列表 / 看板 / REST 里却什么都没有（2026-09-29 第二起事故）。

   senaite 的目录总闸门 `CatalogMultiplexProcessor.supports_multi_catalogs()`：

   ```python
   if api.is_dexterity_content(obj) and IMultiCatalogBehavior(obj, None) is None:
       return False        # ← 直接 return：什么都不索引，不报错、不写日志
   ```

   本包的 FTI 里**声明了** `bika.lims.interfaces.IMultiCatalogBehavior`，
   但实测**新建出来的对象并不提供该标记**（同一个 FTI 里的 `IAutoGenerateID`
   却生效，所以编号正常、编目不正常）；对照 senaite 自带的 `SampleTemplate`
   是提供的。于是 `obj.reindexObject()` 什么都不做，现象是：

   * 方案/任务在 `uid_catalog` 里有、在 `senaite_catalog_setup` 里**没有**；
   * 方案列表、登样看板、REST 搜索全都查不到 —— 用户看到的是"建完就没了"；
   * 而且是**时好时坏**的：先建空方案、再把明细补上的那几次进了目录，
     新建时明细里就带时间点（生成任务发生在 `ObjectAddedEvent` 内部）
     的那几次没进。

   解法（见 `maitux.stability.indexing`，两件一起做）：

   * 在 6 个"要编目"的内容类上**显式声明** `IMultiCatalogBehavior`
     （`stabilityplan` / `stabilitytimepointtask` / `stabilityplans` /
     `stabilityplantemplate` / `storagecondition` / `packagingspecification`）；
   * 自己创建/更新的对象一律走 `indexing.ensure_indexed(obj)`：补标记 +
     直接点名对象该进的每个目录做 `catalog_object(obj, path)`
     —— 不再依赖 `reindexObject()` 有没有被那道门拦掉。

   回归脚本：`.tmp_deploy/_probe_indexing_fix.py`（C1 带明细建方案、
   C2 不带明细、C3 建完补明细再对账，逐项核对"进目录 + 能被目录查询到"）。
   数据修复脚本：`.tmp_deploy/_diag_index_gate.py`（把已存在但没编目的对象
   直接编目，日志里是 `直接编目完成`）。

5. **客户/联系人不是同一家** —— 登样时被 `PROBLEM_CONTACT_OTHER_CLIENT` 拦下，
   提示语要说清"谁家的谁"，而且不能在保存阶段放任错配入库
   （2026-09-29 第三处改动）。

   背景：`Contact` 是样品（AR）的必填字段，平台**不校验**它是否与样品所属客户
   同一家 —— 选错了照样能建出"样品挂 A 客户、联系人是 B 家的人"，
   发报告与追责都会错。而本包的「联系人」下拉原本查的是**全站联系人**
   （`catalog=CONTACT_CATALOG` + 只筛 `is_active`），客户又在同一张表单里另选，
   站点上 5 个客户各有关联人时极易选错。

   三处一起改：

   - **下拉按客户过滤**：在 `StabilityPlan` / `StabilityPlanTemplate` 上实现
     senaite 的上下文钩子 `get_widget_contact_query(...)`
     （`QuerySelectWidget.lookup` 的约定：`get_widget_<字段名>_<属性名>`），
     客户已选时给查询加 `getParentUID=<客户 UID>`；客户为空时返回原查询
     （客户与联系人在同一张表单里，锁死下拉会让人没法先选联系人）。
     ⚠️ 钩子里的名字**必须有 import**：少一个 `from bika.lims import api`
     就会 `NameError`，被 `except` 吞掉 → 钩子静默失效、下拉又变回全量
     （本次真机上就是这么踩了一次）。
   - **保存时清掉错配值**：`subscribers._drop_mismatched_contact()`（方案与方案模板
     的 added/modified 订阅者里调）—— 客户与联系人不是同一家时把联系人清空，
     记 `WARNING`（`Cleared mismatching contact …`）并给一条 portal message；
     自身没写联系人、但**生效联系人来自方案模板**且错配时，只记日志提醒
     （改不动模板，得去模板上改）。
   - **报错带名字**：`get_generation_config()` 多返回 `problem_data`
     （code → 占位符值），`samplegen.problem_text(code, data)` 用
     "带名字"的那条 msgid（`MESSAGE_CONTACT_OTHER_CLIENT` /
     `MESSAGE_TEMPLATE_OTHER_CLIENT`），提示形如
     「联系人"Andre Corbin"属于"Ŝunnyside"，而样品将要登记到的客户是"Klaymore"」。
     文案已进 4 个语言的 `.po` / `.mo`（164 条）。

   验证脚本：`.tmp_deploy/_probe_contact_hook.py`（下拉查询的 `getParentUID`、
   错配清空、文案渲染）；数据修复：`.tmp_deploy/_fix_contact_client.py`。
   ⚠️ 脚本里查目录要 `as_privileged_user()`，否则匿名身份查不到联系人与客户；
   更稳的办法是按已知 UID 直接取对象。

6. **「样品放置」原来会把行锁死** —— 放置过就不能再登样（2026-09-29 需求订正）。

   旧行为：`sample_placement` 把 `detail_status` 写成 `active`（进行中），
   而登样又要求"只有待放置可以登" → **先点过放置的行永远登不了样**，
   登样页的「生成」按钮直接是灰的（`has_generatable_rows()` 为假）。
   真机上客户就卡在这里："为什么不能点生成按钮"。

   新模型（**先放置、再登样**，客户确认）：

   * 新增行状态 **`placed`（已放置）**：放置只记库存批次，**不算开始**；
   * 判据从"状态必须是待放置"改成 **"只要还没登过样"**：
     `sampleautomation.is_generated(row)` 看 `analysis_request` / `generated_at`，
     状态字段**不能**当唯一判据（历史"放置过"的行状态也是 `active`）；
   * 登样成功 → `active`（进行中）并写登样审计，此后不可再登（`already_generated`）；
   * 已完成的点 → `completed`，不可登样；
   * 删除守卫跟着放宽：**还没登样的行可以删**（待放置 / 已放置），
     登过样或已完成的不可删（前端 JS + 后端表单守卫 + `timepoints.is_deletable` 三处一致）；
   * 看板状态筛选新增「已放置」；放置动作允许对 待放置/已放置 的行重复执行（改批次）。

7. **DataGrid 隐藏列的"没值"是以字面量 `<NO_VALUE>` 落库的** ——
   判定"有没有填"时**必须当空**（2026-09-29 真机踩到）。

   `generated_at` / `generated_by` 这类隐藏列在"没有值"时被渲染成字符串
   `<NO_VALUE>`，保存时又原样写回 → 库里出现**非空字符串**的"空值"。
   不带这个兜底时 `generated_at="<NO_VALUE>"` 会被判成"登过样"，
   `stabilityplan-3` 的第一行就这么被误判、按钮灰掉。
   解法：`sampleautomation.is_blank()` 把 `PLACEHOLDER_VALUES`
   （`<NO_VALUE>` / `NO_VALUE` / `<no value>`）当空 —— 见规则 R15。

   回归脚本：`.tmp_deploy/_fix_placed_rows.py`（数据修复 + 判定/删除守卫断言）、
   `.tmp_deploy/_check_sample_generation.py`（纯逻辑，含哨兵用例）。

### 7. 部署与验证

- 生效方式：`.py` / `.zcml` / `.pt` / `.po|.mo` 全部**重启实例**即可，**不需要重跑 profile**
  （没有新增 FTI / registry / 权限）。
- `.pt`：本实例 Chameleon `AUTO_RELOAD=False`，编译产物在 `<root>/var/cache`。
  重启后若页面还是旧模板，清掉引用该模板的缓存条目兜底：
  `grep -rl <模板名> var/cache | xargs -r rm -f`。
- 改了 `.po` 必须重编 `.mo`：本包有 `tools/compile_mo.py`，在包目录跑 `python tools/compile_mo.py`
  （README 之前引用过这个脚本但仓库里没有，本次补上）。
- 纯逻辑自检：`py -3 .tmp_deploy/_check_timepoint_rules.py`（63 项，py2.7 同样通过）。
- 站点应用内自检：`.tmp_deploy/_verify_timepoints_app2.py`（44 项，需停实例）。

> **验证教训**：`bin/instance run` 的合成请求**只渲染默认 fieldset**，
> `plan_details` 这个 DataGrid 不会出现在里面 —— 据此判断"模板没生效"是**误判**。
> DataGrid 相关改动必须用**真实 HTTP 请求**验证；
> 且页面把中文做了 HTML 实体编码（`&#24453;&#25918;&#32622;`），grep 中文前要先解码。

- 完整实施说明与验收清单见 `项目文档/稳定性模块/时间点增删-实施说明.md`。

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

---

## 更新说明（2026-09-30 · 阶段 6d：保存报错修复 + 撤掉「作废」）

### 1. 先说事故（这一段比功能更重要）

**现象**：编辑页保存报 500，事务 commit 时抛
`PicklingError: Can't pickle <class 'z3c.form.interfaces.NO_VALUE'>`。

**根因（6c 写反了一处）**：`plandetails_datagrid_input.pt` 里 `applyVoidedRows()`
把已作废行的输入控件 **disable** 了 —— 与同一段注释写的"行必须继续提交上去"
正好相反。浏览器**不提交被禁用的控件**，于是"计数标记说有 N 行、请求里只有
N-1 行"，`MultiWidget.extract` 就给缺的那一行塞了 `z3c.form` 的 `NO_VALUE`
**哨兵对象**；哨兵不可 pickle，落库那一刻整个事务炸掉。服务端当时还有一个
帮凶：行数守恒把"已作废、静默放回"的行**漏算**了，于是放弃守卫、把**没校验过的
提交数据原样写回** —— 哨兵就是这么进到字段上的。

**现在的四层防线**（任一层单独都能拦住）：

1. **模板**：已废弃的行**只隐藏**（`tr[data-voided="1"] { display: none; }`），
   **绝不 disable、绝不从 DOM 删行**；运行期还把别处加上的 `disabled` 摘掉。
   ★ 这条铁律在模板注释、`browser/edit.py` docstring、自检
   `check_write_guard.py`、应用级 G19、HTTP 8d 段各钉了一遍。
2. **控件层**：`PlanDetailsWidget.extract()` 拦哨兵（整段是哨兵 → 交给上层不写库；
   行内哨兵 → 换空串；整行哨兵 → 丢掉并计数 `dropped_rows`）。
3. **表单层**：行数守恒用 `report["restored"]`（唯一实现）；守卫不通过时写回
   **库里那一份**；控件报丢行时本次**不改明细、不删任何行**并提示刷新重试。
4. **写库层**：`timepoints.sanitize_submitted_rows` 第 7 步把任何哨兵值换成空串。

**验证**：真实表单回放（浏览器保真）保存返回 **302**、明细 **0 处变化**、
错误日志 **0 条新增**；纯逻辑 34/34、应用级 133/133、HTTP 99/99。

### 2. 功能变更：撤掉「作废」动作页，删除 = 状态删除（废弃）

用户 2026-09-30 定稿："作废这个功能还是不要吧，这个界面的删除改成状态删除就行了，
有审计最终追溯，然后不会出现在编辑页面里面，可以在废弃筛选按钮查询到。"

| 项 | 口径 |
| --- | --- |
| **删除入口** | **只有**方案编辑页的删行（`@@void_point` 动作页 + 看板行级链接已撤，页面 404） |
| **删除语义** | 状态删除：行**留在方案里**、写 `voided_at/by/reason`、样品关联保留、审计留痕（`void_timepoint` 快照） |
| **可删范围** | 仍是「待放置 / 已放置」；「进行中 / 已完成」拦下并提示；过期行允许删除 |
| **C1** | 行上关联了样品时样品须达终态，否则拦下并提示是哪个样品没完成 |
| **编辑页** | 已废弃的行**不显示**（CSS 隐藏，但仍随表单提交） |
| **查询废弃行** | 任务看板筛选按钮**「已废弃」**（`?status_filter=voided`）+ 「已废弃」统计卡 + 行上「已废弃」徽标（悬停显示谁/何时/为什么） |
| **文案** | 一律「删除 / 已废弃」（英文 msgid `Discarded`）；6c 的「作废」文案已从 `.po` 移除 |
| **不迁移数据** | 数据键 `voided_*` 与审计动作名 `void_timepoint` **保持不变**（改名要迁移所有历史行与快照），只改用户可见标题 |

### 3. 排查时最费时间的一步（留作经验）

日志里 02:35 的两条同类 `PicklingError` 来自 `127.0.0.1`，是**我自己的调试脚本**
发的（它手工拼 datagrid 提交体、token 抓错）—— 如果一开始就把它们当成产品缺陷，
会得出"这是老问题、不是 6c 引入"的错误结论。**先分清"谁发的请求"（URL / UA），
再谈根因。**
