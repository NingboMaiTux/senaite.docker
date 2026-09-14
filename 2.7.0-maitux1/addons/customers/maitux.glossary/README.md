# maitux.glossary — 检查项目 keyword 中英文对照表（中间表）

SENAITE 2.x（Plone 5.2 / Python 2.7）客户 add-on。把全站 **Calculation 的
Interim Fields** 汇总成一张中间表，`zh` / `en` 两列由**人工**填写；
**每次进入列表页自动与站点对账同步**：

- **只增**：站点上出现的新组合 → 追加一行，默认**活跃**
- **不改**：已存在的组合，除状态外**字段一律不动**（哪怕站点 title 变了）；
  `zh` / `en` 是人工术语，同步**永不回填**
- **不删**：组合从站点消失 → 只把状态改成**未激活**；重新出现 → 对称恢复**活跃**

表的入口在 **SENAITE 设置菜单**里（容器放在 `portal.setup` 下，会被设置菜单自动收录）；
列表页工具栏还有 **「从站点刷新」** 按钮，可以手动立刻对账一次、并把结果直接显示在界面上。

需求、边界与决策记录见 `项目文档/keyword对照表/结构定稿.md`。

> 本包对站点行为**零改动**：不注册任何 monkey-patch；`overrides.zcml` 不存在
> （不涉及 senaite 自定义权限、不覆盖原生同名组件，规则 R1/R5/R5b 不触发）。
> 按 R11 **不注册附加产品配置入口**：容器放在 `portal.setup` 下，设置菜单
> `setupitems() = setup.objectValues() + bika_setup.objectValues()` 会**自动**收录它，
> 因此也**不再**使用 BikaSetup 的 sidebar folders 配置。
> 包外状态：**没有**（全部在 ZODB 内），因此迁移机制只需 GenericSetup 一路。

---

## 1. 数据模型

### 1.1 行的键

```
(analysis_keyword, calc_keyword)
```

- `analysis_keyword`：检查项目的 Keyword（`AnalysisService.Keyword`）
- `calc_keyword`：该检查项目所用 Calculation 的
  `InterimFields[].keyword` —— 就是 Calculation 编辑页
  `Calculation Interim Fields` 表格的 **Keyword** 列

**行的 ID 是确定性的**：`keys.make_entry_id()` = 分析关键词的 slug + 整对 key
的 md5 前 8 位。因为 keyword 的合法字符里包含 `_`（`a__b` + `c` 与 `a` + `b__c`
会拼成同一个 ID），所以必须哈希，不能纯拼接。确定性 ID 带来两件事：

- **幂等**：同一组合重复同步不会产生第二行
- **O(1) 定位**：同步查"这行在不在"直接 `_getOb`，不需要遍历、不需要自定义索引

### 1.2 字段

| 字段 | 谁维护 | 说明 |
|---|---|---|
| `analysis_keyword` / `calc_keyword` / `category` | 同步（仅首次写入） | 行键与上下文；之后不再改动 |
| `zh` / `en` | **人工** | 公式字段的中英文名。**默认为空**，由人工填写；同步不回填 |
| `sync_state` | **同步** | `active` / `inactive` —— **同步唯一会改的字段** |
| `first_seen` | 同步 | 首次收录时间 |
| `state_changed_on` | 同步 | 状态变更时间（仅创建 / 状态变化时写） |
| `last_sync_by` | 同步 | 触发者（写入是提权执行的，这是唯一可用的归因） |
| `note` | 人工 | 备注 |

列表页还有两个**只读参考列**，它们**不入库**，每轮同步从站点快照现取：

| 参考列 | 取值 | 用途 |
|---|---|---|
| `Analysis Service`（检测项目） | 该 AS 的标题 | 认人：一个 calc keyword 常被多个检测项目使用 |
| `Site Field title` | 站点上该公式字段的 `Field title` | 翻译时对照，灰色显示（**只读、仅提示，绝不回写**；`zh` 是独立术语，与它不一致是常态，故不标红） |

> 为什么不入库：存进表里就等于**每轮同步都在改已存在的行**，与"已存在的 key
> 完全不动"直接冲突。参考列随快照走，改站点配置只影响显示。

> 结构定稿里的 `last_seen` 实现成了 `state_changed_on`：每轮都刷新 `last_seen`
> 就意味着**每轮都在改所有已存在的行**，与"已存在的 key 完全不动"直接冲突，
> 而且会把整表写一遍。

---

## 2. 部署

按 `SENAITE-Addon开发规则`：

