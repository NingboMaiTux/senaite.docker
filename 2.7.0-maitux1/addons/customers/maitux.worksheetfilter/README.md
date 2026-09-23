# maitux.worksheetfilter

让「Create worksheet」弹窗里的 **Worksheet Template 真正限定**进入 WorkSheet 的分析项。

> SENAITE 2.x / Plone 5.2 / Python 2.7 环境专用（遵循 `addons/customers/SENAITE-Addon开发规则.md`）。
> 本文档同时提供中文与英文说明。

**版本：** 1.0.0
**兼容：** SENAITE 2.x（实测 2.7.0 / Plone 5.2.15 / Python 2.7）

---

## 1. 问题 / The problem

**现象**：样品列表 → 勾选样品 → Create worksheet → 选了模板，结果样品下**所有**未分配
测试都进了 WorkSheet，模板没有起到限定作用。

**根因**（已在 8086 实例源码核实，非推测）：

`senaite/core/api/worksheet.py` 的 `create_worksheet()` 里，`ws.addAnalysis(an)` 对
`get_analyses()` 返回的**每一条**分析无条件执行，且发生在 `applyWorksheetTemplate()`
**之前**：

```python
for analysis in analyses:
    an = api.get_object(analysis)
    ws_uid = an.getWorksheetUID()
    if not all([ws_uid, api.is_uid(ws_uid)]):
        unassigned_analyses.append(an)
    ws.addAnalysis(an)          # ← 无条件全部加入，不看模板
if template is not None:
    ws.applyWorksheetTemplate(template, analyses=unassigned_analyses)
```

等 `_apply_worksheet_template_routine_analyses()` 跑到「按 `service_uids` 过滤」那一步时
（`content/worksheet.py:1053-1062`），这些分析**早已被上面的循环加进 WS、
`getWorksheetUID()` 已非空**，于是：

```python
if analysis.getWorksheetUID():
    continue        # ← 全部命中，整段过滤从未真正生效
```

**结论：没有第二道防线。** `get_analyses()`（`senaite/core/browser/modals/sample.py:76`）
是**唯一**的把关点。模板目前只影响 duplicate/blank/reference 生成和 instrument/method
赋值，对「进哪些常规分析」完全不起作用。

**实测证据**（Care 站点，改动前）：

| WorkSheet | 模板 | 模板 services | 实际装入 | 样品总 analyses |
|---|---|---|---|---|
| WS-011 | 原料药01 | 22 | 28 | 28 |
| WS-012 | 中间精密度 | 6 | 27 | 28 |
| WS-013 | 中间精密度 | 6 | **33** | 33 |

装入数 ≈ 样品全部 analyses 数，**模板选哪个都没影响**。

---

## 2. 覆盖点 / What this addon overrides

只覆盖一个视图：`create_worksheet_modal`（`overrides.zcml`，同名覆盖
`senaite.core.browser.modals.sample.CreateWorksheetModal`）。

| 方法 | 改动 |
|---|---|
| `get_analyses()` | 在原生 categories 过滤之上叠加模板过滤（取交集）；并排除**已属于其它 WorkSheet** 的分析 |
| `handle_submit()` | 在 `create_worksheet()` **之前**拦截三种情况（见下），报错且不建 WorkSheet |
| `get_template()` / `get_template_services()` | 新增：读所选模板及其声明的 Analysis Service |
| `get_template_category_titles()` / `get_selected_category_titles()` | 新增：为错误提示提供可读的类别对比 |
| `get_template_analyses_on_samples()` | 新增：区分「类别不重叠」与「已全部被占用」 |
| `is_assigned()` | 新增：与 `create_worksheet()` 相同的占用判定 |
| `get_missing_template_services()` | 新增：算出模板里哪些 AS 没进 WorkSheet |

**不改**：`senaite.core` 源码、`WorksheetTemplate` 内容类型、WorkSheet 内部的
Add Analyses 界面、`applyWorksheetTemplate()` 的排版/重复样/空白对照逻辑。
不引入新的内容类型、workflow、权限。

---

## 3. 语义表 / Semantics

弹窗有两个筛选器：**Select analysis categories**（多选）与 **Select worksheet template**
（单选）。本包定义它们的组合语义：

| categories | template | 进入 WorkSheet 的分析 | 与原生对比 |
|---|---|---|---|
| 不选 | 不选 | 样品上**全部未分配**分析（每个 service 取一条） | **与原生一致** |
| 选了 | 不选 | 只进所选类别的分析 | **与原生一致** |
| 不选 | 选了 | 只进**模板声明的 AS** 对应的分析 | ★ 本包修复点 |
| 选了 | 选了 | 两者的**交集** | ★ 本包修复点 |

