# Customer Addons

本目录存放「仅部分客户需要」的 SENAITE / Plone add-on，通过 compose 挂载到容器的
`/opt/addons/customers`。

## 常用文档

- `SENAITE-Addon开发规则.md`：本项目的 addon 开发约束与踩坑总结
- `Git操作速查表.md`：本项目常用 Git 命令与提交流程

## 部署人员只需要做一件事


**把 add-on 源码目录放进本目录（或从本目录删掉），然后重启容器。**

buildout 配置 `custom-addon.cfg` 已经改成**自动生成**，不要再手工维护：

- 容器每次启动，`/gen-custom-addon.sh` 会先删掉旧的 `custom-addon.cfg`，
  再遍历本目录重新生成一份（写到容器里的
  `/home/senaite/senaitelims/custom-addon.cfg`，不落到宿主目录）；
- 生成内容会打印在容器日志里，`docker compose logs instance | grep gen-custom-addon`
  就能看到收录了哪些包、跳过了哪些；
- 本目录下**没有任何 add-on 时不生成**该文件，容器启动可以整段跳过 buildout，
  启动明显更快；
- add-on 配置和上次 buildout 用的完全一致时同样跳过 buildout。要强制重跑：
  `docker exec maitux-lims rm -f /home/senaite/senaitelims/.buildout-applied`
  后重启，或直接重建容器。

历史上手工维护这个文件带来的三类事故（写错、漏项、删了目录但忘了改 cfg
导致 buildout 失败 → 容器无限重启）到此为止。

## add-on 目录要满足什么才会被收录

| 要求 | 说明 |
|---|---|
| 是本目录的**一级子目录** | 不要再套一层客户目录，否则扫不到 |
| 目录里有 `setup.py` | 没有 `setup.py` 的目录（空壳、残留、临时目录）一律**跳过并打日志** |
| `setup.py` 里有 `name=` | egg 名从这里读，**不使用目录名** —— 两者允许不一致，例如目录 `maitux.oauth2.0` 的 egg 名是 `maitux.oauth2` |

生成规则（细节见 `SENAITE-Addon开发规则.md` 与 `/gen-custom-addon.sh` 顶部注释）：

- `[buildout] develop +=` → `/opt/addons/customers/<目录名>`
- `[buildout] eggs +=` → `setup.py` 里的 `name=`
- `[instance] zcml +=` → **每个有 `configure.zcml` 的包都写一条**（复现历史上
  长期跑通的那份配置）。唯一例外是分发名与代码目录大小写不一致的包（如
  `INNOCARE.Reportdesign` 对 `INNOCARE/reportdesign`），显式 include 会重复注册，
  只能交给 autoinclude —— 生成器会在日志里点名说明
- ⚠️ **ZCML 里引用 `senaite.core` 权限的 add-on，必须在自己的 `configure.zcml` 里
  `<include package="senaite.core.permissions" />`**。显式 slug 和 autoinclude
  都不保证排在 `senaite.core` 之后，缺这一行启动就
  `ComponentLookupError: (IPermission, 'senaite.core.permissions...')`，整站起不来
  （见 `SENAITE-Addon开发规则.md` R1）
- 带 `overrides.zcml` 的包补一条 `<egg>-overrides`（R5b）
- `[instance] initialization = import pkg_resources` 固定写入，缺了它
  `collective.recipe.plonesite` 建站会静默失败、站点 404
- **不写 `[plonesite] profiles`**：`buildout.cfg` 里是普通赋值
  `profiles = senaite.lims:default`，extends 链上层优先级最高，在下层追加的
  profile 会被整个丢掉。客户 add-on 的 profile 一律登录后台
  `站点地址/prefs_install_products_form` 手工安装

## 目录结构约定

```text
addons/
  common/                      # 所有客户通用，构建时 COPY 进镜像
    maitux.branding/
  customers/                   # 客户专属，运行时挂载
    maitux.esignature/         # <- 一级子目录，带 setup.py
    INNOCARE.labeldesign/
```

- **不要**按客户再分一层目录（`customers/customer-a/xxx.addon/`）：扫描只看一级
  子目录，套一层就收录不到。多客户请靠 add-on 命名（如 `INNOCARE.*`）区分，
  或给每个客户单独一份 compose / 部署目录。
- 目录名尽量与 egg 名一致，且**大小写要和代码目录一致**（R5c）。
- 只保存 zip 不行，必须是解压后的源码目录：buildout `develop` 直接引用源码目录。
  要留档 zip，就和源码目录并存。

## 本目录里那几个非 add-on 文件是什么

这几个不是 add-on（没有 `setup.py`，扫描会跳过），是**规则检查工具**，
刻意和 `SENAITE-Addon开发规则.md` 放在一起 —— 规则在这、检查器不在，
照规则写完的人跑不了检查。

| 文件 | 是什么 |
|---|---|
| `lint_addon.py` | 静态检查器。把开发规则里的 R1 / R4 / R4b / R5b / R5c / R5d / R9b / R12 / R14 机器化，外加 Python 2.7 编码陷阱 |
| `lint_baseline.json` | **门禁基线 = 已知欠账清单**。门禁只拦不在这张表里的 ERROR |
| `selftest_r14.py` | R14 规则的合成用例自测（10 例） |
| `selftest_gate.py` | 门禁语义自测（17 例） |

**改完 add-on、重启容器之前跑一遍**：

```bash
python lint_addon.py --addon <你的包名>
```

**批量看全部包**（评审别人的包、交接、定期体检）：

```bash
python lint_addon.py --summary
```

### 门禁语义：不新增 ERROR，不是 lint 全绿

退出码 1 = **你这次新增了 ERROR**。仓库里现存的欠账已记在
`lint_baseline.json`，不会算到你头上 —— 所以**红了就是你的**，别忽略。

几条纪律，请务必遵守：

- **不要为了让门禁变绿而往 `lint_baseline.json` 里加条目。** 那等于把
  责任推给下一个人。本次新增的 ERROR 就该修。
- 基线里每条的 `note` 不许留空（为什么还欠着 / 谁负责）。
- 修掉一条基线里的问题后，重写基线把它剔掉：
  `python lint_addon.py --write-baseline`（必须全量扫描，带 `--addon` 会被拒绝）。
  lint 会主动提醒你哪些条目"已经不再出现"。
- 想看**总欠账**（无视基线）：`python lint_addon.py --no-baseline`

> `lint_addon.py` 和两个 `selftest_*.py` 各有两份（另一份在维护者的技能目录里），
> 内容必须一致。lint 启动时会比对并在不一致时警告 —— 看到那条警告说明有人
> 只改了一份，**两个人跑同一条规则会得到不同结果**，先把它同步掉。

## 常见问题

**新加了 add-on，重启后没生效？**
先看日志有没有收录：`docker compose logs instance | grep gen-custom-addon`。
最常见原因是目录里没有 `setup.py`，或多套了一层客户目录。

**想临时停用某个 add-on？**
把目录移出本目录（或改名成不带 `setup.py` 的形式）再重启即可，不用改任何配置。
注意：源码不再加载，但站点里该 add-on 已安装的 profile / 数据不会自动清理，
需要时先在后台执行它的 `uninstall` profile。
