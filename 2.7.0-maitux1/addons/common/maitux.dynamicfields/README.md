# maitux.dynamicfields

SENAITE 动态字段管理：管理员在后台配置页上给对象增删自定义字段，
**不写代码、不重建镜像、不重启容器**，同时支持 Archetypes 与 Dexterity。

> SENAITE 2.7.0 / Plone 5.2 / Python 2.7。遵循 `addons/customers/SENAITE-Addon开发规则.md`。
> 需求文档见仓库根目录 `MaiLIMS_动态字段管理addon_需求文档_20260920.md`，
> 界面设计见同名设计画布。

---

## 1. 解决什么问题

在此之前每次客户提「加几个字段」，都要新开一个 add-on（`INNOCARE.arextension`
加样品字段、`INNOCARE.labid` 加实验室字段、`maitux.worksheetfields` 加工作表
字段……），每个都要重复一遍：判断 AT 还是 DX、写 extender 或 behavior、写
profile、写 ZCML、写四份 locale 目录、改配置、重建镜像、重启容器、后台装 profile。

**加一个字段的成本 ≈ 开一个新包的成本。** 本包把这一层抽出来做一次。

---

## 2. 最重要的前提：随镜像发布，站点侧不安装

这是本包与仓库内所有既有 add-on **最大的不同**，它决定了整个架构。

实测结论（已记录在 `common-addons.cfg` 注释里）：`[plonesite] profiles` 那段是
**死代码**——`buildout.cfg` 在 `extends` 之后用普通赋值重新定义了 `profiles =`，
于是那里写的 profile 一条都进不去。**新建站点不会自动装任何 add-on 的 profile。**

也就是说本包**拿不到 GenericSetup profile 这个执行时机**，凡是靠 profile 才生效
的东西全部不可用：

| 常规做法 | 本包 | 替代方案 |
|---|---|---|
| `browserlayer.xml` | ✗ | 不用浏览器层；本包不覆盖任何原生视图 |
| `registry.xml` | ✗ | 配置存 portal annotation，惰性初始化（`storage.py`） |
| `controlpanel.xml` / `actions.xml` | ✗ | Setup 页入口用 viewlet（`browser/viewlet.py`） |
| `catalog.xml` | ✗ | 勾选时由代码运行时建索引（`indexing.py`） |
| `setuphandlers` 调 `enable_behavior` | ✗ | `IBehaviorAssignable` 适配器，不写 FTI（`assignable.py`） |
| `profiles/uninstall/` | ✗ | 回滚方式见 §7 |

本包**没有 `profiles/` 目录，也不注册任何 profile**——这是刻意的，不是遗漏。

---

## 3. 两套机制怎么统一

一份配置存储，两条生成路径，**走哪条由运行时查 FTI 的 `meta_type` 决定**：

| meta_type | 机制 | 生成路径 |
|---|---|---|
| `Dexterity FTI` | DX | `dxschema.py` 动态生成 behavior schema + `assignable.py` 挂载 |
| `Factory-based Type Information with dynamic views` | AT | `atextender.py` 动态 `ISchemaExtender` |

### 为什么 DX 侧能不写 FTI

`getAdditionalSchemata()` 拿到 context 时走的是
`IBehaviorAssignable(context).enumerateBehaviors()`，**每次都调、没有缓存**，
而 `BehaviorRegistration` 是我们自己构造的对象，它的 `interface` 可以是任何
运行时生成的 schema。仓库里 `INNOCARE.labid/assignable.py` 就是这个套路，
只是它的 schema 是静态的。

### 缓存

两边**都没有跨请求的持久缓存**：

- AT：schemaextender 的缓存挂在 request 上（`__archetypes_schemaextender_cache`）
- DX：`getAdditionalSchemata` 每次都调 assignable

本包另外按 `(portal_type, 配置版本号)` 缓存生成结果。改一次配置 `rev` 加一，
缓存自然失效——**配置改完下一个请求就生效，不需要重启、也不需要清缓存**。

### 配置记录是「机制中立」的

记录里**不写**「这是 AT 字段」还是「DX 字段」。理由：上游每出一个版本 AT 那批
就短一截（2.7 里 SampleType / SamplePoint / Supplier / Contact / Worksheet 刚迁完，
AnalysisRequest / Client / Instrument / AnalysisService 迟早也会迁）。机制中立的话，
上游迁移后只要改本包的分支逻辑，**客户已配好的字段定义一条都不用动**。

