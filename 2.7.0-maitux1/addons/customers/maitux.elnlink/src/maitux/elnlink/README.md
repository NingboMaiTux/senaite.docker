# maitux.elnlink

MaiLIMS 这一侧的 MaiELN 集成（"MaiLIMS × MaiELN Integrated Demo Specification V1.0"）。
不改 senaite.core 的任何数据模型与工作流，只加四样东西：

1. **样品（AR）扩展字段**：`ELNExperimentNo / ELNExperimentTitle / ELNExperimentURL /
   ELNScientist / ELNDepartment / ELNProjectCode / ELNSampleURL`。由 MaiELN 登记样品时
   通过 JSON API 写入，界面上不可编辑（add / edit / view 表单均隐藏）。
2. **样品页 "Source Experiment (MaiELN)" 卡片**（viewlet，`IBelowContentTitle`）：
   显示来源实验、科学家、部门、项目，带 **Open Experiment in MaiELN / Open Sample in
   MaiELN** 深链接（LIMS → ELN 方向）。
3. **结果推送**：分析项发生 `submit / verify / retract / reject` 转换时，向
   `ELN_API_BASE/api/integration/eln/result` POST 一条 JSON（样品号、关键字、结果、
   中间值、结果范围、是否超限、状态、操作人）。只推送来自 MaiELN 的样品；推送失败只记
   日志，永不影响 LIMS 事务。ELN 也会主动拉取，漏推无害。
4. **演示数据端点**（仅 Manager）：`POST @@eln-demo-seed`（用户 / 部门 / 客户 / 样品
   类型 / 分析项目 / 规格 / 项目 PRJ-KRAS-001 / 样品编号格式 `SMP-<年>-{seq:06d}` 并把计
   数器拨到 001823 之前）、`POST @@eln-demo-reset`（删除演示样品、回拨计数器）、
   `GET @@eln-demo-status`。全部幂等。

## 环境变量（instance 容器）

| 变量 | 默认 | 用途 |
|---|---|---|
| `ELN_API_BASE` | `http://mainotebook-backend:8000` | 结果推送目标（容器网络内地址） |
| `ELN_PUBLIC_URL` | `http://localhost:5173` | 深链接用的 MaiELN 浏览器地址 |
| `ELN_INTEGRATION_TOKEN` | 空 | 推送请求头 `X-Integration-Token`，须与 MaiELN 的 `INTEGRATION_TOKEN` 一致 |
| `ELN_DEMO_PASSWORD` | 空 | 演示用户 chenwei / liming / wangjing 的口令；为空时 seed 拒绝创建用户 |

## 已在开发实例上确认的事实（2026-09-21）

- `configure.zcml` 必须先 `<include package="Products.CMFCore" file="permissions.zcml" />`：
  显式 slug 在 `five:loadProducts` 之前处理，否则 `cmf.ManagePortal` 尚未注册，整站
  起不来（ComponentLookupError）。
- 推送用 `urllib2.build_opener(urllib2.ProxyHandler({}))`：镜像里有 `http_proxy`，直接
  `urlopen` 会把容器内地址也送去代理（观察到空 502）。
- MaiELN 走 senaite.jsonapi：`POST analysisrequest/create/<client uid>`（扩展字段与
  ELN* 字段同一记录写入）、`POST update/<uid>` 加分析项（`Analyses: [{"uid": …}]`，裸
  uid 列表会被 jsonapi 自己的 `is_uid(value)` 丢掉）与 `{"transition": "receive"}`。
  `DateSampled` 按站点时区的**墙钟**校验（naive 值），带 `Z`/偏移的 ISO 会被判为"晚于
  现在"。分析员通过 jsonapi 只能写 `Result` / `InterimFields`（`Analyst` 403，由 submit
  自动落上）。
- 演示分析项目 precision = 1（96.7 %）；已存在的分析项目在 seed 时也会被改。

## 依赖

`senaite.core`、`archetypes.schemaextender`、`plone.api`。项目字段依赖 `maitux.projects`
（+ `INNOCARE.arextension`），未安装时 seed 会跳过项目创建并在日志里说明。

## 安装

目录放进 `addons/customers/`，重启容器（首次会跑 buildout），然后在
`站点/prefs_install_products_form` 安装 `maitux.elnlink`（注册 browser layer）。
