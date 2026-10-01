# maitux.stability 稳定性模块 · 更新说明

| 项目 | 内容 |
| --- | --- |
| 模块 | `maitux.stability`（稳定性研究 / 稳定性方案模块） |
| 交付对象 | `addons/customers/maitux.stability`（2.7.0-maitux1 客户包） |
| 更新方式 | **直接覆盖文件**（无分支、无数据库迁移） |
| 变更规模 | 覆盖 36 个文件 · 新增 28 个文件 · 其余 31 个文件内容一致（共 95 个文件已同步） |
| 校验 | 与开发版本逐字节一致 95/95；49 个 `.py` 语法编译 0 失败；模板引用 0 缺失 |

---

## 一、一句话

**修掉了稳定性方案「保存报错」的生产问题，并按需求把「作废」功能撤掉、改成编辑页删除即状态删除（已废弃），同时把整个稳定性模块升级到当前版本。**

---

## 二、本次更新内容

### 1）修复：稳定性方案保存报错（重要，建议尽快更新）

* **现象**：编辑稳定性方案后点保存，页面报错（HTTP 500），**这次保存的内容全部丢失**。
* **原因**：被"作废"过的时间点行，在编辑页被前端脚本**禁用**了输入控件；浏览器**不会提交被禁用的控件**，于是"表格说有 3 行、请求里只有 2 行"，表单框架用一个不可序列化的占位对象补位，事务在写库那一刻失败。
* **修复**：已废弃的行改为**只隐藏、不禁用**（行照旧随表单提交），并在服务端加了四道防线（行数对不上时保持库里的数据不变、写入前清掉一切异常占位值）。
* **结果**：用真实表单回放验证 —— 保存成功、时间点明细 0 处变化、错误日志 0 条新增。

### 2）变更：撤掉「作废」功能，改成「删除 = 状态删除」

* 编辑页删除时间点行 = **状态删除**：行**不会真的被删掉**，而是标记为**已废弃**，留在方案里用于追溯；
* 已废弃的行**不再显示在编辑页**，要看它请到**任务看板 →「已废弃」筛选按钮**；
* 行上仍记录**谁、什么时候**做的删除，方案页的**审计**里也有对应记录（可追溯到底）；
* 原先"作废时间点"的**单独操作页面已经撤掉**（访问该地址返回 404），看板上对应的入口链接也已移除 —— 删除只有"编辑页删行"这一条路径；
* 可删范围不变：**待放置 / 已放置**的行可以删；**进行中 / 已完成**的行会被拦下并提示；
* 若该行已关联样品，样品必须已完成/已取消才能删（否则提示是哪个样品没完成）。

### 3）同步：模块整体升级到当前版本

交付包里的稳定性模块是较早的快照，**本次已整体升级**（含方案状态与冻结、时间点过期、自动登样闸门、任务看板、方案复制等全部内容）。因此下面的"当前完整能力"请整体当作新的行为基线。

---

## 三、当前完整能力（用户可以做什么）

* **方案状态**：进行中 / 暂停 / 终止；暂停与终止后方案被**冻结**（不能编辑、不能登样、不能关联/放置/撤销）；
* **时间点明细**：新增 / 删除（= 已废弃）/ 排序；已登样的行不允许删除；
* **方案复制**：按"复制方案"快速派生（自动跳过已废弃的行）；
* **任务看板**：按状态筛选（全部 / 待放置 / 已放置 / 进行中 / 已完成 / **已过期** / **已废弃**）；批量放置、批量创建样品、0 点关联往期样品、撤销登样；
* **自动登样**：按方案设置的"生成时刻"由定时任务创建到期样品；站点总开关可一键停用；过期时间点**不会被补登**；
* **审计**：状态变更、登样、关联、撤销、删除（状态删除）等写操作都有审计记录。

---

## 四、升级步骤（5 步）

1. **覆盖文件**：`addons/customers/maitux.stability/`（本次已完成）。
2. **清掉旧字节码（建议）**：删除该目录下的 `*.pyc`、`__pycache__/`（旧编译产物；不清也会按时间戳自动失效）。
3. **重启实例/容器**：代码与模板由实例启动时加载，**必须重启**才生效。
4. **（仅老站点：数据库里已有稳定性方案）跑一次迁移**（幂等，可重复执行；需停机）：
   迁移脚本 `stage6a_migrate.py` 由我方提供（**未包含在本次覆盖范围内**，需要请告知，
   可直接放到服务器任意路径再执行）：
   ```
   bin/instance stop
   bin/instance run /path/to/stage6a_migrate.py   # 换绑工作流 + 补权限 + 给存量方案补状态
   bin/instance start
   ```
   * 全新站点（无历史方案数据）**不需要**这一步；脚本本身安全、可重复跑。