---

## 4. 多语言标签：本包自闭环，不依赖 senaite.core

**标准 gettext 在这里走不通**：字段是运行时通过网页建出来的，不可能预先准备
`.po`；运行时写 `.po`/`.mo` 也没用——已注册的 catalog 不重新加载，按 R8 得重启。

做法：翻译域在 Zope 里就是一个实现了 `translate()` 的 utility，接口并没规定它
必须查 `.mo`。本包注册一个自己的域（`maitux.dynamicfields.labels`，见 `i18n.py`），
它的 `translate()` 转而查配置库。回报是**整条渲染链自动就对了**——z3c.form 标签、
AT widget label、模板 `i18n:translate` 全都不用改。

两条硬约束（违反了会在生产上翻车）：

1. **不能在构建 schema 时把当前语言烤进 `title`。** schema 是缓存的，烤进去的
   后果是"第一个发起请求的人的语言变成之后所有人看到的语言"，**单人测试
   百分之百测不出来**。字段 title 一律给 `Message`（延迟求值）。
2. **msgid 和 `default` 一律 ASCII，中文只活在配置库里。** 漏翻的地方至少显示
   正常英文；更要紧的是 Py2 下非 ASCII 的 msgid 撞上 `str()` 会直接抛异常。

语言回落链：精确 → 收窄到基础语言（`zh-cn`→`zh`）→ **放宽到同族变体**
（`zh`→`zh-cn`）→ 站点默认 → 任意非空。第三步是实测补的：只做收窄的话，
浏览器发裸 `zh`、库里存的是 `zh-cn`，中文站点上会看到英文标签。

> 配置页**自身**的界面文案仍走常规 `.po`/`.mo`（`locales/`），跟上面两回事。

### 界面文案的规矩

**源码里一律写英文 msgid + 英文 default，中文只在 `.po` 里。** 这样切到英文
站点就是英文，切回中文就是中文。三类例外，都是刻意的：

| 例外 | 为什么 |
|---|---|
| `config.TYPE_TITLES` / `TYPE_GROUPS` | 双语对照表，每项是 `(中文, 英文)` 元组，`get_type_title(pt, language)` 按语言取。它们是**每请求**调的视图路径，按当前语言取值安全 |
| `POSITION_SLOTS` 的 `编/查/列/报` | 单字徽章，与 `E/V/L/R` 配对，同样按语言取 |
| 语言下拉里的「中文」 | 语言自己的名字不该被翻译 |

`smoke_test.py` 第 8 节有个 **lint**：扫全部 `.py`，除上面三类白名单外，
出现任何中文字符串字面量就报错。防止以后又退化回写死中文。

---

## 5. 设计红线

**Choice 的存储值必须是 ASCII key，中文只能当显示标签。**
`validation.py` 在写入路径上强制（不是只靠界面控制显隐——构造请求能绕过模板）。
一旦把中文存进对象，这份数据就永远翻译不了，索引、导出、统计也全部锁死在
中文上，事后再改要迁数据。

---

## 6. 部署

1. 目录已在 `2.7.0-maitux1/addons/common/maitux.dynamicfields`；
2. `common-addons.cfg` 的 `develop +=` 与 `eggs +=` 各有一行（已加）；
3. 重建镜像。

> 当前 Dockerfile 是 PR #23 之后的分层版本（`Dockerfile:182` 有「第二段 buildout」，
> `common-addons.cfg` 在 `Dockerfile:186` 才 COPY 进来），所以**改这个 cfg 只打到
> 最后几层，几分钟**，不是全量重建。

4. 容器起来后，管理员访问 `<站点>/@@dynamic-fields`，或从 Setup 页上的入口进。
   **站点后台不需要安装任何东西。**

---

## 7. 回滚

本包不提供卸载 profile（R4b 的豁免情形）：

1. **先在配置页上逐个关闭索引开关**（否则目录里会留下无人维护的死索引）；
2. 从 `common-addons.cfg` 摘掉两行 → 重建镜像 → 重启；
3. 已写入对象的字段值作为孤儿属性保留在数据库里，不影响站点运行。

---

## 8. 验证判据（R9，必须可观测）

先跑自动化的那部分：