1. 把整个 `maitux.glossary/` 放到
   `docker/senaite.docker/<tag>/addons/customers/` 的**一级子目录**下
   （该目录必须含 `setup.py`，否则整个目录会被 gen-custom-addon.sh 跳过）。
   目录内不要再套一层客户目录。
2. 从其它环境同步用：

   ```powershell
   robocopy "<源>\maitux.glossary" "<目标>\maitux.glossary" /E /XF *.pyc /NFL /NDL /NJH /NJS
   ```

   **不要用 `/MIR`**（R7）：它会删掉容器编译产生的 `.pyc`。
   robocopy 退出码 0–7 均为成功，PowerShell 会判非零为失败，可用
   `if ($LASTEXITCODE -lt 8)` 判断。
3. **不要手工维护 `custom-addon.cfg`**（R5d）—— 它是运行时生成的。本包有
   `setup.py` + `configure.zcml` + autoinclude 入口点，容器重启后会被自动收录
   （日志里 `gen-custom-addon` 应能看到 `maitux.glossary`）。
4. 重启容器，然后在后台 Add-ons 页面
   （`/prefs_install_products_form`）安装 **Maitux Keyword Glossary**。
   安装后 profile 会在 **`portal.setup` 下**创建容器 `keyword_glossary`
   （即 `<site>/setup/keyword_glossary`），它会**自动**出现在设置菜单里；
   若站点根目录下存在旧版本（v1）建的容器，安装会把它**搬进 setup**
   （cut/paste，保留全部行与 UID，已填的 `zh`/`en` 不丢）。
5. **`.py` / `.zcml` 改动需要重启容器**（R8）。本包没有 `.js` / `.css`，
   所以不涉及浏览器硬刷新。

### 2.1 重新部署时的注意

- 新增 / 修改 `profiles/**` 后，已安装站点**必须重跑 profile**
  （Uninstall → Install 或 upgrade step），不能依赖代码兜底（R3）。
  本包当前 profile 只含 typeinfo / browserlayer / 两个类型定义，
  容器是在 `post_install` 里建的（幂等，含从站点根迁移）。
- 卸载**不会删除数据**：中间表是追加式台账，`setup/keyword_glossary` 容器与其行
  原样保留在 ZODB 里（没有侧边栏入口需要摘除）。要彻底清掉请手工删容器 —— 但这
  等于抹掉历史，请先确认。
- **本包不豁免卸载能力**（不属于合规类：它不承担 GMP/21 CFR Part 11 义务），
  所以按 R4b **不建 `upgrades/`** —— R4b 的"必须从第一版就建 upgrades"是
  **换来的义务**，前提是豁免掉 `profiles/uninstall/`。本包有 uninstall profile，
  "Uninstall → Install" 就是逃生口。**这不是疏漏，不要"补"一个 upgrades 进来。**

---

## 2.2 部署到**原生 buildout**（无 Docker，如 `~/nuocheng/senaite.core-2.x`）

这台测试机不是 docker 部署，而是 pyenv + buildout。步骤：

```bash
# 1) 把 addon 放到 buildout 的 src/ 下（与其它 maitux.* 同级）
#    目录形态必须是 <pkg>/src/maitux/<name>/...
cd ~/nuocheng/senaite.core-2.x

# 2) buildout.local.cfg 三处各加一行（参照其它 maitux.*）
#    [buildout] develop +=   -> src/maitux.glossary
#    [buildout] eggs +=      -> maitux.glossary
#    [instance] zcml +=      -> maitux.glossary

# 3) 跑 buildout（会生成 develop-eggs/*.egg-link + package-includes/0NN-*-configure.zcml）
pyenv activate senaite_dev
buildout -c buildout.local.cfg -N

# 4) 安装 profile（**实例必须先停**，否则 ZODB 被占用）
bin/instance stop
bin/instance run /path/to/install_glossary.py   # 内部 runAllImportStepsFromProfile
bin/instance start                              # 或按你们的习惯 bin/instance fg
```

⚠️ **两个必须知道的坑（本机实测）**：

1. **同一个 section 里不能出现两个 `eggs +=`**。`buildout.local.cfg` 里如果
   除了"带值的那一个"还有一个**空的 `eggs +=`**，ConfigParser 会保留后者，
   于是前面 13 行 addon 全部被丢弃 —— 表现是 `bin/instance` 的 sys.path 里
   只有少数几个 maitux（实例启动时报
   `ImportError: Module maitux has no global instrument_acquisition`）。
   自查：`buildout -c buildout.local.cfg -N annotate | grep -A20 '^\[buildout\]'`，
   看 `eggs=` 的计算值里有没有全部 addon。
