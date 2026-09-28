# maitux.stock

MAITUX 库存管理（Stock Management）扩展，提供库存条目、库存类型/单位、采购订单、库存批次（Stock Batch）及批次动作（领用 / 分装 / 归还 / 销毁 / 盘存 / 打印标签）的完整管理能力，并支持低量库存提醒与批次过期自动同步。

## 功能职责

- 内容类型（见 `src/maitux/stock/content/`）：
  - `StockManager`：库存管理根容器（侧边栏入口）。
  - `StockFolder` / `Stock` / `StockItem`：库存条目管理（编号、类型、样品基质、供应商、数量、单位、存储位置、批次默认到期日、到期提醒天数、领用是否需双人签名）。
  - `StockType` / `StockUnits`：库存类型与单位字典。
  - `StockPurchaseOrder` / `StockPurchaseOrders`：采购订单及订单行（含数量、单价、税率等）。
  - `StockBatch` / `StockBatches`：库存批次（批次编号自动生成、当前/目标数量、低量阈值、有效期、使用流水）。
  - `StockUsageRequest` / `StockUsageRequests`：**库存领用申请单**（申请明细、申请人、用途、审核人、驳回原因、电子签名留痕），领用需签名时由它承载"申请 → 审核签名 → 自动扣减"的链路。
  - `LowStockSection`：低库存入口（`LowStockBatchesView` 列表 + 门户顶部低量提醒 viewlet）。
- 批次动作页（`browser/stockbatch*.py` + 模板）：
  - 领用（`stockbatch_consume`，**两种模式**：直接领用 / 生成领用申请单送审）、归还（`stockbatch_return`）、分装（`stockbatch_split`，支持分装至已有批次或新建批次）、销毁（`stockbatch_destroy`）、盘存（`stockbatch_stocktake`）、打印标签（`stockbatch_print`，支持 Code128 / Code39 / QR 模板并导出 PDF）、审核领用（`stockbatch_review_usage`，跳转到待本人审核的申请单）。
- 领用审批（`usageapproval.py` / `guards.py` / `subscribers.py`）：
  - 工作流 `senaite_stockusagerequest_workflow`：草稿 → 待审核 → 已通过 / 已驳回 / 已撤回；`approve` 需**双人电子签名**（且申请人不能是签名人），`reject` 单人签名。
  - 审核通过时由 `IBeforeTransitionEvent` 执行扣减并写流水（含审核人 / 复核人留痕），失败整体回滚。
- 到期提醒与行标识（`expiryreminder.py`）：
  - `Stock.expiry_reminder_days`（默认 30，0=关闭）决定"到期前多少天开始提醒"；
  - 批次列表行按状态着色：进入提醒窗口 → 黄（`row-expiry-reminder`），已过期 → 红（`row-expiry-expired`），并追加到期徽标文案；
  - `Stock.expiry_date` 的语义是**批次默认到期日**：新建批次时预填，批次自身的到期日始终为准。
- 自带样式：`browser/static/maitux.stock.css` + `browser/viewlets/styling.py`（在 `IHtmlHead` 注入 `<link>`）。**样式随 addon 发布**，不再依赖改 `senaite.core` 的 bundle。
- 过期管理（`stockbatchexpiry.py`）：批次有效期到达后自动/手动同步为 `expired` 状态，过期批次仅允许销毁；提供定时任务入口 `@@sync_expired_batches`。
- 工作流：绑定 `senaite_stockbatch_workflow`，`active / expired / destroyed` 状态与 schema `status` 字段双向同步。
- 列表视图（Listing）：`stockbatches`、`lowstock`、`stock_items`、`stock_units`、`stock_types`、`purchase_orders`、`stock_usage_requests`，支持多选批量动作与状态页签。
- 词汇工厂（`configure.zcml` / `vocabularies.py`）：`maitux.stock.vocabularies.suppliers`。
- JSON 辅助接口：`stock_quantity_json`、`stock_suppliers_json`（表单级联用）。

## 依赖

- `senaite.core` / `senaite.lims`
- `plone.api`、`plone.supermodel`、`senaite.core.schema`
- `zope.component`、`zope.interface`、`z3c.form`
- `Products.CMFCore`、`Products.Five`

> 与 `maitux.stability` 无强制耦合；`maitux.stability` 的样品放置会引用本 addon 的 `StockBatch`。

## 安装注册（buildout）

```ini
[buildout]
develop += /opt/addons/customers/maitux.stock
eggs    += maitux.stock
[instance]
zcml    += maitux.stock
[plonesite]
profiles += maitux.stock:default
```

安装后自动创建 `stockmanager` 侧边栏入口及其子结构（`stock` / `stock_units` / `stock_types` / `purchase_orders` / `stock_batches` / `low_stock`）。

