# INNOCARE.autoreceive

按**委托单位（Client）**控制登样后的「接收」行为。

| Client 上的「自动接收」 | 登样提交后的行为 |
| --- | --- |
| 勾选（如药物分析） | 跳过接收步骤，样品直接进入「已接收」 |
| 不勾选（其他部门 / 稳定性） | 停在「待接收」，由人点「接收」后记录接收人 / 时间 |

## 功能职责

- **Client 新增「自动接收」开关**（`src/INNOCARE/autoreceive/extenders/client.py`）：
  用 `archetypes.schemaextender` 给 Client 加一个布尔字段 `AutoReceive`，
  界面标签「Auto Receive Samples / 自动接收」，位于 Client 编辑页 Default 页签末尾，
  默认**不勾选**。不动 FTI、不改工作流、已装站点无数据迁移。
  - ⚠️ 该字段的 `BooleanWidget` **不能加 `render_own_label=True`**：
    Archetypes/SENAITE 的字段模板据此交出标签渲染权
    （`tal:ifLabel condition="not: widget/render_own_label | nothing"`），
    而 `widgets/boolean.pt` 自身不渲染标签 —— 结果是标签与说明都不显示，
    页面上只剩一个孤立的勾选框。其它控件（String/Reference/DateTime）会自渲染标签，
    所以它们可以传 `True`。
- **登样后按 Client 自动接收**（`subscribers.py`）：
  订阅样品的 `ObjectInitializedEvent`（核心 `create_analysisrequest()` 在创建末尾触发），
  覆盖 AR 新增页（登样）、稳定性任务板「创建样品」、以及任何走 API 的创建路径。
  命中时直接复用核心的 `receive_sample()` —— 行为与核心的全局自动接收完全一致
  （置状态、写 `DateReceived`、初始化分析项、写工作流接收人）。
- **界面显示「接收人」**：
  - 样品列表（`@@samples`）新增一列「接收人」（`adapters.py`，
    走 `senaite.app.listing` 的 `IListingViewAdapter` 扩展点，不覆盖视图）；
  - 样品详情页显示「接收人」字段（`extenders/analysisrequest.py`，
    只读展示字段 `ReceivedByName`，取值实时计算不落库）。
  - 两处都显示**用户全名**（取不到用户时回退登录名）。
- **接管全站的自动接收开关**（`setuphandlers.py`）：
  安装时把 Setup → Sampling → **Autoreceive samples** 置为不勾选。
  核心只有这一个全站开关，留着会让所有 Client 的样品都被自动接收。

## 依赖

- `senaite.core` / `senaite.lims`
- `archetypes.schemaextender`
- `senaite.app.listing`

不依赖任何其它客户 ADD-ON。

## 安装注册（buildout）

在 `custom-addon.cfg` 三处各加（该文件由 `gen-custom-addon.sh` 自动生成，
**不要手工维护**，下面只是说明生成规则）：

```ini
[buildout]
develop += /opt/addons/customers/INNOCARE.autoreceive
eggs    += INNOCARE.autoreceive
[instance]
zcml    += INNOCARE.autoreceive
```

源码挂载路径：容器内 `/opt/addons/customers`（仓库 `addons/customers`）。

## 生效方式

| 改动内容 | 生效方式 |
| --- | --- |
| `.py` / `.zcml` | **重启容器** |
| `profiles/*.xml` | 重启 + 在 Add-ons 页安装 / 重跑 `INNOCARE.autoreceive:default` profile |
| `locales/*.po` | 重新编译 `.mo` 后重启 |

首次部署：重启容器（entrypoint 会跑 `gen-custom-addon.sh` + buildout 把本包挂进来），
再到后台 **Add-ons** 页安装 `INNOCARE.autoreceive`。

## 使用与配置

1. 到**客户（Clients）**里打开需要自动接收的委托单位（如药物分析），
   勾选 **Auto Receive Samples / 自动接收**，保存；
2. 其它委托单位保持不勾选 —— 登样后样品处于「待接收」，
   需要有人在样品列表点「接收」，系统据此写入接收时间与接收人；
3. 样品列表可显示「接收人」列（列设置里默认开启）。

> ⚠️ **不要**再手工勾选 Setup → Sampling → Autoreceive samples。
> 该开关已被本 ADD-ON 接管，勾上会让**所有** Client 的样品都被自动接收。

## 验证判据（可观测）

1. Client「药物分析」勾选自动接收 → 登样一张样品 → 列表里该样品直接是**已接收**状态，
   `Date Received` = 提交时间，详情页「接收人」= 当前登录用户全名；
2. Client「稳定性」不勾选 → 登样后是**待接收**；人工点「接收」后
   `Date Received` 与「接收人」正确写入；
3. 稳定性任务板 →「创建样品」→ 结果与 1 / 2 一致；
4. 样品列表出现「接收人」列，值与工作流历史里的接收操作人一致；
5. Setup → Sampling → Autoreceive samples 为**不勾选**。

## 已知行为差异

- **自动接收不会触发「接收时自动打印贴标」**：贴标自动打印由工作流动作适配器触发，
  程序化接收不经过它。若需要，请用 Setup → Sticker 的「Register」时机，
  或在自动接收后人工打印。
- 安装时把全站 Autoreceive 置为不勾选后，AR 新增页的
  `is_automatic_label_printing_enabled()` 判定动作名会由 `receive` 变成 `register`，
  即登样后按「Register」配置决定是否自动打印贴标。

## 卸载

- 后台 Add-ons 页执行 `INNOCARE.autoreceive:uninstall`，或
- 移除 `custom-addon.cfg` 的生成来源（即从 `addons/customers` 移走本目录）后重启。

卸载会注销本包的 browser layer（Client / 样品字段扩展与列表列随之失效），
但**刻意不做**两件事：

- 不把全站 Autoreceive 重新勾上（原值无法可靠还原，擅自打开会让所有 Client 又被自动接收）；
- 不删除 Client 上的 `AutoReceive` 字段值（保留业务数据，重装即恢复）。

## 双语翻译（i18n）

- 使用独立 i18n 域 `INNOCARE.autoreceive`，
  `configure.zcml` 里 `<i18n:registerTranslations directory="locales" />` 注册。
- 翻译目录：`src/INNOCARE/autoreceive/locales/{en,zh,zh-cn,zh_CN}/LC_MESSAGES/`。
- `.po` 是源文件；`.mo` 是运行期实际加载的编译产物，改动 `.po` 后必须重新编译
  （容器内示例，`python_gettext` 随实例 eggs 一起提供）：

```bash
docker exec maitux-lims python -c "
import glob, sys
sys.path.insert(0, glob.glob('/home/senaite/senaitelims/eggs/cp27mu/python_gettext-*.egg')[0])
from pythongettext.msgfmt import Msgfmt
base='/opt/addons/customers/INNOCARE.autoreceive/src/INNOCARE/autoreceive/locales'
for lang in ('en','zh','zh-cn','zh_CN'):
    po='%s/%s/LC_MESSAGES/INNOCARE.autoreceive.po' % (base, lang)
    open(po[:-3]+'.mo','wb').write(Msgfmt(po, name=lang).get())
"
```

## 提交前

```bash
python addons/customers/lint_addon.py --addon INNOCARE.autoreceive
```