2. **`bin/instance run` 里跑 profile 必须先 `setSite(site)`**，否则
   `plone.dexterity` 的 `ftiAdded` 订阅者取不到 `ISiteRoot`，
   typeinfo 导入抛 `ComponentLookupError`。本包 `install_glossary.py` 已处理。

---

## 3. 同步逻辑

```
进入列表页（HTML 请求） 或 点「从站点刷新」（@@glossary-sync）
  └─ run_sync(container)                      # 只读站点
       ① 遍历**只取 is_active** 的 AnalysisService / Calculation
          → site_keys = {(as_kw, calc_kw): {category, service_title, site_title}}
       ② 读中间表现有行
       ③ 新增 = site_keys - table_keys  → 追加
            zh = 空、en = 空（人工填写，**不从站点回填**）
            sync_state = active、category 取站点类别
            first_seen = state_changed_on = now、last_sync_by = 触发者
       ④ 消失 = table_keys - site_keys  → 只把 sync_state 改成 inactive
       ⑤ 已存在的 key：除 sync_state 外**完全不动**
          （站点 title/category 变了也不动，差异只进日志）
       ⑥ 写一行可 grep 的日志
```

### 3.1 为什么 `zh` 不从站点回填

`zh` 是**独立术语**，不是站点数据的镜像 —— 需求方明确要求表里"有值"的一定是
人填的，不会与站点现状混淆。所以：

- 新行 `zh` / `en` 一律**留空**，由人工填写；
- 同步**只**动 `sync_state` / `state_changed_on` / `last_sync_by`；
- 人工填的 `zh` 与站点 `Field title` 不同时，同步**只记一行提示日志**，
  **绝不**覆盖表里的值（这正是"站点 Field title"参考列存在的意义：给人看，
  让人决定是改站点还是保留本表的术语）。

> 历史背景：v1 曾让新行继承同 `calc keyword` 已有行的译文（当时叫 R4），
> 目的是一致性。v2 取消该规则 —— 一致性改由"人工编辑按 calc keyword 批量生效"
> （§4.4）保证，新行留空反而更符合"术语由人维护"的定位。

### 3.2 遍历范围的连带效应

只遍历 `is_active`，所以**停用一个 AnalysisService，会让它名下所有组合在下一轮
同步里变成"未激活"**；重新启用后会由对称重算自动恢复。这是刻意的选择，但要知道
它不是一个"人工停用"开关。因此本包额外提供 **「从站点刷新」** 按钮：在站点上改完
配置后不必等下一次进页面，点一下就能立刻看到结果。

### 3.3 写入身份

需求是"任何能打开列表页的人都触发同步"，而只读用户没有写权限。所以写入以
**提权身份**执行（`plone.api.env.adopt_roles(["Manager"])`），并记录触发者到
`last_sync_by` 与日志里。这是追加式台账能归因的唯一手段。手动刷新视图
（`@@glossary-sync`）权限同样是 Zope 内置的 `zope2.View`，写入一样走提权。

---

## 4. 日志与界面提示

**自动同步**（进页面）只写日志，不改动界面。主信号：

```
maitux.glossary: sync by <user>: +12 new, 3 deactivated, 1 reactivated, 0 unchanged (2.4s)
```

随后按需给出样例与对账提示：

```
maitux.glossary:   new          imp_specificity / imp_main_name_ref
maitux.glossary:   deactivated  imp_gone / imp_name
maitux.glossary: 4 row(s) where zh differs from the site Field title (...)
maitux.glossary: 2 duplicate AnalysisService keyword(s) - the row key is no longer one-to-one
maitux.glossary: 1 active Calculation(s) are used by no active AnalysisService
maitux.glossary: sync by <user> FAILED after 0.31s: <reason>
```

**手动刷新**除了写日志，还会用 `ploneapi.portal.show_message` 把结果摆在界面上：

```
同步完成：+12 new, 3 deactivated, 1 reactivated, 0 unchanged（耗时 2.40s）
同步失败：<原因>
未找到关键词对照表容器
```

排查命令：

```bash
docker compose logs instance | grep 'maitux.glossary:'
```

---

## 5. 查表 API（给报告 / 接口 / 其他 addon）

```python
from maitux.glossary.api import get_field_name, get_name, find_by_en, stats

get_field_name(u"imp_main_name_ref")                     # 本表的事实主键
get_name(u"imp_specificity", u"imp_main_name_ref")       # 带上下文，含兜底链
find_by_en(u"Main Component Name")                       # 反查
stats()                                                  # 覆盖率
```

规则：