```bash
docker run --rm \
  -v "<仓库>/2.7.0-maitux1/addons/common/maitux.dynamicfields:/opt/addons/common/maitux.dynamicfields:ro" \
  -e PYTHONIOENCODING=utf-8 \
  --entrypoint /home/senaite/senaitelims/bin/zopepy \
  <镜像> /opt/addons/common/maitux.dynamicfields/tools/smoke_test.py
```

覆盖 107 项：存储与校验、动态 schema 生成、**同一 schema 在不同语言请求下给出
不同标签**、behavior 属性转发、**九种字段类型在 AT 和 DX 两条路上都能构造**
（含标签必须是延迟求值的 Message、AT 侧必须带 `add` 键、多值形态）、
**视图层吃 bytes 中文不崩**、脏配置容错、
**中英切换**（类型名按语言走、.po 里译文齐全、源码里不许再写死中文界面文案的 lint）。

> 最后一项是踩过坑补的：Py2 下 Zope 的 request 给回来的表单值常常是 utf-8
> **bytes** 而不是 unicode，对它调 `.encode("utf-8")` 会先用 ASCII 隐式解码，
> 搜索框一输中文就 `UnicodeDecodeError: 'ascii' codec can't decode byte 0xe6`。
> 第 7 节就是这条的回归用例，且做过反向验证（把 bug 注回去，测试确实变红）。

再跑 ZCML 加载检查（把 `smoke_test.py` 换成 `zcml_check.py`）：验证 configure.zcml
真的能加载、翻译域与两个适配器都注册上了。**ZCML 错误是启动期报错、站点直接
起不来的那一类**，等重建完镜像再发现一轮就是几十分钟——这个脚本实际抓到过
`Undefined permission ID: cmf.ManagePortal`（少了 CMFCore permissions 的 include）。

第三个脚本 `site_check.py` 需要**站点起着**，走 `bin/instance run`：

```bash
docker exec <容器名> /home/senaite/senaitelims/bin/instance run   /opt/addons/common/maitux.dynamicfields/tools/site_check.py lims2
```

它对白名单里 36 个类型逐个走一遍配置页实际用的代码路径（机制判定、找实例、
三段内省、工作流状态、九种字段构造、DX 的 assignable 有没有被旁路），报告
哪个类型会炸。**只读，可以在生产上跑。** 手工点 36 个类型要几十分钟，
而真正的风险不在「加字段」本身（字段构造跟 portal_type 无关），在**内省**
——某个类型的 schema 读崩了，那一页就 500。

手工部分：

| 检查点 | 预期信号 |
|---|---|
| 新镜像启动后**不做任何安装动作**，访问 `@@dynamic-fields` | 页面正常打开 |
| 非管理员访问 | 403 |
| 类型列表 | 白名单类型各带 AT / DX 标注；`Analysis`、文件夹类型、`BikaSetup` / `ARTemplate` / `ARReport` 不出现 |
| 展开 AnalysisRequest（AT） | 列出原生字段 + `INNOCARE.arextension` 已加字段，**均无删除按钮** |
| 展开 Worksheet（DX） | 列出主 schema + behavior 字段（含 `maitux.worksheetfields` 的 `instruments` / `stock_batches`） |
| 给 Client（AT）加一个文本字段 | 保存后**无需重启**；客户编辑页出现该字段，中文站点显示中文标签 |
| 给 SampleType（DX）加一个 Choice 字段 | 同上；**存储值是 key 不是标签**（ZMI 核验） |
| 只改标签文案后保存 | 实时生效 |
| 删除自建字段 | 字段消失；旧值保留；索引同步摘除 |
| 字段名填 `title` 或已存在的名字 | 保存被拒绝并给出原因 |
| **脏配置容错**：塞一条引用不存在 portal_type 的记录后重启 | **站点正常启动**；总览页红色告警；日志有 error |
| 导出 JSON → 清空 → 导入 | 定义与多语言文案完整恢复 |
| **两个浏览器分别用中 / 英登录**，同时打开同一编辑页 | 各自看到各自语言的标签 |

> 最后一条**单人测试测不出来**，必须双会话验证。`tools/smoke_test.py` 已经
> 自动覆盖了它的核心（同一 schema 对两个不同语言的 request 给出不同结果）。

---

## 9. 已知限制

