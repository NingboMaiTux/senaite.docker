# maitux.instrument_acquisition —— 仪器采集插件说明

SENAITE（LIMS）仪器数据采集插件：采集页绑定解析模板 → 按模板连接仪器 /
对接本地采集端（labgate）→ 接收读数 → 解析 → 分配/回写到 Worksheet 的
Interim Field → 可选 HTTP 转发到第三方系统。

> 适用版本：SENAITE core 2.x / Plone 5 / Zope 4（Python 2.7）
> 采集端：`labgate`（Go，边缘网关，见 labgate 项目 README）

---

## ★ 1.1.1：修两个只有单测真跑起来才看得到的问题

`tests/test_session_store.py` 的 38 条测试**从来没真跑过**：文件顶部
的 try 块里 import 了一个在本版 `zope.annotation` 里根本不存在的名字
（`attribute.AttributeAnnotatable`），`_IMPORT_OK` 恒为 False，unittest
只报 "skipped 38" 不报错。harness 已随 1.1.0 修好，真跑起来之后
暴露出一个真产品 bug：

### ★ `flush_relay_readings`：重试预算在**一次** flush 里就烧光了（丢数）

进程内 relay 模式下，采集页每次轮询调 `flush_relay_readings` 把队列里
的读数写进会话。单条写入失败时重新入队，最多重试
`RELAY_FLUSH_MAX_RETRIES`（5）次 —— docstring 写的是“下个轮询周期重试”。

实际不是。`relay.requeue()` 把读数放回的是**同一个队列**，而 requeue
写在 `while True: pop` 的循环体里 —— 下一轮循环立刻又把它 pop 出来重试。
**5 次重试在同一次 flush 内耗尽，读数当场丢失**；下一个轮询周期根本
等不到。一次瞬时性拒绝（切会话、ZODB 冲突）就能把一次称量静默抹掉。

修法：失败的读数先攒起来，**等本轮排空队列之后**再统一 requeue。
日志也跟着改了：原先的 `failed` 按“尝试次数”计（一条读数会报 5 次），
现在分开报 `retrying` 与 `dropped`。

回归测试 `test_flush_retry_budget_spans_poll_cycles` 把“每个轮询周期只消耗
一次重试额度”钉死了。

### 其余是测试自己写错（不改产品）

| 桩 | 错在哪 | 后果 |
|---|---|---|
| `api.is_object` 桩恒 True | 真的 `is_object(None)` 是 False | `ensure_session` 的“没分配仪器”那道门测不到 |
| `api.get_object` 桩只认分析 | portal 会话索引存的是 `worksheet_uid` | 会话反查 / 跨工作表占用互斥 / force 挤占整条链路恒为 None |
| 没打桩当前用户 | zopepy 无安全上下文，`_get_user_id()` 恒 u"" | `occupied_by` 恒空，“记录占用者”立不住 |
| `test_unassign_returns_pending` 的 `assertNotIn` | 描述的是“撤销就删整条 assignment”的旧行为 | 现在是**只解绑、不删行**（数组字段的手动添加行靠 assignment 存在），已改成核“占位还在、绑定已清” |

跑法（容器内，**不能用 `bin/instance run`**，会 OOM 杀实例）：

```bash
docker exec maituxlimslatest /home/senaite/senaitelims/bin/zopepy -c '
import unittest, sys
sys.path.insert(0, "/opt/addons/customers/maitux.instrument_acquisition/src")
suite = unittest.TestLoader().loadTestsFromName(
    "maitux.instrument_acquisition.tests.test_session_store")
unittest.TextTestRunner(verbosity=1).run(suite)'
```

---

## ★ 1.1.0：采集目标位改为可配置（原先写死 `T_name` / `T_weight`）

**1.0.0 把采集目标写死成两个 keyword**（`T_name` / `T_weight`），而线上任何
Calculation 都没有这两个字段 —— 采集页因此一个目标位都渲染不出来。

**1.1.0 起，"哪些字段参与采集"由配置决定**：在 Calculation 的 interim 字段上
配两个标记（由 `maitux.calcenhance` ≥1.6.0 注册为 subfield）：

| 标记 | 取值 | 含义 |
|---|---|---|
| `采集角色` `acquisition_role` | `name` / `weight`（空 = 不参与） | `name` = 名称录入框，`weight` = 重量接收区 |
| `分组号` `acquisition_group` | `0` = 不参与；`≥1` = 组号 | 同组字段绑同一行 |

