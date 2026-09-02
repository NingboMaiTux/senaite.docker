# Reactivate 踩雷记录

## 背景

本次在 `maitux.workflow` 中为 SENAITE 2.x 增加样品、分析项、工作表联动的“重新激活”能力。

目标要求：

- 只通过 add-on 实现，尽量不改 `core`
- 兼容 Python 2.7
- 重新激活后保留原结果
- 失败时不能出现半成功状态
- 审计追踪里必须能看到“重新激活原因”

## 这次踩过的坑

### 1. 不能用简化版 workflow XML 直接覆盖官方 workflow

现象：

- 安装 add-on 时出现 `Invalid attribute: title`

根因：

- `profiles/default/workflows/.../definition.xml` 被当成完整 DCWorkflow 导入
- 但实际写进去的是“增量补丁式”内容，不是完整 workflow 定义

处理方式：

- 删除 add-on 自己的 workflow XML 覆盖方案
- 改为在 `setuphandlers.py` 里通过 Python 补丁给现有 workflow 动态补 transition

### 2. 站点数据库里的 workflow 不会自动跟着代码变

现象：

- 代码里已经有 `reactivate` / `reactivate_assigned`
- 页面点击仍报 `No workflow provides the 'xxx' action.`

根因：

- 代码已改，但站点数据库中的 workflow 配置没有同步刷新

处理方式：

- 通过安装步骤或 `setup_workflows()` 动态补丁
- 必要时在目标环境手工执行补丁逻辑并提交事务

### 3. Reactivate 确认页 GET 能找到对象，POST 却找不到对象

现象：

- 确认页能打开
- 提交后提示“未找到可重新激活的对象”

根因：

- 请求参数在不同场景下会出现：
  - `uids:list`
  - `uids` 字符串
  - `uids` 列表
- POST 时还可能出现 querystring 与 form 同时提交，导致重复值

处理方式：

- `get_uids()` 同时兼容 `uids:list`、字符串和列表
- 增加 UID 清洗与去重逻辑
- 模板提交统一改成 `uids:list`

### 4. 失败后对象出现半成功状态

现象：

- 样品状态已经回退
- 但分析项或工作表后续步骤失败

根因：

- 浏览器视图捕获异常后，没有显式终止本次事务

处理方式：

- 在提交异常分支中执行 `transaction.abort()`
- 保证任一步骤失败都整体回滚

### 5. `verified` 工作表没有合法的原生回退 transition

现象：

- 先报 `rollback_to_open` 不存在
- 改成 `retract` 后又报 `retract` 不存在

根因：

- 官方 `worksheet` workflow 中：
  - `to_be_verified` 支持 `rollback_to_open`
  - `verified` 不支持 `rollback_to_open`
- 同时 `worksheet.retract` 的 guard 还依赖其下 analysis 必须允许 `retract`
- 但 analysis 在对应状态下并不满足这个条件

处理方式：

- `to_be_verified` 工作表继续走官方 `rollback_to_open`
- `verified` 工作表改为受控同步到 `open`
- 同步时保留审计记录

### 6. 审计原因只写 metadata，原生 Changes 不会显示

现象：

- 审计记录存在
- 但 `@@auditlog` 的 `Changes` 一列看不到“原因”

根因：

- SENAITE 原生 `Changes` 只展示快照正文 diff
- `reason` 如果只写在 `__metadata__` 中，不会进入普通字段差异

处理方式：

- 不修改 `core` 的审计页面
- 在 add-on 自己写快照时，把“重新激活原因”写进快照正文
- 这样原生 diff 会自动显示：
  - `重新激活原因: Not set -> xxx`

### 7. Python 2.7 测试环境不能使用 Python 3 的标准写法

现象：

- `importlib.util`
- `types.SimpleNamespace`

在 Linux 测试环境报错

根因：

- 当前项目运行环境是 Python 2.7

处理方式：

- 测试动态加载统一使用 `imp.load_source`
- 不使用 `SimpleNamespace`
- 测试桩用普通对象或普通模块替代

### 8. 调试日志容易污染最终交付

现象：

- 为了排查 UID、transition、请求参数，加了大量 `logger.info/warning/error`

风险：

- 虽然有助于定位问题，但会污染正式日志输出

处理方式：

- 问题定位完成后移除临时调试日志
- 只保留真正的业务逻辑与错误处理