1. **加了字段在哪儿看得见。**（此条原先写错过，已按源码更正）

   **会自动出现的：**
   - DX 的标准 `@@edit` / `@@add` 表单
   - AT 的 `base_edit` / `base_view`
   - **样品新建页 `ar_add2`** —— 它**是读 AR schema 的**，且明确包含 extender
     字段（`add2.py:290` 注释原文 "Return the AR schema fields (including
     extendend fields)"）。前提是 widget 的 `visible` 字典里有 `"add"` 键，
     否则 `isVisible(..., mode="add", default='invisible')` 会把它判为不可见
     ——`atfields._visibility()` 已按 senaite 自己的写法给了 `{"add": "edit"}`。
   - 样品 / 工作表顶部的 header_table（同理给了 `"header_table": "visible"`，
     实际效果待站点上验证）

   **仍然不会自动出现的：**
   - 全部列表页：`senaite.app.listing` 的列来自 `self.columns` 字典，与 schema
     无关，需要二期做一个读同一份配置的通用挂载点
   - 工作表结果录入页页头：手写模板
2. **别的 add-on 可能把本包旁路掉。** `INNOCARE.labid` 为 `ILaboratory` 注册了
   自己的 `IBehaviorAssignable`，比本包的 `IDexterityContent` 更具体，zope 会挑它
   ——本包在 Laboratory 上不生效。配置页用 `assignable.is_assignable_active()`
   实测并给告警，不让它静默丢字段。
3. 字段名与字段类型创建后不可改；改类型只能删除重建，数据不迁移。
4. v1 不做 DataGrid、计算字段、文件 / 图片、富文本；多行文本的索引退回
   `FieldIndex`（`ZCTextIndex` 需要 lexicon）。
5. `show_report`（在检验报告中显示）为二期，界面置灰、代码里钉死 `False`。

---

## 10. 目录结构

```
maitux.dynamicfields/
├── setup.py / MANIFEST.in / README.md
├── tools/
│   ├── compile_mo.py       # .po -> .mo（纯标准库；顺带同步 zh / zh-cn 别名）
│   ├── smoke_test.py       # 冒烟测试（74 项），镜像的 zopepy 里跑，不需要站点
│   ├── zcml_check.py       # ZCML 注册检查，能查出跨包注册冲突
│   └── site_check.py       # **在运行中的站点上**逐个验证 36 个类型的内省不崩
└── src/maitux/dynamicfields/
    ├── configure.zcml      # 翻译域 utility + 两个适配器；**不注册 profile**
    ├── config.py           # 白名单、字段类型、保留名、上限
    ├── storage.py          # annotation 存储 + revision + JSON 导入导出
    ├── validation.py       # 写入路径上的校验
    ├── i18n.py             # 自注册 ITranslationDomain
    ├── dxfields.py         # 记录 -> zope.schema 字段
    ├── dxschema.py         # 动态 interface 构建 + 缓存 + behavior 工厂
    ├── assignable.py       # IBehaviorAssignable（不写 FTI）
    ├── atfields.py         # 记录 -> Archetypes 字段
    ├── atextender.py       # 动态 ISchemaExtender
    ├── introspect.py       # 机制判定 + 类型清单 + 字段内省（AT/DX 归一）
    ├── indexing.py         # 运行时建 / 删索引与 metadata
    ├── browser/            # 配置页 + Setup 入口 viewlet
    └── locales/            # 配置页界面文案（zh_CN / zh / zh-cn）
```

---

## 11. 开发规则符合性自查

- [x] R1：ZCML 不引用 senaite.core 自定义权限（一律 `cmf.ManagePortal`），
      从根上绕开 autoinclude 的顺序问题
- [x] R2/R5：无 `overrides.zcml`，不覆盖任何同名组件
- [x] R4：不注册 profile，因此无「目录不存在」风险；R4b 豁免卸载，回滚见 §7
- [x] R5c：分发名与目录名一致，靠 autoinclude 入口点
- [x] R8：部署说明区分重建镜像与刷新
- [x] R9：验证判据可观测，且关键几条已自动化
- [x] R12：ReferenceWidget 传 `query=` 时同时传 `base_query={}`
- [x] R13：异常处理不重复失败调用；Py2 转字符串一律走安全函数
- [x] R16：布尔控件不传 `render_own_label`
- [x] R17：无硬编码凭据
- [ ] R14：注入外来 UI 未做 layer 门控——本包**不存在「未安装」状态**
      （随镜像发布、无 profile），门控条件换成「上下文是 Setup 页 + 有 ManagePortal」