留在代码里的只有**角色词表**（`name` / `weight` 两个取值及其槽位元数据），
见 `services/phase1_targets.py`。

### 三条上手就会踩的

1. **★ 标记是快照进分析行的，不追溯。** 标记配好之后**新建**的样品才会出现
   采集目标位；已有的分析不会追溯（SENAITE 的 interim 快照机制，
   见根 `CLAUDE.md` §6.3.2）。采集页的空状态提示里写了这一条。
2. **★ 重新生成配置 XLSX 再导入会冲掉标记** —— 生成器目前还不认这两列
   （已单独立项）。导入后请回读这两列，或看 calcenhance 那条点名
   Calculation 与 keyword 的 warn。
3. **★ `locked` 目前还不能给采集字段标上。** 机器写入通道还没包
   `allow_locked_writes()` 逃生阀（S6 待做），标了就会"写一次再也改不了"。

### 表格排版

采集页「待分配目标列表」**固定 6 列**（样品 / 组 / 分析 / 名称 / 重量 / 状态·操作）。
一组里可以有**任意多个** `weight` 字段，它们在「重量」这一格内纵向堆叠，
各带自己的标题与操作 —— 所以 3 个、5 个称量都装得下，表头不变。

★ **样品列不可省。** 一个 Worksheet 常常装着多个样品的**同一个** AS
（实测 WS-008 三行全是「有关物质-系统适用性」，分属 S-0007 / S-0008 / S-0009）。
只显示分析标题时三行一模一样，操作者分不清在给哪个样品称量。
读数的「选择分配目标」下拉同理，标签带 Sample ID 前缀。
列表按**样品优先**排序，一个样品的活儿聚在一起。

### 一次称量落到多个样品：「同步到其它 N 个样品」

系统适用性这类测定**现实上只称一次**，但 SENAITE 要求**每个 AR 下都有**
这个分析（一个 Sample 上同一个 AS 只能有一个，见根 `CLAUDE.md` §6.3.3）——
于是同一个称量值要落到 N 个样品的分析上。

采集页的每一组，只要本 Worksheet 里**存在其它样品的同名分析**，
「状态 / 操作」列就会出现 **「同步到其它 N 个样品」**：先在一行里填好
（或绑好读数），点一下，组内**全部字段**一次写进其它样品的同名分析。

实测 WS-008：填 3 次 + 点 1 下 + 保存 = 9 个 interim 值三份完全一致，
代替原来的填 9 次。

三条要点：

- **每样品仍各占一行**，不归并 —— 看得到每个 AR 确实都有值。
- **没有引入任何新标记。**「哪个字段是共用的」由**操作者点这个按钮**表达，
  不写进配置：分配本来就由人完成，这里解决的只是方不方便。
  （供试品称量每个 AR 不同，就别点这个按钮。）
- **覆盖会说出来。** 兄弟行上已有**不同**的值时照样覆盖（点"同步"就是这个意图），
  但消息里会写「其中 N 处覆盖了原有不同的值」；兄弟行快照里没有标记的
  （标记导入前建的老分析）会跳过并点名。

---

## 一、功能说明

### 1. 总体流程

```
仪器（天平/串口服务器，TCP）
   │  (a) 进程内 relay 模式：LIMS 直接连仪器收数
   │  (b) 远端采集端模式（默认）：labgate 连仪器，读数 HTTP 推回 LIMS
   ▼
LIMS 采集页（Worksheet）
   │  按 event_id 幂等去重、按 instrument_code 归入当前监听会话
   ▼
读数列表（pending / assigned / saved / discarded）
   │  手动分配或自动回写
   ▼
Worksheet Interim Field：由标记指定（role=name 的名称、role=weight 的重量）
```

默认模式是 **远端采集端模式**（`PHASE1_AGENT_MODE = True`）：LIMS 与仪器
不在同一网络，由实验室本地的 labgate 采集端连接仪器，读数推回 LIMS；
LIMS 点「开始采集」只是标记会话监听并通知采集端连接仪器。

### 2. 采集会话状态机

- 会话状态：`active`（活动）→ `closed`（关闭）
- 监听状态：`listening=True`（采集中）/ `listening=False`（未监听）
- 读数状态：`pending`（待分配）→ `assigned`（已分配）→ `saved`（已保存写回）；
  也可 `discarded`（废弃）
- 同一仪器同时只允许一个监听会话；其他用户点「开始采集」会弹确认框，
  确认后 `force=1` 挤占（自动停掉对方会话并通知其采集端断开）

