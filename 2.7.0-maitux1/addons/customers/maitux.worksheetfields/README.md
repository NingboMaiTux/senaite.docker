# maitux.worksheetfields

工作表页头多选扩展 Add-on（Worksheet header multi-select extension）

> SENAITE 2.x / Plone 5.2 / Python 2.7 环境专用（遵循根目录 `SENAITE-Addon开发规则.md`）。
> 本文档同时提供中文与英文说明。

---

## 1. 功能 / Features

针对「工作表结果录入页」（Worksheet `manage_results`，即工作表默认落地页）做如下改造：

1. **仪器多选（新字段 `instruments`）** —— 原页面顶部「仪器」单选下拉不再显示，改为
   **弹层搜索式多选**（新字段，值存 UID 列表，可关联多台仪器）。
2. **库存批次多选（新字段 `stock_batches`）** —— 页头新增**库存批次**弹层搜索式多选，
   选择 stock 模块（`maitux.stock`）的 `StockBatch` 对象（含已过期/销毁的全部批次）。
3. **隐藏原仪器单选与仪器采集入口** —— `manage_results` 页头不再显示原「仪器」单选格与
   「仪器采集 / 进入采集」格。
4. **仅作关联记录** —— 新字段只把多选仪器/批次记录在工作表上（追溯用），
   **不**改变表内每个分析自身的仪器/方法，也不触发自动分配。

**多选交互（美观与易用性考虑）**：页头只显示一个触发按钮（未选时“请选择仪器/请选择
库存批次”；选 ≤2 项直接显示名称；选更多折叠为“已选 N 项”并带完整清单 tooltip）。
点按钮弹出**搜索弹层**：顶部关键字过滤（选项多时可输入即筛）、列表勾选、已选项以
可移除的 chips 展示、底部提供 全选/清空/取消/确定。点「确定」才一次性保存并刷新页面，
取消/关闭不保存——避免逐项勾选时反复整页刷新。

对应英文：

1. **Multi-select Instruments (new field `instruments`)** — the original single
   "Instrument" dropdown on the Worksheet header is replaced by a popup-search
   multi-select (new field, UID list).
2. **Multi-select Stock Batches (new field `stock_batches`)** — a new popup-search
   Stock Batches selector in the header, choosing `StockBatch` objects from the
   stock module (`maitux.stock`), including expired/destroyed batches.
3. **Original instrument selector & instrument-acquisition entry hidden** — the
   original "Instrument" cell and the "Instrument Acquisition / 进入采集" cell are no
   longer rendered on the `manage_results` header.
4. **Record-only semantics** — the new fields are stored on the worksheet for
   traceability only; per-analysis instruments/methods are untouched and no
   automatic assignment is triggered.

**Interaction / UX notes**: the header shows a compact trigger button only (prompt
when empty, names when up to 2 selected, "N selected" with a full-list tooltip for
more). Clicking opens a **search popup**: keyword filter on top (type to filter when
there are many options), checkbox list, selected items shown as removable chips, and
Select all / Clear / Cancel / OK actions. Values are saved once when pressing **OK**
(a single page refresh); Cancel or closing the popup discards changes — no page
reload per checkbox tick.

### 改造范围之外 / Out of scope

- `/worksheets` 列表页顶部「新建工作表」横条（分析员/模板/仪器）保持不变；
  若在此选择带仪器的模板或仪器，工作表/表内分析仍按 senaite.core 原生逻辑
  被赋予单台仪器（本 addon 不干预创建流程，仅接管结果录入页的页头选择）。
- `/worksheets` 列表底部工具栏「仪器采集」按钮与 `worksheet_instrument_acquisition`
  采集视图保持不变（可按需另行扩展）；
- 表格内每个分析行自身的「仪器」列（per-analysis instrument）保持不变。

---

## 2. 实现方式 / How it works

