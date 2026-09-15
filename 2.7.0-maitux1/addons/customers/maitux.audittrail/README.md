# maitux.audittrail — 审计追踪页可读性增强

SENAITE 2.x（Plone 5.2 / Python 2.7）客户 add-on。覆盖原生 `@@auditlog`
视图，把**记下来了、但人读不出来**的快照数据渲染成人类可读形式。

适用对象是所有提供 `IAuditable` 的上下文（样品、分析项、计算、工作表、
批次……），**包括 Worksheet**。

> 本包对站点行为**零改动**：只覆盖渲染，不碰数据、不碰工作流（规则 R10）。
> 没有 `overrides.zcml`，不需要 `-overrides` slug。
> **不改动任何 `profiles/**` 内容**，因此已安装站点**不需要**重跑 profile
> 或重装 add-on（R3 不触发），部署只需同步代码 + 重启容器。
> 包外状态：没有（全部在 ZODB 的快照里）。

---

## 1. 三类"读不出来"的数据，现在都能读

| # | 数据 | 原来长什么样 | 现在 |
|---|---|---|---|
| 1 | Calculation / Analysis 的 **Interim Fields** | `[{"keyword": "NM", "title": ...}]` 一坨 JSON | 关键字 / 字段标题 / 结果类型 / 默认值 / 公式 / 单位 / 选项 / 标志 八列表格 |
| 2 | **Worksheet 的 Layout**（`layout_view`） | `[{"position": 1, "type": "a", "container_uid": "df2a…", "analysis_uid": "9c31…"}]` | # / 位置 / 类型 / **样品标题** / **分析项标题** 五列表格（本次新增） |
| 3 | 其它**泛化 JSON 数据**（dict / list[dict] / 字面 JSON 串） | `json.dumps` 出来的原始串，中文还是 `\uXXXX` | 键值表 / 记录表 / 项目符号列表（本次新增） |
| 4 | **电子签名**（`maitux.esignature` 写进快照 metadata） | 原审计列表 10 列，没有任何一列读它 —— 记了从不显示 | 新增「电子签名」列，默认可见 |

第 4 项是 21 CFR Part 11 §11.50(b) 的要求（签名 manifestation 必须是
"电子记录任何人类可读形式"的组成部分）；第 1–3 项是同一件事的另一半：
审计页的价值全在"能不能读"。

---

## 2. Worksheet 那一格原来为什么读不出来

工作表的工作流数据在快照里是 **DataGridField**，值是 JSON 意义上的
`list of dict`（见 `senaite.core.content.worksheet.addToLayout`）：

```python
{"position": 1, "type": "a", "container_uid": "<样品 UID>", "analysis_uid": "<分析项 UID>"}
```

`bika.lims.api.snapshot._process_value` 对字典走
`json.dumps(sorted(value.items()), indent=1)`，对列表按 `"; "` 拼 —— 于是
审计页上出现的是**一坨原始 JSON**，两个 32 位 UID 谁也认不出。结果显示
"第几格、哪个样品、哪个分析项"变了，读者得自己去别处查 UID。

---

## 3. 实现

| 文件 | 职责 |
|---|---|
| `browser/auditlog.py` | 覆盖 `@@auditlog`：加签名列、决定每行走哪种渲染模式、注入 UID 解析器 |
| `browser/formatter.py` | 纯函数渲染器（Interim Fields / 工作表布局 / 通用 JSON / 签名）。**不 import bika.lims** |
| `browser/templates/auditlog_diff.pt` | 三种渲染分支的模板 |

### 3.1 三种渲染模式互斥

`render_diff` 为每个字段行算出一个 `mode`，模板只认三个布尔量：

| mode | 触发条件 | 渲染 |
|---|---|---|
| `interim` | 字段名是 `InterimFields` / `interim_fields` 且值是列表 | Interim Fields 表格 |
| `structured` | 值是工作表布局行，或任何 JSON 容器形态 | 修改前 / 修改后各一张表 |
| `text` | 其它（标量、UID 列表、普通文本） | 原生的 `code` + `→` |

> **坑（已用测试钉住）**：模板里三个 `tal:block` 的 `tal:condition` 是
> **各自独立**的。原来第三个分支写的是 `not:row/is_interim_fields`，
> 加结构化分支后它会**把结构化行也再渲染一遍 code**。所以第三个分支现在
> 判 `row/is_text`，而不是取反。

### 3.2 一行里前后值形态不同怎么办

取"最能读出内容"的那个模式（`interim` > `structured` > `text`），
保证"修改前是 JSON、修改后是空"这类变更不会一半表格一半裸串。

### 3.3 UID 解析是注入的，不是 import 的

`render_worksheet_layout_html(value, uid_resolver=...)` 的解析器由视图注入
（`AuditLogView.resolve_uid_title`），`formatter.py` 因此**保持脱离 Plone
可直接单测**（`test_auditlog_source` 里有一条测试专门守这个取舍）。
视图侧同一个 UID 在一次渲染里只查一次（`_uid_title_cache`）。

**解析不出来时回落显示裸 UID**，绝不留空白 —— 对象被删掉是审计场景的常态，
空白等于把记录吞了。

### 3.4 不丢内容是底线

- JSON 串只在首字符是 `[` / `{` 时才尝试解析，失败一律原样返回；
- 嵌套超过 3 层退回**转义后的 JSON 文本**（`<pre class="audit-json-raw">`）；
- 所有输出统一走 HTML 转义（`safe_html`）。

---

## 4. 部署