### 3. 核心接口（HTTP，全部 `zope.Public`）

请求头统一用 `X-Instrument-Token` 携带采集端 Token。

| 接口 | 方法 | 用途 |
|---|---|---|
| `@@instrument_acquisition_api_ingest` | POST | 采集端上报读数（body 含 event_id / instrument_code / raw_text / parsed） |
| `@@instrument_acquisition_api_agent_instruments` | GET | 采集端轮询：按 Token 反查其负责的全部仪器与启停指令 `{instruments:[{code,start,ip,port}]}` |
| `@@instrument_acquisition_api_agent_config` | GET | 旧接口：按 `instrument_code` 查单台仪器启停指令 `{start,ip,port,session_id,...}` |
| `@@instrument_acquisition_api_templates_list` | GET | 解析模板列表 |
| `@@instrument_acquisition_api_forward_test` | GET | 测试模板的 HTTP 转发配置 |
| `@@instrument_acquisition_api_forward_status` | GET | 查询转发状态/队列 |
| `@@instrument_acquisition_api_forward_history` | GET | 查询转发历史 |
| `@@instrument_acquisition_api_manual_forward` | POST | 手动触发转发 |

**ingest 上报约定（与 labgate 一致）：**

- body 字段：`event_id`（必填，幂等键，格式 `agent-<32位hex>`）、
  `instrument_code`、`received_at`、`raw_text`、`parsed{value,unit,stable}`、
  可选 `site_id`、`session_id`
- Token 校验：优先按模板登记的 `agent_token` 校验；等于固定共享 Token
  `PHASE1_INGEST_TOKEN` 时始终放行（兼容旧采集端）
- 会话归属：带 `session_id` 按会话；不带则按 `instrument_code` 归入该仪器
  当前监听会话（无监听会话返回 404 `No active listening session`）
- 幂等：同一 `event_id` 重复上报返回 `duplicate`，不重复写入
- 响应：`200 + {status: created|duplicate, success: true}`

**agent_instruments 下发约定（labgate 轮询）：**

- 按 `X-Instrument-Token` 反查所有 `agent_token` 相同的解析模板
- 每台仪器：LIMS 有监听会话 → `{code, start:true, ip, port}`（ip/port 来自
  模板 `ip_address` / `port`）；否则 `{code, start:false}`
- 采集端据此自动连接/断开各仪器，**无需在采集端本地配置仪器信息**

### 4. 读数解析与写回

- 解析脚本：模板字段 `script_file` 上传 `.js` 脚本，入站数据经 JS 解析出
  `parsed{value,unit}`
- 目标位：由 interim 标记决定 —— `role=name`（名称，单值）、
  `role=weight`（重量，可多个；`result_type=list` 时支持数组多行），
  target_key 格式 `{analysis_uid}:{keyword}[:{seq}]`
- 手动导入：PDF 报告经 `browser/deemo` 的提取/JS 解析/写回逻辑
  （`services/acquisition.py::parse_and_write_report` 复用同一套逻辑）
- 写回：读数分配到目标位后写入 Worksheet 的 Interim Field；支持
  `add_target_row` / `remove_target_row` 增删数组行

### 5. HTTP 转发（可选，模板级开关）

模板字段 `forward_enabled` 打开后，解析出的数据可按 `forward_url` /
`forward_method`（POST/PUT）/ `forward_headers` / `forward_timeout` 转发到
第三方系统（`forwarder.py`，重试 3 次、退避 1 秒）。

### 6. 采集页（Worksheet 视图）

- 进入采集页自动 `ensure_session` 创建活动会话
- 徽章显示采集端连接状态（远端模式查询 labgate `/api/state?code=xxx`）
- 「开始采集」：远端模式调用采集端 `/api/start_sync`（带 host/port/push/code），
  连接失败当场报错；进程内 relay 模式由 LIMS 直连仪器
- 读数卡片：`#event_id前8位` + 解析值/单位 + 原始文本 + 状态徽章
- 分配：下拉选择目标位（分析行上被标记的字段）

---

## 二、配置说明

### 1. 解析模板（InstrumentParsingTemplate）

SENAITE 后台「仪器 → 解析模板」新建/编辑：