1. **行级**：只有 `sync_state == active` 的行参与输出
2. **术语级兜底**：按 calc keyword 查时，只要该 keyword 还有**任意一个**活跃行，
   译名就仍然有效 —— 否则 `imp_name` 被 3 个检查项目使用、其中 1 个停用时，
   整个字段的译名会因为不相干的项目停用而查不到
3. 英文缺失回落中文；整体查不到返回 `None`，调用方自行兜底（一般原样输出 keyword）
4. 容器由 `maitux.glossary.utils.get_container()` 定位（先 `portal.setup`、再兜底
   站点根）—— **不要**在调用方自己去找容器，否则会重演 §8.1.1 那次故障

索引在**同一请求内复用**（挂在 request 上），所以报告里逐条查名字不会重复遍历容器。

---

## 6. 离线自检（不需要 Zope、不需要连站点）

```bash
# 从工作区根目录（E:\senaite\诺诚项目\senaite.core-2.x）
python src/maitux.glossary/src/maitux/glossary/tests/run_offline.py

# 也可以先 cd 进 addon 根（maitux.glossary/），脚本自带的用法就是这么写的
python src/maitux/glossary/tests/run_offline.py
```

检查 **9 组**断言：全部 `.py` 语法、全部 `.zcml`/`.xml` well-formed、profile 目录
存在性（R4，并断言 `translation_status` 字段已从 schema 移除）、确定性 ID
（含 `_` 歧义与 CJK）、新行默认值（`zh`/`en` 必须为空、不从站点回填）、
同步计划 R1–R3 的逐条断言、列表页静态配置（`self.icon`、刷新动作、
搜索覆盖 `service_title`、无 `translation_status` 列、**列定义不得开 `autosave`**、
DataManager 跳过无改动写入且**永不返回空列表**、**列头必须走 `self.label()`**、
**注入脚本与资源注册必须存在**）、**容器定位**
（setup 优先 / 站点根兜底，见 §8.1.1）、**翻译完整性**
（`.po` / `.mo` / 代码里的 msgid 三者一致，见下面的 i18n 一节）。

当前 **98/98 通过**（**Python 2.7 与 Python 3 都能跑**）。

静态检查（`addons/customers/lint_addon.py`，需 **Python 3**：Linux 用 `python3`，
Windows 用 `py -3`；不需要起容器）：

```bash
# 只报告本包（跨包冲突检查仍全量加载）—— 实测过的确切命令
py -3 E:/senaite/docker/senaite.docker/2.7.0-maitux1/addons/customers/lint_addon.py \
      --addon maitux.glossary

# 若工作区那份还没同步到 addons/customers/，可先用 junction/软链搭个假根：
#   <shim>/customers/maitux.glossary  ->  <本 addon 目录>
py -3 .../lint_addon.py --addons-root <shim> --addon maitux.glossary --no-baseline
```

实测（2026-09-11，真实 addons 根）：本包 **0 ERROR / 0 WARN / 0 INFO**、退出码 0、
判定 `pass` —— 而且该目录下**没有** `lint_baseline.json`，即按"有 ERROR 即拦"的
**严格口径**通过。全量扫描 25 个 addon 为 **0 ERROR / 9 WARN / 1 INFO**，WARN 全在
别的包（`maitux.reviewerassignment` 4、`maitux.instrument_acquisition` 3、
`maitux.capabilityinventory` 1、`maitux.hazardcategories` 1），本包属"干净"。

> `--in-container`（用容器里的 py2 跑 compileall，对应 E13）这里没有跑 —— 它的等效
> 检查已由离线自检第 1 组覆盖：每个 `.py` 都用 **Python 2.7** `compile()` 编译一遍。

i18n（改了 `.po` 之后，在 addon 根目录 `maitux.glossary/` 下执行）：

```bash
python tools/compile_mo.py     # .po -> .mo，纯标准库，不依赖 gettext 工具链
python tools/verify_po.py      # 全量校验：.po / .mo / 代码里的 msgid 三者一致
```

**为什么要自己编译**：宿主和容器都**没有 `msgfmt`**，Python 标准库也不提供
（`maitux.auditjournal/compile_locales.py` 的注释同理）。而且**没有任何自动编译** ——
`docker-entrypoint.sh` / `docker-initialize.py` / `Dockerfile` / `buildout.cfg` /
`gen-custom-addon.sh` 里都没有 po→mo 的步骤，**lint_addon.py 也不检查 .po/.mo**。
所以 `.po` 改了不重编译是**静默失效**：界面继续用旧译文，不报任何错。

`tools/verify_po.py` 现在查三类问题（全量，不再是硬编码的几个 key）：

