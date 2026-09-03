# maitux.setupmenu（Setup 菜单角色管理）

SENAITE 的 Setup 菜单（`@@lims-setup` 上的配置入口 tile）**按角色分配**插件：
不同角色登录后，在 Setup 界面只能看到分配给该角色的菜单；addon 创建的菜单
可自动识别并在管理界面配置，无需二次开发。

---

## 1. 功能一览

| 功能 | 说明 |
| --- | --- |
| 用户端 Setup 界面 `@@maitux-setup` | 与 `@@lims-setup` 同风格的 tile 网格，**只显示分配给当前用户角色的菜单**；未分配任何菜单时显示空状态提示 |
| 管理界面 `@@maitux-setupmenu` | 表格：逐菜单**启用/停用** + **分配允许角色** + 全局过滤开关；入口：Site Setup → **Menu Management（菜单管理）** |
| 右上角齿轮按钮 | **所有登录用户**可见；点击后：管理员 → 原 `@@lims-setup`；非管理员 → `@@maitux-setup`（按角色过滤） |
| 默认安全 | 除管理员外，**所有菜单默认不可见**，需在管理界面显式启用并分配角色 |
| Addon 菜单自动识别 | 内容建在 `setup` / `bika_setup` 文件夹，或实现 `IMenuEntryProvider` 注册 → 自动出现在管理界面，**无需改动本插件** |
| 双语 | 英文 / 中文（`locales/`，随界面语言切换） |

### ⚠️ "管理员"的定义（重要）

本插件把 **Manager** 和 **Site Administrator** 角色视为管理员：

- 管理员**始终可见全部菜单**，不受过滤影响；
- 管理员齿轮进入原 `@@lims-setup`。

**不是**用 `senaite.core: Manage Bika` 权限判定！该权限在 SENAITE 的
rolemap 里授给了 **LabClerk / LabManager / Manager** 三个角色 —— 若用它当
"管理员"，LabClerk / LabManager 也会绕过过滤、始终看到全部菜单（这是本项目
实测踩过的坑，勿改回）。

---

## 2. 界面与行为

### 2.1 管理界面 `@@maitux-setupmenu`（Site Setup → Menu Management）

| 列 | 说明 |
| --- | --- |
| Menu | 菜单标题（链接到目标页面） |
| Source | 来源徽标：`Setup`（新 setup 文件夹）/ `Legacy Setup`（bika_setup）/ `Add-on`（addon 注册/虚拟条目） |
| Enabled | 勾选 = 启用该菜单（不启用则非管理员一律不可见） |
| Allowed roles | 每个角色一个勾选框，可多选 |

表单顶部有 **"启用基于角色的菜单过滤"** 开关（默认开启）：

- 开启：只显示已启用且分配给当前用户角色的菜单；
- 关闭：所有菜单对所有人可见（相当于临时恢复原 `@@lims-setup` 行为）。

### 2.2 可见性规则

```
对某个菜单、某个用户（非管理员）：
  1. 全局开关关闭        → 可见
  2. 菜单未启用          → 不可见（默认）
  3. 已启用但未分配角色  → 不可见
  4. 已启用且用户角色 ∩ 分配角色 ≠ ∅ → 可见
管理员（Manager / Site Administrator）→ 始终可见
```

### 2.3 齿轮按钮

- 未登录：不显示齿轮；
- 管理员：齿轮 → `@@lims-setup`（原界面，全部菜单）；
- 其它登录用户（含 LabClerk、LabManager、Analyst、Sampler…）：齿轮 → `@@maitux-setup`。

---

## 3. 安装 / 部署

1. 将 `maitux.setupmenu` 整个目录放入 addons 目录（与其它 `maitux.*` 一致，
   `setup.py` 位于一级目录下），重新 buildout / 启动；
2. Add-ons 页面安装 **Maitux Setup Menu**（若已安装过旧版，先卸载再安装，
   确保 registry 记录与浏览器层就位）。

> ⚠️ 更新了 `profiles/default/`（registry.xml 等）后，对已安装站点必须
> **Uninstall → Install** 重跑 profile 才生效（开发规则 R3）。

### 改动后的生效方式

| 改动内容 | 生效方式 |
| --- | --- |
| `.py` / `.zcml` | **重启实例** |
| `.pt` 模板 | 重启即可 |
| `.js` / `.css` | 重启 + 浏览器硬刷新 `Ctrl+Shift+R` |
| `profiles/*.xml` | 重启 + 重跑 profile |

---

## 4. 使用步骤

1. 用 **Manager** 账号登录 → Site Setup → **Menu Management**；
2. 逐个菜单：勾选 **Enabled**，并勾选允许看到的**角色**（可多选）→ **Save**；
3. 用目标角色账号登录（如 Analyst），点右上角齿轮 → 进入 `@@maitux-setup`，
   即可看到分配给该角色的菜单；