## 双语翻译（i18n）

本 addon 使用独立的 i18n 域 `maitux.stock`，全部用户可见文案（列表标题/列名/按钮、schema 字段、批次动作、模板文本、侧边栏菜单标题）均通过该域的翻译目录解析，支持界面语言在中英文之间切换。

- `configure.zcml`：`<i18n:registerTranslations directory="locales" />` 注册翻译目录。
- 翻译目录：`src/maitux/stock/locales/{en,zh,zh-cn,zh_CN}/LC_MESSAGES/maitux.stock.po`。
  ⚠️ **`.po` 入库、`.mo` 不入库**（仓库根 `.gitignore` 有 `*.mo`，原因见该文件顶部：
  `addons/customers` 是 bind mount，容器里重编译会写脏宿主机工作区），
  但**磁盘上必须有 `.mo`** —— 本环境没开 zope.i18n 自动编译，删了等于所有中文标签变英文。
  改了 `.po` 之后在本包目录跑：**`python tools/compile_mo.py`**（纯标准库 struct，Py2/Py3 通用）。
- 侧边栏菜单标题回退：`INNOCARE.arextension` 的 `senaite.core.i18n.translate` 附加域回退列表已包含 `maitux.stock`。

**写文案的三条硬规矩**（违反任意一条都会"切了语言没反应"，而且不会报错）：

1. 界面上出现的英文一律写成 **英文文本 msgid**，中文只放 `locales/zh*`；
   **不要**再用 `_(u"listing_xxx", default=u"Text")` 这种符号 msgid（英文站有漏出符号名的风险）。
2. Python 里凡是要显示的文案，必须带**本包域**的 Message（`_ = stockMessageFactory`），
   或是运行期用 `maitux.stock.i18n.translate_stock()` 明确翻译。
   schema 的 `title=` / `description=` / `label=` 尤其容易漏 —— 纯字符串 z3c.form 不翻译。
3. 模板要同时有 `i18n:domain="maitux.stock"` 和 `i18n:translate`；纯 `<script>` 里的文案
   用 `data-msg-*` 挂到元素上再让 JS 读，别直接硬编码。

## 更新说明（2026-08-31 · 双语翻译支持）

本次更新为该 addon 补充了完整的双语（中 / 英）翻译支持，遵循 `maitux.hazardcategories` 的 i18n 模式：

- `configure.zcml` 增加 `<i18n:registerTranslations directory="locales" />`。
- `__init__.py` 增加 `_` MessageFactory 别名（`maitux.stock` 域），并将工厂定义前置到 patches 导入之前，避免 `cannot import name _` 循环导入。
- 全部 browser / content 模块的消息工厂由 `bika/senaiteMessageFactory` 切换到本 addon 自有域（`from maitux.stock import _`），字符串按自身目录翻译。
- 新增中文翻译条目：列表标题/列名/操作按钮/状态页签（Active/Expired/Destroyed/All）、批次动作（领用/分装/归还/销毁/盘存/打印标签）、流水操作标签、schema 字段标题、门户消息、文件夹/侧边栏标题（Stockinventory/库存管理、Stock Item、Units、Stock Types、Purchase Orders、Stock Batches、Low Quantity 等），共 172 条 msgid。
- 模板补 `i18n:domain="maitux.stock"` + `i18n:translate`：`stock.pt`、`stockbatch.pt`、`stockbatchconsume/destroy/return/split/stocktake/print.pt`、低量 viewlet、采购行 datagrid。
- `setuphandlers.py` 的文件夹标题改为 Message 对象，随界面语言翻译。
- 翻译目录 `locales/{en,zh,zh-cn,zh_CN}` 及**磁盘上已编译的 `.mo`**（`.mo` 不入库，见上）；重启实例即生效，无需重装 profile。

## 更新说明（2026-09-22 · 领用审批 / 到期提醒 / 双语收尾）

### 1. 库存领用审批（申请单 + 双人电子签名）

- 新增内容类型 `StockUsageRequest` / `StockUsageRequests`（`content/stockusagerequest*.py`）
  与工作流 `senaite_stockusagerequest_workflow`（`profiles/default/workflows/`）。
- 新增 `usageapproval.py`：申请单落库、批次扣减、流水与审计留言的唯一入口；
  `guards.py` 提供"非申请人 / 审批角色 / fail-closed 签名检查"守卫。
- 领用页 `stockbatch_consume` 增加**申请模式**：只要所选批次里有"领用需电子签名"的库存，
  就**不允许直接扣减**，改为生成申请单并直接进入"待审核"：
  `提交申请（不签名）→ 待审核 → 审核人（非申请人）双人复核签名 → 自动扣减`。