| code | 含义 |
|---|---|
| `stale_mo` | `.po` 里有、`.mo` 里没有（或译文不一致）→ **改了 .po 没重编译** |
| `empty_msgstr` | `.po` 里该条目 msgstr 为空 |
| `missing_in_po` | 代码里 `_(u"...")` 用了、`.po` 里没有 → 新文案永远翻不出来 |

实现只维护这一份：`run_offline.py` 第 **[9]** 组直接 import 它来跑
（连同"校验器不是空转"的自检）。反向测试验证过它真的会拦：

```bash
# .po 加一条假 msgid、不重编译 .mo -> 应 FAIL(stale_mo)
# 代码里加一个 .po 没有的 msgid     -> 应 FAIL(missing_in_po)
```

---

## 7. 验收判据（逐条可观测）

| # | 检查项 | 可观测信号 |
|---|---|---|
| 1 | 包被 buildout 收录 | `docker compose logs instance \| grep gen-custom-addon` 出现 `maitux.glossary` |
| 2 | profile 安装成功 | 后台 Add-ons 显示已安装；站点下出现 `setup/keyword_glossary`（`portal_type` = `GlossaryEntries`） |
| 3 | **设置菜单入口** | 设置菜单（`@@lims-setup` / `@@maitux-setup`）里出现「检查项目关键词对照表」；直接打开 `/lims/setup/keyword_glossary` 出列表页 |
| 4 | **首次同步** | 容器日志出现 `maitux.glossary: sync by <你>: +N new, 0 deactivated, 0 reactivated, 0 unchanged`，N > 0 |
| 5 | **只增** | 再刷新一次列表页：`+0 new`，行数不变（幂等） |
| 6 | **新行 `zh`/`en` 为空** | 新出现的行两列都是空 —— 站点 `Field title` 没有被写进来 |
| 7 | **已存在不动** | 在站点上改某个 Calculation 的 Field title（不改 keyword），刷新列表页：`+0 new`，该行 `zh` **不变**，日志出现 `zh differs from the site Field title`（`zh` 为空时不报，属正常） |
| 8 | **消失 → 未激活** | 停用某个 AS，刷新列表页：`N deactivated`；点「未激活」按钮能看到那些行，状态标签为灰色 |
| 9 | **重现 → 活跃** | 重新启用该 AS，刷新列表页：`N reactivated`；行回到「活跃」筛选里 |
| 10 | **zh/en 就地编辑** | 有 ModifyPortalContent 的用户在列表里改一格 `en`（表格上方有保存提示；**Save 按钮出现在表格最底部**，与分页同一行，开始打字后才出现）→ 点 Save → 刷新后保留；日志出现 `'en' on calc keyword '<kw>' applied to N rows (batch by calc keyword, M already up to date)` |
| 11 | **按 calc keyword 批量改** | 改 `imp_name` 任一行的 `zh` → **所有**含 `imp_name` 的行（含未激活行）同步变化 |
| 12 | **检测项目参考列** | 列表出现 `Analysis Service` 列，值与站点上该 AS 的标题一致；该列只读、不入库 |
| 13 | **手动刷新按钮** | 工具栏出现「从站点刷新」；点它 → 走 `@@glossary-sync`，界面出现「同步完成：…（耗时 Xs）」，随后跳回列表页 |
| 14 | **双语搜索** | 搜索框输入中文（如 `峰面积`）或英文（如 `Area`）都能命中；输入检测项目标题或任一 keyword 也能命中 |
| 15 | 只读用户 | 用只读账号打开列表页：能看到数据、**没有**输入框；日志仍出现 `sync by <该账号>`（提权写入生效） |
| 16 | 同步失败不影响页面 | 人为制造异常（如临时把某 Calculation 的 interim 弄坏）→ 列表页仍能打开，日志出现 `sync by <user> FAILED` |
| 17 | 设置页不被标题拖崩 | 中文界面打开 `@@lims-setup` 返回 200（不是 500）—— 见 §8.1 |
| 18 | 查表 API | `bin/instance debug` 里 `from maitux.glossary.api import get_field_name; print(get_field_name('imp_name'))` |
| 19 | 离线自检 + lint | `python src/maitux.glossary/src/maitux/glossary/tests/run_offline.py` → `98/98 passed`（py2/py3 均可）；`py -3 addons/customers/lint_addon.py --addon maitux.glossary` → `0 ERROR / 0 WARN / 0 INFO`（§6） |
| 20 | **勾选行即保存** | 改一格 `en`（底部出现 Save）→ 勾选该行复选框 → 改动即刻保存（日志出现 `applied to N rows`），无需再点 Save —— 见 §8.1.5 |
| 21 | **列头跟随界面语言** | 界面切成英文后刷新列表页：列头/筛选按钮变英文（`I18N_LANGUAGE=en` → `Analysis category` / `Active`），中文界面下仍是中文 —— 见 §8.1.4 |