4. 想临时放开全部菜单时，在管理界面取消"启用基于角色的菜单过滤"→ Save。

---

## 5. Addon 接入（新增菜单，无需改本插件）

### 方式 A：内容对象（零代码）

把内容建在门户的 `setup`（新）或 `bika_setup`（旧）文件夹下即可自动出现。

### 方式 B：实现 `IMenuEntryProvider`（推荐，可默认隐藏）

```python
# 你的 addon 的 menus.py
from maitux.setupmenu.interfaces import IMenuEntryProvider


class MenuProvider(object):
    def get_menu_entries(self):
        return [{
            "menu_id": "my.addon.settings",  # 必填，全局唯一
            "title": "My Addon Settings",     # 必填
            "url": "/@@my-settings",          # 必填，相对门户
            "icon": "fas fa-cog",             # 可选，FontAwesome
            "enabled": False,                 # 可选，False=默认隐藏，分配后可见
        }]
```

```xml
<!-- 你的 addon 的 configure.zcml -->
<utility component=".menus.MenuProvider"
         provides="maitux.setupmenu.interfaces.IMenuEntryProvider"
         name="my.addon"/>
```

注册后自动出现在管理界面（来源 = Add-on），可启用并分配角色。

### 菜单 ID 规则

- 内容对象：`uid:<对象的 UID>`（稳定，不随路径迁移变化）；
- addon / 虚拟条目：`url:<完整 URL>`（无 UID 时用 URL 兜底）。

---

## 6. 与其它 addon 的共存

- **`maitux.groupmanagement`**：其"组管理"入口（通过覆盖 `@@lims-setup`
  追加的虚拟 tile）会自动出现在本插件管理界面中（来源 = Add-on），
  可正常启用与分配角色。本插件**不覆盖** `@@lims-setup`，两者无冲突。
- 其它 addon 若通过内容对象或 `IMenuEntryProvider` 注册菜单，同样自动识别。

---

## 7. 常见问题（FAQ）

**Q1：给角色分配了菜单，但该账号登录后还是看到全部菜单？**
先确认该账号的角色：若带 **Manager / LabClerk / LabManager**（尤其
LabClerk/LabManager —— 它们持 `senaite.core: Manage Bika`），会命中管理员
或旧权限逻辑。本插件已改为**仅 Manager / Site Administrator 视为管理员**，
其余角色全部走过滤；若仍全部可见，请确认看的是 `@@maitux-setup`（齿轮进入），
而不是直接访问 `@@lims-setup`（旧页面本身不过滤，且要求 ManageBika）。

**Q2：直接输入 `@@lims-setup` 地址能看到全部菜单？**
会。`@@lims-setup` 是 SENAITE 原页面（ManageBika 权限 + 不过滤）。
本插件的新界面是 `@@maitux-setup`。如业务上必须让 `@@lims-setup`
也按角色过滤，需要额外覆盖该页面（注意与 groupmanagement 的 layer
冲突问题），请联系插件维护者评估。

**Q3：勾选了角色保存后，回显又复原了？**
旧版本存在该问题（ZPublisher 对 `:list` 表单标记的处理差异），
已修复并加回归测试。请确保运行的是最新代码并重启实例；仍异常时查看
实例日志中 `maitux.setupmenu save:` 一行的 `roles=` 值。

**Q4：默认情况下普通用户什么都看不到？**
是的 —— 安全默认：除管理员外所有菜单默认隐藏。需要在管理界面逐个
启用并分配角色。

---

## 8. 开发

- 翻译：`locales/<lang>/LC_MESSAGES/maitux.setupmenu.po`，
  修改后运行 `tools/compile_mo.py` 重新编译 `.mo`；
- 单测（无 Plone 运行时，stub 模式，Py2/3 均可）：

  ```bash
  python -m unittest maitux.setupmenu.tests.test_setupmenu
  ```

- 主要模块：
  - `api.py` — registry 读写 + 可见性判定（`is_admin` / `is_menu_visible_for`）
  - `menus.py` — 菜单收集（生效的 `@@lims-setup` 视图 + `IMenuEntryProvider`）
  - `browser/setupview.py` — `@@maitux-setup` 用户端视图
  - `browser/menumanagement.py` — `@@maitux-setupmenu` 管理视图
  - `browser/toolbar.py` — 齿轮按钮（plone.toolbar 管理器覆盖）
- 遵循 `SENAITE-Addon开发规则.md`（R1 权限注册顺序、R3 profile 重跑、
  R8 生效方式、R9b configlet title ASCII 等）。

---

## 9. 卸载

Add-ons 页面卸载即可：安装标记、浏览器层、Site Setup configlet、
registry 记录都会被清理，齿轮按钮恢复原行为（仅管理员可见、链接回原页面）。
