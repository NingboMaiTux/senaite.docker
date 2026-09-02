# Reactivate 安装使用手册

## 1. 文档说明

本文档用于指导 `maitux.workflow` 插件中“重新激活（Reactivate）”功能的安装、升级、使用与排障。

适用范围：

- SENAITE 2.x
- Plone / Zope 环境
- Python 2.7

本文档对应的功能目标：

- 为样品 `AnalysisRequest` 增加 `Reactivate`
- 为分析项 `Analysis` 增加 `Reactivate`
- 联动处理工作表 `Worksheet`
- 审计追踪 `@@auditlog` 中可查看“重新激活原因”
- 失败时整体回滚，避免半成功状态

## 2. 功能概述

安装完成后，系统支持以下能力：

- **已发布**或**已拒收**的样品允许重新激活
- **已审核**、**已发布**或**已拒绝**的测试允许重新激活
- 已挂工作表的分析项会根据工作表状态执行不同回退策略
- 重新激活时要求填写原因
- 原因会进入原生审计追踪的 `Changes` 列
- 原有结果值保留，不会因为重新激活而被清空

> ★ **完整的状态清单与连带后果见 §8.2**，那里逐行标注了哪些是实测、
> 哪些只有代码依据。**操作前请读那一节** —— 本节只是概览。
>
> 特别注意两处与早期版本**不同**的地方：
>
> - 样品的 `verified`（已审核）**不再**提供 Reactivate —— 业务规则是开工就走完流程
> - 测试的 `to_be_verified`（待审核）**不再**提供 Reactivate ——
>   该状态本来就有原生的「撤回」和「重测」

## 3. 前置条件

部署前请先确认：

- 目标环境已正确加载 `maitux.workflow`
- 项目运行环境为 Python 2.7
- buildout 已包含 `maitux.workflow` 的 `develop`、`eggs` 和 `zcml` 配置
- 当前站点可正常安装或重装 add-on
- 当前操作者具备插件安装与站点管理权限

## 4. 代码接入

如果是新环境首次接入，请先确认以下配置已加入项目 buildout。

### 4.1 buildout 配置

在主 buildout 配置中确认以下内容存在：

```ini
[buildout]
develop +=
    src/maitux.workflow

eggs +=
    maitux.workflow
```

在实例配置中确认已加载 ZCML：

```ini
[instance]
zcml +=
    maitux.workflow
```

如果项目有测试环境配置，也建议同步加上：

```ini
[test]
eggs =
    ${buildout:package-name} [test]
    ${buildout:eggs}
```

## 5. 安装步骤

### 5.1 覆盖代码

将 `maitux.workflow` 最新代码覆盖到目标项目：

- `src/maitux.workflow/src/maitux/workflow/browser/workflow.py`
- `src/maitux.workflow/src/maitux/workflow/browser/reactivate.pt`
- `src/maitux.workflow/src/maitux/workflow/services/reactivate.py`
- `src/maitux.workflow/src/maitux/workflow/setuphandlers.py`

如果项目目录中仍有历史调试文件或旧测试文件，可一并清理。

### 5.2 重新执行 buildout

在项目根目录执行：

```bash
bin/buildout
```

### 5.3 重启实例

根据现场部署方式重启 Zope / instance。

### 5.4 安装或重装插件

进入站点 Add-ons 页面：

- 新站点：安装 `maitux.workflow`
- 已安装站点：如已同步代码但 workflow 未刷新，建议重装或执行补丁逻辑

安装时会自动执行：

- 清理历史 `workflowroot` 侧栏入口
- 补丁更新样品 workflow
- 补丁更新分析项 workflow

## 6. 升级注意事项

如果目标站点之前已经装过旧版本，请特别注意：

- 代码更新后，数据库中的 workflow 配置不一定自动刷新
- 如果页面仍提示 `No workflow provides the 'xxx' action.`，通常不是代码没同步，而是 workflow 补丁未真正写入站点数据库

此时建议手工执行 workflow 补丁。

## 7. 手工刷新 workflow 补丁

进入 debug：

```bash
bin/instance debug
```

执行：

```python
app = makerequest(app)
portal = app['lims']
setSite(portal)

from maitux.workflow import setuphandlers
setuphandlers.setup_workflows()

import transaction
transaction.commit()
```

执行完成后退出 debug，并重启实例。

## 8. 使用说明

### 8.1 入口位置

重新激活按钮会出现在以下位置：

- 样品列表页 workflow 按钮区域
- 样品对象页 workflow 操作区域

### 8.2 允许状态与状态变化（★ 操作前请读完本节）

本节的目的是**避免操作后的认知偏差** —— 点一次 Reactivate 到底动了哪些对象、
哪些**没有**动，必须事先清楚。

每一行都标了**证据来源**：

- **实测** = 在本机 Care 站点上真的走过一遍并核对了结果
- **仅代码** = 依据 SENAITE 源码判断，但本环境**没有对应数据可验**