| 改动内容 | 生效方式 |
|---|---|
| `.py`（`auditlog.py` / `formatter.py`） | **必须重启容器** |
| `.pt` 模板 | **必须重启容器**（Chameleon 按内容摘要自动失效缓存） |

**不需要**重跑 GenericSetup profile，也**不需要**重装 add-on：本次没有新增
或修改 `profiles/**`（规则 R3 只在 profile 文件变化时触发）。
浏览器端无新增静态资源，无需硬刷新。

---

## 5. 验证判据（可观测）

重启容器后，打开任一**工作表**的 Audit Log 页
（`<worksheet>/@@auditlog`），找 "Layout" 那一行：

| 检查点 | 预期信号 |
|---|---|
| Worksheet 布局变更行 | 显示表格，表头是 `# / 位置 / 类型 / 样品 / 分析项` |
| 类型列 | 显示 `常规分析` / `空白` / `质控` / `平行样`，不是单字母 `a/b/c/d` |
| 样品列 | 显示样品编号（如 `AP-0001`），**不是** 32 位 UID |
| 分析项列 | 显示检查项目标题（如 `Ca_Rf`），**不是** 32 位 UID |
| 行内是否残留 JSON | 页面源码里该行**不再出现** `[{"position"` / `container_uid` / `analysis_uid` |
| 前后对照 | 「修改前」「修改后」各一张表，中间 `→` |
| 被删除的对象 | 该格显示**裸 UID**（`<Deleted …>` 或原 UID），**不是空白** |
| 泛化 JSON 字段 | dict 显示成「键 / 值」两列表；记录表带 `#` 列 |
| 回归：Interim Fields | Calculation / Analysis 的 Interim Fields 行仍是原八列表格 |
| 回归：电子签名 | 「电子签名」列仍在，签名人 / 时间 / 含义 / 原因都在 |
| 回归：普通字段 | Title / Analyst / Review State 等仍是 `code` + `→` 样式 |
| 回归：快照列 | 「Snapshot」列仍显示完整原始 JSON（**故意保留**，审计需要原样留底） |

单测（本机 Python 2.7 即可，不需要 Plone）：

```bash
cd <addon>/src/maitux/audittrail/tests
python -m unittest test_formatter
python -m unittest test_auditlog_source
```

当前 **48 个用例全绿**（`test_formatter` 34 + `test_auditlog_source` 14）。

---

## 6. 目录结构

```
maitux.audittrail/
├── setup.py                       # 1.2.0；分发名与目录名一致（R5c）
└── src/maitux/audittrail/
    ├── configure.zcml             # include senaite.core.permissions（R1）
    ├── interfaces.py              # IAuditTrailLayer(ISenaiteCore, IBikaLIMS)
    ├── setuphandlers.py           # 安装 / 卸载 handler + HiddenProfiles
    ├── browser/
    │   ├── configure.zcml         # @@auditlog 覆盖（layer 门控）
    │   ├── auditlog.py            # 视图：签名列 + 渲染模式 + UID 解析
    │   ├── formatter.py           # 纯函数渲染器（可脱离 Plone 单测）
    │   └── templates/auditlog_diff.pt
    ├── profiles/{default,uninstall}/
    └── tests/{test_formatter,test_auditlog_source}.py
```

---

## 7. 已知边界

- **WorksheetTemplate 的 `template_layout` 不走布局渲染器**：它的行键是
  `pos / type / blank_ref / control_ref / …`（见
  `senaite.core.content.worksheettemplate.ILayoutRecord`），与工作表布局
  (`position / *_uid`) 不同。目前走通用 JSON 记录表 —— 仍然可读，但
  「类型」列不会中文化、引用 UID 不解析。本包服务的是 **Worksheet** 的审计追踪。
- **嵌套 > 3 层**退回原始 JSON 文本（`JSON_MAX_DEPTH`）。这是刻意的：
  宁可少渲染，不可丢内容。
- 审计页读的是**快照 JSON**，不是活对象。样品/分析项被删掉之后，UID 解析
  不出来，那一格只能显示裸 UID。
- 字面 JSON 串形态的**普通文本字段**（例如备注里正好写了一个合法 JSON 数组）
  会被解析后渲染。内容一字不差，只是换了排布。

---

## 8. 开发规则符合性自查

- [x] `browser:page` 用 `configure.zcml` + 顶部 `<include package="senaite.core.permissions" />` 钉住注册顺序（R1）
- [x] 同名视图覆盖通过 **browser layer 继承**（`IAuditTrailLayer(ISenaiteCore, IBikaLIMS)`）实现，无同名 ZCML 冲突（R5 精神）
- [x] 无 `overrides.zcml`，因此不需要 `-overrides` slug（R2 不触发）
- [x] 未改动 `profiles/**` —— 已安装站点无需重跑 profile（R3 不触发）
- [x] `registerProfile` 声明的目录都存在且含 `metadata.xml`；提供 `profiles/uninstall/`（R4）
- [x] 部署说明区分了「重启」与「重启 + 硬刷新」（R8）
- [x] 每项功能都给出可观测验证判据（R9）
- [x] `formatter.py` 不 import Plone / SENAITE，有测试守这条边界
- [x] 未新增 `actions.xml` / `controlpanel.xml` 条目（R9b 不适用）
- [x] 未注册 configlet（R11 不适用）；无引用控件（R12 不适用）
- [x] 无订阅者 / 适配器注入外来接口（R14 不适用）
- [x] `python3 lint_addon.py --addon maitux.audittrail` → 0 ERROR / 0 WARN
