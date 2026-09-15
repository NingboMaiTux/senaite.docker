# INNOCARE.labid

给 **Laboratory**（Setup → Laboratory Information，界面上即 "SENAITE Test Lab"）
增加一个 **Lab ID** 字段，供样品编号（AR ID）取前缀使用。

本包只负责"字段"，不负责"编号取值"：取值逻辑在 `INNOCARE.arextension`
的 ID Server 适配器里（同一个适配器只能有一个，见下）。

## 功能职责

- **Lab ID 字段**（`src/INNOCARE/labid/behaviors.py`）：`Laboratory` 上的
  `lab_id` 文本字段，标题 `Lab ID`。
- **动态挂载**（`src/INNOCARE/labid/assignable.py`）：`Laboratory` 是
  Dexterity 类型且 FTI 在 `senaite.core` 里（不能改），因此用
  `plone.behavior` + 针对 `senaite.core.interfaces.ILaboratory` 的
  `IBehaviorAssignable` 把字段挂上去 —— 与 `senaite.core` 自己给 Dexterity
  内容追加 labels 字段是同一套机制。

## 与 INNOCARE.arextension 的分工

| 关注点 | 所在包 |
|---|---|
| Lab ID 字段本身（UI / 存储） | 本包 |
| `labId` ID Server 变量（读 Lab ID） | `INNOCARE.arextension` |

样品编号模板（Setup → ID Formatting，AnalysisRequest 行）切换为：

```
{labId}{sampleType}{yymmdd}{seq:03d}
```

> 为什么变量不放在本包：`IIdServerVariables` 对 `IAnalysisRequest` 的**无名
> 适配器全链路只能有一个**，再注册一个会 `ConfigurationConflictError`
> 导致 Zope 起不来。`deptCode`（原部门简码）保持不变，用哪个变量由上面的
> 模板决定 —— 切回 `{deptCode}...` 即回退旧编号规则。

## 依赖

- `senaite.core` / `plone.behavior` / `plone.dexterity` / `plone.supermodel`

## 安装注册（buildout）

`custom-addon.cfg` 由 `/gen-custom-addon.sh` 在容器启动时按
`/opt/addons/customers` 的实际内容自动生成，无需手工维护；本包只要放在
`addons/customers/` 一级目录下并带 `setup.py` 即可被收录。

之后在站点后台 **Add-ons → INNOCARE.labid → Install** 安装（客户 add-on 的
profile 一律在后台手工安装，不写进 `[plonesite] profiles`）。

## 生效方式

| 改动 | 生效方式 |
|---|---|
| `.py` / `.zcml` | 重启容器 |
| `profiles/*.xml` | 重启容器 + **重跑 profile**（Uninstall → Install） |

## 验证判据（可观测）

1. 未装本 add-on 的站点：打开 Laboratory 编辑页（`<site>/bika_setup/laboratory/edit`），
   **看不到** `Lab ID` 输入框（layer 门控生效）。
2. 安装后：同一页面**能看到** `Lab ID` 输入框；填入 `LAB-001` 保存后，
   `lab_id` 值落在 Laboratory 对象上（ZMI → `bika_setup/laboratory` 可见该属性）。
3. 把 ID Formatting 的 AR 行切成 `{labId}{sampleType}{yymmdd}{seq:03d}` 后
   新建样品，编号应以 `LAB-001` 开头；未填 Lab ID 时回退为部门简码
   （见 `INNOCARE.arextension/idserver.py`），并在日志出现一条 warning。

## 卸载

后台 **Add-ons → INNOCARE.labid → Uninstall**：移除本包的 browser layer，
`Lab ID` 字段随即不再出现。已填写的值以属性形式留在 Laboratory 对象上，
不删除（重新装回后原样恢复）。