---

## 8. 已知边界（如实声明）

### 8.1 平台坑：容器的 `Title()` 必须返回 **utf-8 字节串**（重要）

本包容器放在 `portal.setup` 下、会出现在设置菜单里，而设置菜单由 core 的
`senaite.core.browser.bootstrap.bootstrap.BootstrapView.img_tag` 渲染 —— 它用
**字节串模板**拼字符串：

```python
"<img title='{}' src='{}/{}' {} />".format(title, ...)
```

Py2 下 `str.format`（字节串模板）遇到含中文的 `unicode` 会**先按 ASCII 编码**，
抛 `UnicodeEncodeError` → `@@lims-setup` 设置页直接 **500**。
平台其它 setup 项的标题都是 ASCII msgid，所以这条隐雷平时不暴露。

**约定**：容器（以及任何要进 Setup 菜单的内容类型）的 `Title()` 必须返回
**utf-8 字节串**，用 `api.to_utf8(...)`。这与平台既有约定一致
（`senaite.core.i18n.translate`、`bika.lims.utils.to_utf8` 都返回字节串）。
参考实现与完整注释：`src/maitux/glossary/content/glossaryentries.py`。

> **相关陷阱（列表页）**：`ListingView` 必须显式给 `self.icon`，否则
> `ListingTableTitleViewlet` 会退回 `bootstrap_view.get_icon_for(context)`，
> 对没有图标的内容类型抛异常，页面上表现为 listingtitle viewlet 报
> `LocationError`。本包用 `config.LISTING_ICON`（`senaite_theme/icon/setup`），
> 刷新按钮用 `REFRESH_ICON`（`senaite_theme/icon/retest`）。

### 8.1.1 平台坑：容器**位置**变了，所有读容器的地方都要跟着改（踩过一次）

v1 的容器在站点根 `<site>/keyword_glossary`，v2 搬到 `<site>/setup/keyword_glossary`。
当时**只改了创建/迁移**，漏改了读取侧：`utils.get_container()` 还在站点根找，
于是

- 「从站点刷新」按钮报 **「未找到关键词对照表容器」**（`browser/sync.py` 拿不到容器）；
- 查表 API（`api.build_index()` / `api.validate()`）**恒空**（§5 与判据 18 实际不可用）；
- 而**列表页看起来一切正常** —— 因为列表视图在 "正在看容器" 时会把
  `get_container()` 返回的 `None` 回退成 `self.context`，掩盖了故障。

**约定**：容器位置只在 `config.SETUP_FOLDER_ID` / `config.FOLDER_ID` 里定义；
定位只走 `maitux.glossary.utils.get_container()`，它**先找 `portal.setup`、
再兜底站点根**（老站点在迁移跑起来之前也要能读到旧容器）。除 `setuphandlers.py`
外，任何模块都不许自己 `portal._getOb(FOLDER_ID)`。

离线自检第 8 组断言就是这条的回归测试（用假的 `bika.lims.api` 真跑一遍定位逻辑：
setup 优先 / 站点根兜底 / 两处都有时 setup 胜 / 类型不对继续找 / 静态扫描越权访问）。

### 8.1.2 平台坑：`Message` 拼进 HTML 前必须**显式翻译**

`_(u"Active")` 返回的是 `Message`，只有被模板或 JSON 编码器处理时才会翻译。
若直接 `html_escape(Message)` 再拼进 HTML，拿到的是 **msgid（英文）** ——
症状是中文界面的状态列徽标显示 `Active`（而筛选按钮、字段值是中文）。

**约定**：`browser/listing.py` 里凡是拼进 HTML 的值，先过 `translated()`
（内部 `senaite.core.i18n.translate(msgid, to_utf8=False)`，返回 **unicode**；
返回字节串会在 `unicode % str` 时按 ASCII 解码而炸）。

### 8.1.3 平台坑：`ajax` 列**不要**开 `autosave`（本表踩过 500）

`senaite.app.listing` 的 JS（`webpack/app/listing.coffee:2017`）语义是：

```coffee
if column.autosave
  me.ajax_save()      # 每次单元格变化立刻发一个 set_fields 请求
```