| 需求 | 实现 | 位置 |
|---|---|---|
| 新字段（DX） | `plone.behavior`：`IWorksheetMultiSelectSchema`，两个 `UIDReferenceField(multi_valued=True)` | `src/maitux/worksheetfields/behaviors/worksheet.py` |
| 行为注册 | `<plone:behavior for="senaite.core.interfaces.IWorksheet">` | `behaviors/configure.zcml` |
| 安装启用 | `api.enable_behavior("Worksheet", …)` | `setuphandlers.py` |
| 页面覆盖 | 自定义浏览器层 `IWorksheetFieldsLayer` 继承 `IInstrumentAcquisitionLayer`，注册同名 `manage_results` | `interfaces.py` + `browser/configure.zcml` |
| 模板 | 基于 instrument_acquisition 的 `manage_results.pt`：去掉仪器/采集两格，新增两个「弹层搜索式选择器」（触发按钮 + Bootstrap 弹层：搜索/勾选/已选 chips/全选/清空/确定） | `browser/templates/manage_results.pt` |
| 保存 | 弹层点「确定」→ 提交隐藏表单（逗号分隔 UID）→ 视图 `__call__`（仅 POST）校验后经 schema field 写回 Worksheet 并 `reindexObject` | `browser/manage_results.py` |
| 双语 | `i18n:domain="maitux.worksheetfields"` + `locales/{en,zh,zh-cn,zh_CN}`（.po/.mo） | 页面模板 + `locales/` |

覆盖优先级（层继承链，保证本模块最终生效）：

```
ISenaiteCore
 └─ IReviewerAssignmentLayer        (maitux.reviewerassignment)
      └─ IInstrumentAcquisitionLayer (maitux.instrument_acquisition)
           └─ IWorksheetFieldsLayer  ← 本 addon
```

### 数据读写（供后续模块/报表使用）

行为字段按对象属性存储：`ws.instruments` / `ws.stock_batches`（值为 UID 列表），
也可用便捷函数：

```python
from maitux.worksheetfields.behaviors.worksheet import (
    get_worksheet_instruments,      # -> [uid, ...]
    get_worksheet_instrument_objects,  # -> [Instrument, ...]
    set_worksheet_instruments,      # 接受 uid/对象/列表
    get_worksheet_stock_batches,
    get_worksheet_stock_batch_objects,
    set_worksheet_stock_batches,
)
```

---

## 3. 依赖与安装前置检查 / Dependencies & pre-install check

**代码级依赖（需已存在于运行环境中，否则包无法加载）**：

- `maitux.instrument_acquisition`（浏览器层与 manage_results 基类）
- `maitux.reviewerassignment`（manage_results 基类链）
- `senaite.core`

**安装级前置检查（本 addon 安装时执行，需求 5）**：

安装 handler 的第一步会检查 stock 模块是否可用，判定方式二选一通过即可：

1. `portal_quickinstaller.isProductInstalled("maitux.stock")`；
2. `portal_types` 中存在 `StockBatch` FTI。

若两者都不满足，安装直接失败并给出明确报错：

> Cannot install maitux.worksheetfields: the stock module (maitux.stock,
> portal type 'StockBatch') is not installed. Please install the stock module
> first and run the install again. / 无法安装 maitux.worksheetfields：未检测到
> 库存模块（maitux.stock / StockBatch 类型），请先安装库存模块后再重试。

**因此：必须先安装并启用 `maitux.stock`（库存模块），再安装本 addon。**

代码位于 `setuphandlers.py::ensure_stock_module_installed`。

---

## 4. 部署步骤 / Deployment

> 依据 `SENAITE-Addon开发规则.md` R7/R8：`.py` / `.zcml` 改动必须重启容器；
> 模板改动重启即可；浏览器端如遇旧资源请硬刷新 `Ctrl+Shift+R`。

1. 将整个 `maitux.worksheetfields` 目录同步到容器 addon 目录
   （如 `/opt/addons/customers/maitux.worksheetfields`），
   确保 `setup.py` 的 `name='maitux.worksheetfields'` 与目录名一致（R5c/R5d）。
   若部署使用 `/gen-custom-addon.sh` 自动生成 slug，本包 **无** `overrides.zcml`
   （页面覆盖通过层继承在 `configure.zcml` 完成），无需额外 slug；若后续新增
   `overrides.zcml`，则需确认自动补 `-overrides` slug（R2）。
2. 确认容器内已存在 `maitux.instrument_acquisition`、`maitux.reviewerassignment`、
   `maitux.stock`。
3. 重启容器（加载新包 ZCML/代码）。
4. 在站点 **Add-ons** 面板安装 `Maitux Worksheet Fields (Instruments & Stock
   Batches)`：
   - 若 stock 模块未安装 → 安装失败并提示（见上）。
   - 安装成功后会：启用 Worksheet 多选行为（挂到 FTI）、安装浏览器层
     `maitux.worksheetfields`。
5. 浏览器硬刷新后进入任一工作表的结果录入页（manage_results）验证。

### 验证判据（R9，必须可观测）