5. **（可选）启用自动登样**：
   * 站点设置 → Products → **Stability Sample Automation**（或直接开 `/lims/@@stability-automation-controlpanel`）打开总开关；
   * 服务器 crontab 增加（每 10 分钟一次，是否需要建样由配置决定）：
     ```
     */10 * * * * curl -s --max-time 120 -u "$(cat $HOME/.stability_scheduler.cred)" "http://127.0.0.1:8081/lims/stability_studies/200_stability_plans/@@generate_due_stability_samples"
     ```
   * 专用账号口令放 `~/.stability_scheduler.cred`（权限 0600，格式 `用户名:口令`），账号需要 `maitux.stability.permissions.ManageSampleAutomation` 权限。

> **升级前请备份**：`var/filestorage/Data.fs*`、`var/blobstorage/`、`var/log/`。

---

## 五、验证结论（本次交付前已在**开发环境**跑完）

| 检查 | 结果 |
| --- | --- |
| 本地纯逻辑自检（Python 2.7 + 3.14 各跑一遍，不连库） | **34/34 通过** |
| 应用级检查（真机 Zope，全程回滚不留痕） | **133 项通过，0 失败** |
| HTTP 端到端（只读，含"已撤掉的作废页面必须 404"） | **99 项通过，0 失败** |
| **真实表单回放**（浏览器保真提交一次方案编辑保存） | **保存成功**（302 跳回方案页）、明细 0 处变化、错误日志 0 条新增 |
| 文件同步校验 | 95/95 与开发版本逐字节一致；49 个 `.py` 编译通过、模板引用 0 缺失 |

> 部署到客户环境后建议回归这 3 条：① 打开一个进行中方案的编辑页 → 改一处 → 保存成功；
> ② 删掉一个「待放置」的时间点行 → 保存成功、该行从编辑页消失、看板「已废弃」筛选里能看到；
> ③ 日志 `grep -c Traceback var/log/instance.log` 不增加。

---

## 六、注意事项

1. **已废弃的行不会出现在编辑页**，这是设计行为（不是数据丢了）；用看板「已废弃」筛选查看，审计里可查。
2. 状态删除**不可逆**：如需"恢复"某个已废弃时间点，需要运维直接在方案明细上清掉 `voided_at` / `voided_by` / `void_reason` 三个字段（界面没有提供恢复入口，避免误操作）。
3. 交付包内 `browser/templates/` 下仍留有 2 个**旧版本遗留的未使用模板**（`create_sample.pt`、`link_sample.pt`）；新代码已不引用它们，可删可留。
4. 站点设置（站点总开关、权限、工作流、目录结构）由模块安装/升级步骤维护；**覆盖代码后请确认站点设置里能看到 "Stability Sample Automation"**。

---

## 七、本次覆盖文件清单

**修改（36）**

* 顶层：`README.md`
* `browser/`：`view.py`、`add.py`、`configure.zcml`、`templates/task_board.pt`、`templates/sample_placement.pt`、`viewlets/configure.zcml`、`viewlets/templates/stabilityplantemplate_form.pt`
* `content/`：`stabilityplan.py`、`stabilityplans.py`、`stabilitystudies.py`、`stabilitystudytemplate.py`、`stabilitystudytemplates.py`、`stabilitytimepointtask.py`、`packagingspecification.py`、`packagingspecifications.py`、`storagecondition.py`、`storageconditions.py`
* 其他：`configure.zcml`、`permissions.py`、`plan_copy.py`、`setuphandlers.py`、`subscribers.py`、`title.py`、`z3cform/widgets/plandetails.py`、`z3cform/widgets/plandetails_datagrid_input.pt`、`profiles/default/rolemap.xml`、`profiles/default/workflows.xml`
* 文案：`locales/{en,zh,zh-cn,zh_CN}/LC_MESSAGES/maitux.stability.po` 与 `.mo`（8 个）

**新增（28）**

* 核心：`timepoints.py`、`plan_status.py`、`voiding.py`、`audit.py`、`automation.py`、`sampleautomation.py`、`samplegeneration.py`、`indexing.py`、`plandetails.py`
* `browser/`：`edit.py`、`generation.py`、`planstatus.py`、`revoke.py`、`samplegen.py`、`zeropoint.py`、`rowids.py`、`controlpanel.py`
* `browser/templates/`：`plan_status.pt`、`generate_sample.pt`、`revoke_sample.pt`、`zero_point_link.pt`
* `browser/viewlets/`：`stabilityplanstatus.py`、`stabilityplanzeropoint.py`、`templates/stabilityplan_status.pt`、`templates/stabilityplan_zeropoint_notice.pt`
* `profiles/default/`：`registry.xml`、`controlpanel.xml`、`workflows/senaite_stability_plan_workflow/definition.xml`

**技术细节参考**：`项目文档/稳定性模块/方案状态与过期规则-阶段6d-实施说明.md`（含故障根因链、四层防线、验收步骤）。
