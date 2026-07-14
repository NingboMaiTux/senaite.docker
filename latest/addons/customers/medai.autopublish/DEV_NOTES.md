# medai.autopublish 开发笔记

## 关键经验：读取 Plone Behavior 字段的正确方式

### 问题

在 `auto_publish.py` 订阅者中，读取 SampleType 上的 `auto_publish` behavior 字段时，使用：

```python
auto_publish = getattr(sample_type, "getAutoPublish", lambda: None)()
```

永远返回 `None`，导致自动发布逻辑从不触发。

### 根因

`IAutoPublishBehavior` 是通过 `plone.behavior` + `IFormFieldProvider` 注册的 behavior schema。这种方式的字段**不会**生成 `get<FieldName>()` 访问器方法（那是 Archetypes 的做法），而是通过 **behavior adapter 接口**访问。

### 正确做法

```python
from medai.autopublish.behaviors.auto_publish import IAutoPublishBehavior

behavior = IAutoPublishBehavior(sample_type, None)
if behavior is None:
    # behavior 未绑定到此类型
    return

auto_publish = behavior.auto_publish  # 直接属性访问
if auto_publish == "enabled":
    # 执行自动发布逻辑
```

### 总结

| 方式 | 适用场景 | 本例 |
|------|----------|------|
| `obj.getFieldName()` | Archetypes schema 字段 | 无效 |
| `getattr(obj, "field_name", default)` | Dexterity 直接属性 | 不可靠 |
| `IBehaviorInterface(obj, None).field_name` | plone.behavior | **正确** |

### auto_publish 工作流触发点

两个层级的 Verify：
1. **第一层级 - 分析 Verify**：审核员逐个审核分析结果（核心流程，不干预）
2. **第二层级 - 样品 Verify**：分析全部审核后，在 "Sample to Approve" 点击 Verify → 如果 SampleType 的 `auto_publish=enabled`，直接跳到 `published`

实现方式：订阅 `IAnalysisRequest + IAfterTransitionEvent`，捕获 `verify` transition，通过 `changeWorkflowState` 直接设 `published`（绕过 guard）。

### 参考模式

- **跳过采样**：`SamplingWorkflowEnabled` 设定 → `guard_no_sampling_workflow` → 跳过采样状态
- **自动接收**：`AutoreceiveSamples` 设定 → `after_no_sampling_workflow` → 自动 `receive`
- **自动发布**（本 addon）：SampleType `auto_publish` 字段 → `after_verify` 订阅者 → 直接 `published`