- 批次列表新增"审核领用"动作（`stockbatch_review_usage`），点击跳到等待本人审核的申请单。
- 安装步骤幂等写入签名规则（`USAGE_REQUEST_SIGNATURE_RULES`）：
  `approve = require_countersign + disallow_initiator`，`reject = 单人 + disallow_initiator`，
  并显式删除历史遗留的 `submit` 签名规则（否则老站点提交申请还会弹签名页）。

### 2. 到期提醒与批次列表行底色

- `Stock.expiry_reminder_days`（Int，默认 30，0=关闭）：到期前多少天开始提醒。
- `Stock.expiry_date` 改语义为**批次默认到期日**（新批次创建时预填；批次自身的到期日为准）。
- `expiryreminder.py`：纯函数式计算剩余天数与行标识，输出
  `row-expiry-reminder`（黄 `#fff3cd`）/ `row-expiry-expired`（红 `#f8d7da`）
  与到期徽标文案；`browser/stockbatches.py` 把它追加到列表行的 `state_class` 上。

### 3. 样式改为随 addon 发布（**部署要点**）

- 新增 `browser/static/maitux.stock.css` + `browser/viewlets/styling.py`，
  在 `plone.app.layout.viewlets.interfaces.IHtmlHead` 注入
  `++resource++maitux.stock/maitux.stock.css`。
- 为什么不能像以前那样把规则追加进 `senaite.core` 的 `senaite.core.css`：
  docker 部署里的 `senaite.core` 是 buildout 从上游 fork 拉取构建的，
  本地改 core 的 bundle **不会进镜像**，行底色会静默失效。
- 也不要用 `plone.resources` / `plone.bundles` 新注册 bundle：SENAITE 的
  main_template 只渲染它自己那份 bundle 列表，addon 新注册的不会出现在页面上。

### 4. 中英双语补缺（本轮重点）

仓库副本里 2026-08-31 做过一轮双语改造，但工作副本后来被生成器版本覆盖回去了一部分，
造成"切了中文还是英文"。本轮把两个方向的差异合并成一份，并做了一次系统性体检：

- **消息工厂域**：18 个模块从 `from bika.lims import (bika|senaite)MessageFactory as _`
  换回本包域 `from maitux.stock import stockMessageFactory as _`。符号 msgid 在 bika 域
  查不到，会落回 `default`，中文站永远英文。
- **符号 msgid → 文本 msgid**：36 处 `_(u"listing_xxx", default=u"Consume")` 改成
  `_(u"Consume")`。这样英文站绝不会漏出 `listing_xxx` 这种符号名，中文站命中目录即中文。
- **schema 文案包 Message**：73 处 `title=/description=/label=` 的纯英文字符串改成
  `_(u"...")`。z3c.form / Dexterity **只翻译 Message 对象**，纯 unicode 永远不翻译
  且不报错（`content/stockbatch.py`、`stockpurchaseorder.py`、`stockusagerequest.py`）。
- **批次动作模板**：`stockbatchdestroy/print/return/split/stocktake.pt` 补回
  `i18n:domain="maitux.stock"` 与全部 `i18n:translate`（此前完全没标，中英文都显示英文）。
- **其它界面文案**：低量提醒 viewlet（原来是硬编码中文，英文站也显示中文）、
  采购订单行 datagrid（`Add row`、数量校验弹窗改为从 `data-msg-*` 读译文）、
  `stock_usage_setup` 的 portal 消息（原走 bika 域）全部双语。
- **R9b 合规**：`stockusagereport.pt` / `stockusagetrace.pt` 的 50 处中文默认文案改成英文
  （符号 msgid 不变 → 翻译结果不变，只是 catalog 未命中时的兜底文案变英文）。
- **翻译目录**：四个语言目录共新增约 140 条；`.po` 与磁盘上的 `.mo` 逐条比对一致
  （`maitux.stock` 现为 en 377 / zh 381 条；`.mo` 用 `python tools/compile_mo.py` 重新生成，不入库）。
  （`maitux.stock` 现为 en 377 / zh 381 条）。
- **体检工具**（本次新增，可复用）：AST 逐条提取 msgid 与目录比对；
  检查 schema 里未包 Message 的纯字符串；检查"符号 msgid + default"写法；
  乱码（GBK 误解码）检测。`python lint_addon.py --addon maitux.stock` 当前 **0 ERROR / 0 WARN**。

## 卸载

- 执行 `maitux.stock:uninstall` profile：仅从侧边栏移除 `stockmanager` 注册，不删除业务数据。

## 备注

- 批次编号由 `INumberGenerator` 持久化计数器生成（`subscribers.py`），并发安全。
- 批量动作对所选批次做服务端校验（`stockbatchactions.py` / `workflow.py`），前端按钮与后端限制保持一致。