### 9. live workflow 可能被错误补丁覆盖到只剩 Reactivate

现象：

- 页面上只剩 `Reactivate`
- 样品 `verified` 状态看不到 `publish`
- 分析项 `to_be_verified` 状态看不到 `verify`、`retest`、`retract`、`reject`
- 即使重新新建样品再走流程，按钮仍然不恢复

根因：

- 之前错误的 workflow 补丁不仅改坏了自定义 transition
- 还把数据库中的 live `state.transitions` 覆盖成了只剩 `reactivate`
- 部分关键原生 transition 对应的 `permission-map` 也被覆盖或丢失
- 由于 workflow 配置保存在站点数据库中，所以代码修好后，旧站点不会自动恢复

处理方式：

- 不能只看代码，必须同时检查 live workflow 数据库里的：
  - `state.transitions`
  - `state permission-map`
- 正确做法是：
  - 在 `setuphandlers.py` 中显式恢复关键状态的原生 transitions
  - 同时恢复 `publish`、`verify`、`retest`、`retract`、`reject` 等关键权限映射
- 对已受影响环境，需执行一次 `setup_workflows()` 并提交事务
- 如果数据库已经被覆盖坏到只剩 `reactivate`，必要时需先在 `debug` 中手工修正，再重跑补丁

补充说明：

- 新建样品不会自动修复这个问题
- 只要站点数据库里的 workflow 还是坏的，新对象也会继续使用错误的 workflow 配置

## 第二轮（2026-09-02，范围收敛与落点修正）踩过的坑

### 10. `update_workflow` 只增不删 —— 把状态从清单里去掉是没用的

现象：

- 从 `update_workflow(states=...)` 里删掉某个状态之后，已安装站点上那个
  transition **还在**

根因：

- `senaite.core.api.workflow.update_workflow` 只创建和更新传入的条目，
  **漏写的状态原样保留**

处理方式：

- 另写 `ensure_state_reactivate_removed()`：把该状态的出口**强制复原**成原生清单，
  并把本包加的权限从 `permission_roles` 里删掉
- 撤权限要**删键**，不要 `setPermission(perm, 0, ())` ——
  删键之后 `getPermissionInfo()` 回到 `acquired=1`（本工作流不管这条权限），
  才是装上去之前的样子；显式置空等于声称"本状态管理这条权限并拒绝所有人"
- **两者在"按钮消失"上完全看不出区别**，只有 ZMI 权限页的 `acquire`
  复选框能区分（删键 → 勾选；置空 → 未勾选）

### 11. 落点写死 `assigned` 会造出"谁也够不着"的孤儿

现象：

- 激活一条不在工作表上的测试，它落在 `assigned`
- 该测试既不在任何工作表上，又**进不了任何工作表的「添加分析」列表**

根因：

- 工作表的「添加分析」只取 `review_state = unassigned`
- 而 `after_reject` / `after_cancel` **都会先把测试移出工作表** ——
  所以被拒绝/被取消的测试**必然**撞上这个坑

处理方式：

- transition 统一落 `unassigned`，仍挂在工作表上的由服务层同步回 `assigned`
- ⚠️ **不要用"先落 unassigned 再 `doActionFor(assign)` 补回去"**：
  `guard_assign` 第一句是 `is_worksheet_context()`，从样品页发起时永远为假，
  **而且是静默失败**

### 12. `IRejected` 不是装饰性标记，它控制着"要不要参与重算"

现象：

- 激活一条被拒绝的测试之后，状态活了，但录入上游结果时它不会被重新计算

根因：

- `get_dependents()` 默认 `with_retests=False`，会把带 `IRejected` 的项**滤掉**
- 而结果录入触发的 `recalculate_results` 用的就是默认参数

处理方式：

- 激活时必须 `noLongerProvides(analysis, IRejected)`
- 反过来：只激活上游、不动下游时**不得**去清下游的标记 ——
  那正是让下游安全留在重算集合外的机制
- 写"找出仍处于拒绝状态的上下游"这类代码时，**必须显式传 `with_retests=True`**，
  否则永远返回空、且看起来一切正常

### 13. 父样品回退：顺序反了等于没做

现象：

- 把父样品的回退从"只处理 verified/published"改成走原生
  `rollback_to_receive` 之后，样品仍然不动

根因：