> ⚠️ **不要把"仅代码"当成"已验证"。** 标成"仅代码"的那几行，
> 是本环境造不出对应数据（例如 `verified` / `published` 样品需要走完
> 电子签名复核流程才能产生）。它们的依据是可靠的源码，但没有观测记录。

#### 8.2.1 样品（Sample）

| 样品当前状态 | 有 Reactivate？ | 点了之后 | 连带后果 | 证据 |
|---|---|---|---|---|
| `sample_received` 及更早 | ❌ 没有 | — | 本来就可以录结果，无需激活 | 实测 |
| `to_be_verified` | ❌ **没有** | — | 业务规则：开工就要走完流程。**但激活它下面某条测试，会把样品拉回 `sample_received`** | 实测 |
| `verified` | ❌ **没有**（本次改动移除） | — | 同上：激活其下某条测试即可把样品拉回 `sample_received` | 出口实测；回退路径仅代码 |
| `published` | ✅ 有 | → `sample_received` | 级联激活其下"为出报告而定格"的测试；**被单独拒绝的测试不会回来** | 出口实测；级联仅代码 |
| `rejected`（样品拒收） | ✅ **有**（本次改动新增） | → `sample_received` | 级联激活其下所有被拒绝的测试（它们是随样品一起被拒的，不是逐条决定） | **实测** |
| `invalid`（已作废） | ❌ 没有 | — | 作废时**已自动新建重验样品**（编号带 `-R01`），请到重验件上继续 | 实测 |
| `cancelled`（已取消） | ❌ 没有 | — | 用原生**「恢复」（reinstate）**：级联恢复所有测试并回到取消前的状态 | 实测 |
| `dispatched`（已送出） | ❌ 没有 | — | 用原生**「还原」（restore）**：回到送出前的状态 | 仅代码 |

#### 8.2.2 测试（Analysis）

| 测试当前状态 | 有 Reactivate？ | 落到哪个状态 | 连带后果 | 证据 |
|---|---|---|---|---|
| `unassigned` / `assigned` / `registered` | ❌ 没有 | — | 本来就可以录结果 | 实测 |
| `to_be_verified` | ❌ **没有**（本次改动移除） | — | 该状态已有原生**「撤回」（retract）**和**「重测」（retest）**两条路，不需要第三个入口 | 实测 |
| `verified` | ✅ 有 | 在工作表上 → `assigned`；不在 → `unassigned` | 结果值**保留**；父样品回退；工作表按其状态处理（见 8.4） | **实测** |
| `published` | ✅ 有 | 同上 | 同上 | 仅代码 |
| `rejected`（被拒绝） | ✅ **有**（本次改动新增） | **必定 `unassigned`** —— 拒绝时已被移出工作表 | 清除"已拒绝"标记；恢复其附件进报告；**不动上下游测试**，只在确认页提醒 | **实测** |
| `retracted`（已撤回） | ❌ 没有 | — | 撤回时**已自动生成重测项**，请在重测项上继续 | 实测 |
| `cancelled`（已取消） | ❌ 没有 | — | 随样品一起取消的，用样品的**「恢复」** | 实测 |

#### 8.2.3 什么时候按钮会"消失"

即使状态在上表里是 ✅，**父样品处于下列状态时按钮也不会出现**：
`cancelled` / `rejected` / `invalid` / `dispatched`。

理由：整张样品已经退出正常流程，单独把某条测试拉活只会造成状态矛盾。
（`cancelled` 已实测；其余三个仅代码。）

#### 8.2.4 几条容易误解的后果

1. **激活不会清除复核历史。** 一条被激活过的测试，仍然会显示当初的复核人 ——
   那是评审历史里的记录，不是"它现在已复核"。**实测**
2. **附件恢复是不对称的。** 拒绝会把该测试的附件全部设为"不进报告"，
   激活会把它们全部设回"进报告"。如果某个附件在**被拒绝之前**就已经被人为
   关掉，激活会把它一并打开 —— 拒绝没有记录改动前的值，无从区分。**已知限制**
3. **整单激活会跳过一些测试。** 见 8.4.4。确认页会把跳过的逐条列出来。

### 8.3 操作流程

1. 打开样品列表页或样品详情页
2. 点击 `Reactivate`
3. 进入确认页
4. 填写“重新激活原因”
5. 点击确认提交

### 8.4 系统联动行为

#### 8.4.1 激活**一条测试**时

按这个顺序处理，**顺序本身有讲究**：

1. **该测试**先迁移：在工作表上 → `assigned`；不在工作表上 → `unassigned`
2. **父样品**再回退：优先走原生「回退到已接收」，该路不通时才走本插件的激活
   —— 结果都是回到 `sample_received`
3. **所属工作表**按其状态处理（见 8.4.3）