> **为什么是交集而不是互斥**：用户最初的直觉是「两者应该互斥」，但实测发现弹窗的
> 模板下拉**没有 `onchange` / ajax / 重载**（选模板不触发服务端请求），互斥在服务端
> 渲染路径上无法表达。交集是更保守的选择：两个筛选器都生效，用户选得越细、进得越少，
> 不会出现「选了 A 却进了 B」的意外。

### 三种拦截（不建 WorkSheet）

| 情况 | 提示级别 | 文案要点 |
|---|---|---|
| 模板已选，但模板**不声明任何 AS** | error | 该模板无法用于限定，请换模板或改用类别 |
| 模板已选，交集为空，且模板的 AS **全部已被占用** | error | 全部已分配给其它 WorkSheet，请先释放 |
| 模板已选，交集为空（类别不重叠 / AS 不在样品上） | error | 给出「模板涉及类别 vs 你选的类别」对比 |

### 一种提示（建 WorkSheet，但部分缺失）

| 情况 | 提示级别 | 文案要点 |
|---|---|---|
| 模板声明 N 个 AS，样品上只有 M 个（M < N） | warning | 列出缺失的 AS 中文标题 + 实际装入数 |

> **为什么部分缺失要提示**：静默的部分成功是最难排查的 —— 用户以为模板生效了，
> 实际少了几个。**本包要解决的正是「系统静默做了我没预期的事」**，这里不能自己
> 再制造一个。

---

## 4. 安装 / Install

本包在 `customers` 层，**bind-mount**，不需要重建镜像：

```bash
docker restart maituxlimslatest
```

重启后还需**在 SENAITE 后台安装 profile**（★ 四个站点各自独立）：

```
/<site>/prefs_install_products_form  →  找到 maitux.worksheetfilter  →  Install
```

> 本环境**不会**在建站时自动装 addon profile（`buildout.cfg` 的普通赋值会丢掉
> `[plonesite] profiles` 里追加的条目，实测 annotate 确认）。任何包都一样，
> 一律要在后台手工装。

**验证已生效**：

```bash
# 1. profile 已装（页面里能搜到包名）
curl -u admin:<password> http://localhost:8086/<site>/prefs_install_products_form

# 2. 覆盖已生效（弹窗端点 200）
curl -u admin:<password> "http://localhost:8086/<site>/samples/create_worksheet_modal?uids=<sample-uid>"
```

---

## 5. 卸载 / Uninstall

```
/<site>/prefs_install_products_form  →  maitux.worksheetfilter  →  Uninstall
```

卸载后 `create_worksheet_modal` 回落到 `senaite.core` 的原生实现，
**弹窗行为立即恢复为改动前**（模板不再限定范围）。

本包**无外部状态**：不写 ZODB 之外的东西、不建内容类型、不改 workflow、
不注册权限。卸载是干净的，不需要额外的清理步骤。

---

## 6. 验证方式 / How it was verified

三站点（`MaiLIMS` / `InnoCare` / `Care`）回归，判据与证据见
`Docs/worksheet-create-filter-Backlog.md` 的 S6 段。摘要：

| 判据 | 结果 |
|---|---|
| `verify_addon.py` → `package_deploy_state` | `deployed` |
| `C5_STARTUP_CLEAN` | PASS |
| 三站点 `/samples` | 均 200 |
| 选模板建 WS，装入数 = 模板 services ∩ 样品未分配 services | Care 5/5、MaiLIMS 2/2、InnoCare 0/0（空交集拦截） |
| 不选模板，原生行为回归 | Care 20/20、MaiLIMS 2/2、InnoCare 6/6 |

**手工复现**（最快的一条）：

1. 找一个**未分配** WorkSheet 的样品，记下它有几个 distinct Analysis Service
2. 样品列表勾选它 → Create worksheet → 选一个模板 → Create Worksheet
3. 新 WorkSheet 里的分析数应 = 「模板 services」∩「样品未分配 services」，
   **而不是**样品的全部分析数

---

## 7. 已知限制 / Known limitations

- **弹窗的类别下拉不会随模板收窄。** 原生弹窗的模板下拉没有 `onchange` / ajax，
  选模板不触发服务端重载，所以「选了模板后把类别下拉收窄到模板涉及的类别」在
  服务端渲染路径上做不到。诉求改由 `handle_submit()` 的可读错误提示满足
  （见 §3 的第三种拦截）。
- **一个 service 只进一条分析。** 原生行为如此：样品可携带同一 service 的多条分析
  （重复样），弹窗每个 service 只取一条。本包沿用该行为，未改动。
- **`C6_SITE_ENABLED` 无法自动核验。** `portal_quickinstaller` 在 Plone 5 已废弃，
  `verify_addon.py` 的该项恒为 `unknown`。改用 §4 的两条直接证据替代。