- `guard_rollback_to_receive` 要求**样品下至少有一条 `unassigned`/`assigned` 的测试**
- 原代码是"先动样品、后动测试"，判断时那个条件必然不成立
- 而且 guard 为假**不报错**，样品只是静静地留在原状态

处理方式：

- 改成"**测试先走、父样品后退**"，与 core 的 `after_retract` 同序
- 用 `isTransitionAllowed()` 择路，不要拿状态名硬编码 ——
  否则样品侧范围一改，这里的清单就过期

### 14. `IGuardAdapter` 的 `layer=` 拦不住它，必须自己做站点级收口

现象（预防性，未实际发生）：

- `for="*"` 的 guard 适配器会在**所有站点**参与每一次工作流 guard 求值，
  包括从没装过本包的站点

根因：

- `guard_handler` 用 `getAdapters((instance,), IGuardAdapter)` 遍历，
  **查找签名里没有 request**，所以 ZCML 的 `layer=` 在这里无效
- 任一适配器返回 False 即否决整个 transition ——
  写错一行就能把别人站点的原生按钮拦掉，**而且现象是"按钮没了"、不报错**

处理方式：

- 新增 `siteinstall.py`，guard 第一句先判本站是否装了本包，未装一律放行
- 这是 `maitux.reviewerassignment` 的同构实现，**刻意复制而不是 import**
  （两个包之间不建立依赖）
- ⚠️ **跨站"没影响"单独看是无效证明**：本包的 guard 只对 `reactivate` 返回
  False，而未装站点本来就没有这个 transition —— "没坏"也可能只是因为它
  **压根没被调用**。必须另做一个能让 guard 真返回 False 的正面对照
  （本轮用的是：取消样品 → 其下被拒测试的按钮从有变无 → 恢复样品 → 按钮回来）

### 15. 接口 import 路径写错 = 整站起不来，且现象像"启动很慢"

现象：

- 容器进入重启循环，`docker logs` 尾部**退回到启动早期阶段**，看着像在慢慢起

根因：

- `IRequestAnalysis` 在 `bika.lims.interfaces.analysis`，**不在** `bika.lims.interfaces` 顶层
- 写错在 ZCML 加载期抛 `ImportError`，整站起不来

处理方式：

- 判断"还在起"还是"起坏了"：看 `docker inspect --format '{{.RestartCount}}'`，
  以及日志时间戳是否**倒退**到早期阶段
- 新增 import 前先核实定义位置：
  `grep -n "class IXxx" .../interfaces/*.py`

### 16. 验证方法本身出错，比被验的代码出错更难发现

本轮**四次**把观测手段的问题误读成了被观测对象的问题：

| 现象 | 真实原因 |
|---|---|
| 列表端点返回"按钮列表为空" | 路径写错 → 服务端 503，脚本把错误响应解析成了空列表 |
| 中文原因导致 `'utf8' codec can't decode byte 0xd6` | 本机 shell 按 GBK 编码了命令行，发出去的不是 UTF-8 |
| `getVerificators` 有值 → 以为签名闸留下脏数据 | 那是**历史值**，激活不清评审历史（对照组同样有值） |
| 确认页"有提醒" | 检测串 `alert alert-warning` 太松，命中了页面别处的元素 |

**教训**：判据脚本必须先判 HTTP 状态码再解析 body；
测中文表单一律用 `quote(s.encode('utf-8'))` 生成 body；
判断"某个东西出现了没有"要用**该功能独有的标记串**，不要用通用的 CSS 类名；
任何"没有变化"的结论都要配一个**能让它变化的正面对照**。

## 最终落地原则

- 不改 `core` 页面展示逻辑
- 审计原因由 add-on 写入快照正文，交给原生 `Changes` 自动显示
- 工作流回退逻辑按官方 workflow 实际能力做分支，不强行套不存在的 transition
- workflow 修复既要看 transitions，也要看 state permission-map
- 失败必须整体回滚，不能出现半成功状态
- 所有实现保持 Python 2.7 兼容

## 后续复用建议

- 新项目安装前，先确认 workflow 补丁确实已执行
- 旧环境升级时，要优先检查数据库中的 live workflow 是否已被历史错误补丁覆盖
- 涉及 workflow 审计展示时，优先考虑“把业务字段写进快照正文”，避免再去改 `core` 页面
- 涉及对象联动回退时，先确认官方 workflow 的真实 state/transition/guard，再写代码