| 字段 | 说明 | 必填 |
|---|---|---|
| Name | 模板名称 | 是 |
| Instrument | 绑定的仪器（`Instrument` 类型） | 是 |
| Port | 仪器 TCP 端口（天平地址端口） | 采集中必填 |
| IP Address | 仪器 TCP 地址（天平地址 IP） | 采集中必填 |
| 采集端接口地址 (Agent API URL) | 本地采集端 HTTP 地址，如 `http://192.168.1.5:8090`（与天平 IP/端口分离） | 远端模式必填 |
| 采集端 Token | 采集端鉴权凭证，一个中转站一个 Token；多台仪器共用可填相同值 | 远端模式必填 |
| Parser Script File | 解析脚本（.js），把原始行解析成 `{value, unit}` | 按需 |
| Enable HTTP Forward | 是否把解析数据转发到第三方 HTTP 接口 | 否 |
| Forward URL / Method / Headers / Timeout | 转发目标与参数 | 转发时填 |

> 仪器也可以不绑定模板，改用仪器扩展字段
> （`extender/instrument.py` 的 `FIELD_NAME`）指定模板。

### 2. 代码级开关（services/phase1_targets.py）

| 常量 | 默认 | 说明 |
|---|---|---|
| `PHASE1_AGENT_MODE` | `True` | `True`=远端采集端模式（labgate）；`False`=进程内 relay 模式 |
| `PHASE1_INGEST_TOKEN` | `maitux-phase1-instrument-acquisition-token` | 固定共享 Token（兼容旧采集端；新部署建议用模板 `agent_token`） |
| `PHASE1_TCP_PROBE_TIMEOUT` | `3` | 开始采集时 TCP 连通探测超时（秒） |
| `ACQUISITION_ROLE_META` | `name` / `weight` 两个角色的槽位元数据 | 角色词表（目标位本身由 interim 标记决定，不写死） |
| `PHASE1_TARGET_DEFINITIONS` | 名称/重量 | 目标位定义（keyword、显示标题、是否多值、排序、值类型） |
| `PHASE1_ANNOTATION_KEY` / `PHASE1_SESSION_INDEX_KEY` | `maitux...v1.session*` | Worksheet annotations 存储键 |

### 3. 与 labgate 采集端联动配置（本次联调结论）

| 项 | 值 |
|---|---|
| labgate 配置 `cloud.lims_url` | `http://<LIMS 主机>:8081/lims` |
| labgate 配置 `cloud.token` | = 模板「采集端 Token」（如 `jklNg_...`） |
| labgate 配置 `agent.mode` | `auto` + `cloud.poll_enabled=true`（轮询下发仪器清单） |
| labgate 配置 `cloud.lims_push_enabled` | `true`（读数 HTTP 直推 LIMS ingest） |
| labgate 容器连本机仪器 | `extra_hosts: "192.168.1.5:host-gateway"`（容器内连宿主局域网 IP） |
| LIMS 模板「采集端接口地址」 | `http://<labgate 主机>:8090` |

**联动注意事项（踩坑记录，2026-08）：**

- 「开始采集」/「停止采集」通知已改为携带 `code`（`session_store.py`），
  避免采集端用不到真实仪器 code 而建错连接（读数推不进、报 Invalid token）
- 采集端收到的读数若 `instrument_code` 在 LIMS 无模板，ingest 返回 401
  Invalid token；labgate 已改为有界重试（5 次后放弃），不会无限刷屏
- labgate 轮询 `agent_instruments` 时，模板 `agent_token` 必须与 labgate
  配置 token 完全一致（`_verify_token` 对固定共享 Token 始终放行，但
  `agent_instruments` 按模板 token 严格反查）
- 采集页徽章显示的「已登记，等待 LIMS 开始采集」说明采集端已从轮询
  得知该仪器，只等 LIMS 下发开始指令

---

## 三、常用排查

| 现象 | 处理 |
|---|---|
| 采集页徽章「该仪器未在本采集端登记」 | 模板 `agent_token` 与 labgate 配置 token 不一致；或 labgate 未启动轮询（mode=auto + poll_enabled） |
| 读数推不进，LIMS 日志 Invalid token | 检查读数 `instrument_code` 对应模板存在且 `agent_token` 匹配 |
| 点「开始采集」立即失败 | 模板 `ip_address`/`port` 未配，或采集端连不上仪器（TCP 探测失败）；远端模式看 labgate 日志 |
| 读数出现在页面但无值 | 解析脚本未配或解析不出 `value`；用 `instrument_acquisition_debug` 页面调试 JS 解析 |
| 读数重复 | 正常：同一 event_id 重复上报会去重（duplicate）；检查采集端 event_id 是否稳定生成 |