| 检查点 | 预期信号 |
|---|---|
| 结果录入页页头 | 出现「仪器 / 库存批次」两个触发按钮（编辑态：未选显示提示、≤2 项显示名称、更多折叠为“已选 N 项”）；只读态显示已选文本 |
| 点触发按钮 | 弹出搜索弹层：顶部输入框可过滤、列表可勾选、已选项以 chips 展示，底部有 全选/清空/取消/确定 |
| 原「仪器」单选格 | 不再显示 |
| 「仪器采集 / 进入采集」格 | 不再显示 |
| 勾选多台仪器后点「确定」 | 一次性保存并刷新；选择保持；顶部出现“工作表仪器已保存。”；取消则不改动 |
| 搜索多个批次（含过期批次也能搜到） | 弹层选项含全部 StockBatch（含 expired/destroyed） |
| 英文站点 | 界面显示英文；中文站点（zh_CN）显示中文 |
| 新建一个 Worksheet | `ws.instruments` / `ws.stock_batches` 属性为空列表，可选填 |

### 卸载 / 回滚

卸载 profile 已在代码中提供但按仓库惯例被隐藏（`HiddenProfiles`）。需要回滚时：

- 直接方式：在 ZMI `portal_setup` 中导入
  `profile-maitux.worksheetfields:uninstall`（摘除行为）；
- 手工移除行为：
  `python`：`api.disable_behavior("Worksheet", "maitux.worksheetfields.behavior.worksheetmultiselect")`；
- 移除包目录并重启容器（同时保留/删除旧数据由你决定：已写在工作表对象上的
  `instruments` / `stock_batches` 属性会随对象保留，摘掉行为后不再有 schema 描述）。

---

## 5. 翻译维护 / Translations

页面文案 msgid 使用英文，`locales/zh_CN` 等提供中文翻译，英文站点直接使用默认
英文文本。目录结构：

```
locales/
  en/LC_MESSAGES/maitux.worksheetfields.{po,mo}      # 英文（identity）
  zh/LC_MESSAGES/...
  zh-cn/LC_MESSAGES/...
  zh_CN/LC_MESSAGES/...
```

修改 `.po` 后重新编译 `.mo`：

```bash
python tools/compile_mo.py
```

（`tools/compile_mo.py` 为标准库实现，无需 gettext 工具链，兼容 Python 2/3。）

---

## 6. 目录结构 / Package layout

```
maitux.worksheetfields/
├── setup.py                  # 分发名与目录名一致（R5c）
├── MANIFEST.in
├── README.md
├── src/maitux/
│   └── worksheetfields/
│       ├── configure.zcml        # include senaite.core.permissions（R1）+ 翻译 + 子包
│       ├── interfaces.py         # IWorksheetFieldsLayer（层继承链顶端）
│       ├── config.py             # 常量（字段名/行为名/类型名）
│       ├── setuphandlers.py      # 安装：stock 前置检查 + enable_behavior；卸载
│       ├── behaviors/            # plone.behavior：instruments / stock_batches 字段
│       ├── browser/
│       │   ├── configure.zcml    # manage_results 覆盖（ViewResults 权限）
│       │   ├── manage_results.py # 视图：选项/已选/保存
│       │   └── templates/manage_results.pt
│       ├── profiles/{default,uninstall}/
│       └── locales/{en,zh,zh-cn,zh_CN}/LC_MESSAGES/
└── tools/compile_mo.py
```

## 7. 开发规则符合性自查 / Checklist compliance

- [x] 新字段走 `plone.behavior`（Worksheet 为 DX 类型，AT schemaextender 无效）
- [x] 用到 SENAITE 自定义权限（`ViewResults`）的注册：`configure.zcml` 顶部
      `<include package="senaite.core.permissions" />` 钉住注册顺序（R1）
- [x] 同名页面覆盖通过**层继承**实现，无 ZCML 同名注册冲突（R5 精神）
- [x] 分发名与目录名一致；依赖 autoinclude 入口点，不手动 include（R5c）
- [x] `registerProfile` 目录真实存在且含 `metadata.xml`（R4）
- [x] 提供 `profiles/uninstall/`（非合规豁免类，R4b）
- [x] 部署说明区分「重启」与「重启+硬刷新」（R8）
- [x] 每项功能给出可观测验证判据（R9）
- [x] `actions.xml`/`controlpanel.xml` 未新增任何非 ASCII title（R9b 不适用）