> 第 2 步必须在第 1 步之后：SENAITE 判断"样品能不能回退"的条件是
> **样品下至少有一条测试处于 `unassigned` / `assigned`**。
> 如果先动样品，那个条件还不成立，样品会**纹丝不动而且不报错**。

**父样品的回退是无条件尝试的**，不再只针对 `verified` / `published` ——
样品停在 `to_be_verified`（所有结果都已提交）时同样会被拉回 `sample_received`，
因为"全部已提交"这个前提在激活之后就不成立了。**实测**

#### 8.4.2 激活**一条测试**时，**不会**动什么

- **不动上游**：本测试依赖的其他测试，状态不变
- **不动下游**：引用本测试结果的其他测试，状态不变
- 上下游中若有仍处于拒绝状态的，**确认页会提醒**，但不阻断操作

> 这与 SENAITE 原生的拒绝行为是对称的：拒绝**只向下游**级联、不动上游；
> 所以激活也只管选中的那一条。要恢复关联项，请单独勾选它再激活（两次操作）。

#### 8.4.3 工作表

| 工作表状态 | 处理 |
|---|---|
| `open` | 不动 |
| `to_be_verified` | 走原生「回退到打开」（`rollback_to_open`） |
| `verified` | 受控同步到 `open`（该状态没有合法的原生回退路径，见踩雷记录 §5） |

激活后测试**仍然挂在原工作表上**（若原本在工作表上）。**实测**

#### 8.4.4 激活**整张样品**时，哪些测试不会跟着回来

| 测试状态 | 跟着回来？ |
|---|---|
| `verified` / `published` | ✅ 会 |
| `rejected`（被单独拒绝） | ❌ **不会** —— 报告就是按"不含它"的形态发出去的 |
| `rejected`（**样品自己**被拒绝时随之被拒的） | ✅ 会 —— 那不是逐条决定 |
| `retracted` | ❌ 不会 —— 已有重测项 |
| `cancelled` | ❌ 不会 —— 走样品的「恢复」 |

**确认页会把不会回来的逐条列出来。** 要恢复其中某一条，单独勾选它再点
Reactivate。**实测**

### 8.5 审计追踪

每次重新激活都会写入审计快照：

- `action = reactivate_audit`
- `Changes` 中可看到 `重新激活原因`

查看方式：

1. 打开目标对象
2. 进入 `@@auditlog`
3. 在 `Changes` 一列查看本次差异记录

## 9. 验收建议

建议按以下场景逐项验收。

### 9.1 正常场景

- 已发布样品重新激活成功
- 样品状态回退正确
- 分析项状态回退正确
- 工作表状态回退正确
- 原始结果值仍然保留
- 审计追踪中可看到“重新激活原因”

### 9.2 异常场景

- workflow 未刷新时，按钮存在但执行报 transition 不存在
- 任一步骤失败时，样品、分析项、工作表均不应部分提交
- 提交空对象或异常 UID 时，应提示未找到对象

### 9.3 审计场景

- `@@auditlog` 中存在本次 `Reactivate audit`
- `Changes` 中出现：
  - `重新激活原因`

## 10. 常见问题

### 10.1 页面提示 `No workflow provides the 'reactivate_assigned' action.`

原因：

- workflow 补丁没有真正写入站点数据库

处理：

- 重装插件
- 或按“手工刷新 workflow 补丁”章节执行 `setup_workflows()`

### 10.2 页面提示 `No workflow provides the 'rollback_to_open' action.`

原因：

- `verified` 工作表不支持该 transition

说明：

- 当前实现已做状态分支处理
- 请确认现场代码已更新到最新版本

### 10.3 页面提示 `未找到可重新激活的对象`

原因：

- 提交参数中的 UID 格式异常
- 或页面仍在使用旧模板

处理：

- 确认 `reactivate.pt` 已同步
- 清理缓存后重试

### 10.4 审计追踪里看不到“重新激活原因”

原因：

- 旧版本实现只把原因写进 metadata
- 或当前记录是在旧代码上线前产生

处理：

- 确认已同步最新 `reactivate.py`
- 用最新代码重新执行一次 Reactivate
- 再查看新生成的审计记录

### 10.5 样品状态变了，但分析项或工作表没有一起变

原因：

- 通常是旧代码版本未包含事务回滚保护
- 或现场 workflow 补丁不完整

处理：

- 确认已同步最新代码
- 确认 `setup_workflows()` 已执行

## 11. 发布建议

正式发布前建议：

- 清理 `.pyc` 与 `__pycache__`
- 重启实例
- 在测试环境完整走一遍验收流程
- 保留本次实施记录与审计截图

可选清理命令：

```bash
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} +
```

## 12. 相关文档

- [REACTIVATE_踩雷记录.md](file:///e:/senaite/诺诚项目/senaite.core-2.x/src/maitux.workflow/REACTIVATE_踩雷记录.md)

如后续还要做版本化交付，建议基于本文档再补一份“实施测试说明”作为正式上线附件。