本表的保存要**按 `calc keyword` 批量写所有兄弟行**（R5）。边填边存 → 连续请求并发改
同一批对象 → ZODB `ConflictError` → 提交阶段 **500**（前端弹 "Oops, an error occurred"，
那一格的修改还可能丢）。日志特征是同一秒成对出现 `ERROR Zope.SiteErrorLog ... set_fields`
加一条 `ZPublisher.Conflict ConflictError ... (N conflicts (M unresolved))`。

**约定**：`zh`/`en` 列只写 `"ajax": True`，**不写 `autosave`**。改动的值先进
`ajax_save_queue`，界面出现 **Save** 按钮，点一次 = 一个请求 = 一个事务，冲突面消失。
配套：DataManager 批量写时**跳过值没变的行**（少脏对象 = 少冲突），但**返回值必须非空**
—— core 的 `ajax_set_fields` 把空列表当保存失败（`Failed to set field of save queue` 500），
所以"没改内容"这种保存要回报用户编辑的当前行。

> 前端 `ajax_save()` 是**按 UID 顺序**逐个请求（`listing.coffee:2447-2450` 的
> `chain = chain.then(...)`），所以一次点击天然串行、不会并发。**残余边界**：core 的 JS
> 没有防重入标志，**双击 Save** 或在两个标签页里同时保存，仍可能撞到同一个
> `ConflictError` 500（ZODB 的并发写语义，服务端无法在 `set()` 里捕获 —— 冲突发生在
> 提交阶段）。遇到时刷新页面重做一次即可，数据不会错乱（批量改是幂等的）。

**Save 按钮在哪（用户必问）**：它在**表格最底部**的按钮栏里（`ButtonBar.coffee:119`，
与分页同一行，id `ajax_save_selection`），而且 **只有存在未保存改动时才出现**
（前端状态 `show_ajax_save`；刷新页面后队列为空 → 按钮本来就不显示，不是坏了）。
输入框的 `onChange` 是**每次按键**都会入队（`StringField.js:12-24` →
`updateEditableField`）—— 所以"一开始打字，按钮就出现了"，但此时**一个请求都没发**，
点 Save 才发。

因为 core 没有其它可写的提示位，本包把提示固定显示在**表格上方**
（`senaite.core` 的 `ListingTableDescriptionViewlet`，manager
`senaite.listingtabledescription`，渲染 `view.description`，支持 HTML）：

> 「中文名」「英文名」可直接编辑，改动只暂存在当前页面上（本表不做自动保存）：
> 请点表格最下方的 Save 按钮保存，否则离开本页会丢失。

### 8.1.4 平台坑：AJAX 送出的标签**不会**跟界面语言（列头恒中文）

症状：把界面切成英文后，**这张表的列头、筛选按钮仍是中文**（页面其它部分是英文）。

原因（实测）：列头/筛选/状态徽标是通过 AJAX 的 JSON 响应送前端的，而 core 这条
序列化路径**不认请求语言** —— `json.dumps(Message)` 只输出 msgid，把它翻成中文的
是列表视图里的翻译调用，它拿不到用户界面的语言；给请求带 `Accept-Language: en`、
`LANGUAGE=en` 都不改变结果（`LANGUAGE` 还被 Zope 默认设成 `en`，反而更乱）。

**约定**：本包所有**要显示**的标签都走 `browser/listing.py` 的 `self.label(...)`
（内部 `translated(msgid, self.request)`，返回 unicode）：

1. 先读 Plone 语言选择器写下的 **`I18N_LANGUAGE` cookie**（用户显式选择的界面语言）；
2. 没有 cookie 就交回 zope 协商（= 站点默认语言，保持老行为）。

验证（对着 AJAX 端点发请求）：

```bash
# 中文（站点默认）
curl -u admin:admin -H 'Content-Type: application/json' -X POST -d '{"review_state":"all"}' \
  ".../glossary-listing/folderitems" | grep -o '"category": {[^}]*}'
# 英文（模拟界面已切英文）
curl -u admin:admin -H 'Content-Type: application/json' -X POST -d '{"review_state":"all"}' \
  -b 'I18N_LANGUAGE=en' ".../glossary-listing/folderitems" | grep -o '"category": {[^}]*}'
```

### 8.1.5 勾选行即保存（注入脚本，不改 core）

core 的 Save 按钮在表格**最底部**，逐行录入时不好找。本包在**自己的列表页**里注入
一段脚本（`browser/static/glossary_listing.js`，由 `browser/assets.py` 的视图件插到
表格上方）：**勾选一行 = 保存当前所有未保存的改动**。

- 不自己发请求：脚本只是**程序化点击 core 的 Save 按钮**（`#ajax_save_selection`），
  保存链路、权限、批量规则全部复用官方实现；
- 行勾选框的 selector 是 `tbody input[type="checkbox"][name="uids:list"]`
  （`TableCells.coffee:110` 的 `select_checkbox_name + ":list"`），表头"全选"在
  `thead` 里，已被排除；
- 有**锁**：保存期间再勾别的行不会重复触发（那正是会撞 `ConflictError` 的用法），
  以"Save 按钮消失"（core 保存完会隐藏它）作为解锁信号，另有 15s 兜底；
- 没有未保存改动时 Save 按钮根本不存在 → 勾选不产生任何请求。

脚本的触发逻辑有离线测试：`node .tmp_deploy/test_glossary_listing.js`
（node + 极简 DOM 替身，7 条断言：会点保存 / 加锁 / 无改动不点 / 表头全选不点 /
取消勾选不点 / 用的是 core 的真实 id 与 name）。

### 8.2 其他边界

1. **"Analysis Service" / "Site Field title" 两个参考列依赖一个 5 分钟的进程内快照缓存**。
   同步发生在页面请求里，而表格行是随后由 AJAX 渲染的（另一个请求），拿不到页面
   请求里的同步结果。缓存过期后 `Site Field title` 显示 `-`，直到有人再次打开列表页
   或点「从站点刷新」。缓存按容器物理路径为键，多站点共进程不会串。
2. **choices（公式字段的下拉选项）不在本表范围内**（需求方决定只看计算公式）。
   后果：下拉选项的英文标签本表给不了。将来若要纳入，行键要变三级
   `(analysis_keyword, calc_keyword, choice)` —— 因为
   `choices_unique_keys_validator` 只保证**本字段自己的** choices 串内 key 不重复。
   详见 结构定稿.md §9 备案 B。
3. **一个检查项目的多个 Method/Calculation 取并集**：一行表示"这个项目会用到
   这个字段"，不表示它属于哪个 Calculation。
4. **未被任何 active AS 使用的 Calculation 不进表**（凑不出 `analysis_keyword`），
   每轮同步在日志里单独列出。
5. **`Analysis Keyword` 的唯一性只是表单级**：批量导入 / API 直建可绕过
   （本项目历史上出现过重复 AS）。故同步每轮都做重复检查并在日志里报 ERROR ——
   有重复时行键会一对多。
6. **并发**：两人同时进入列表页会对同一批新 key 各算一次计划，但确定性 ID 保证
   不会产生重复行（第二个人的插入会因 ID 已存在而失败并被记日志），
   随后由 `run_sync` 的 try/except 兜住，页面不受影响。
7. **每次进页面都全量遍历站点**（所有 active AnalysisService → 其 Method →
   Calculation → InterimFields）。这是需求要求的"每次进入自动遍历"，另有手动刷新
   按钮作为补充。开销可以从日志尾部的耗时看出来（`... (2.4s)`）；若哪天站点变大到
   不可接受，再考虑把自动同步降级为可选。

---

## 9. 目录结构

```text
maitux.glossary/
  setup.py
  README.md
  tools/compile_mo.py              # .po -> .mo（纯标准库）
  tools/verify_po.py               # 用 py2 gettext 校验 .mo 里的新 msgid
  src/maitux/glossary/
    __init__.py                    # PROJECTNAME / _ / logger（含离线降级）
    config.py                      # 常量（类型名、字段、状态值、图标、日志前缀…）
    interfaces.py                  # layer + 两个 marker + 两个 schema
    vocabularies.py                # State（活跃/未激活）词表
    keys.py                        # 纯函数：确定性 ID、安全取字符
    utils.py                       # 容器/条目定位、同 calc keyword 查找
    api.py                         # 只读查表 API
    configure.zcml
    content/{glossaryentries,glossaryentry}.py + configure.zcml
    datamanagers/glossaryentry.py  + configure.zcml   # 就地编辑的保存链路
    sync/{core,reader,runner}.py   # 纯逻辑 / 站点遍历 / 落库+日志
    browser/listing.py             # 列表页（筛选 / 就地编辑 / 搜索）
    browser/sync.py                # 「从站点刷新」视图（@@glossary-sync）
    browser/configure.zcml
    setuphandlers.py               # 在 setup 下建容器（含旧位置迁移）、权限、索引
    profiles/{default,uninstall}/
    locales/zh_CN/LC_MESSAGES/
    tests/run_offline.py           # 离线自检（98/98，py2/py3）
    browser/assets.py              # 把"勾选即保存"脚本注入到表格上方
    browser/static/
        glossary_listing.js       # "勾选行即保存"（见 §8.1.5）
```
