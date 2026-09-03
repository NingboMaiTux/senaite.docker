# maitux.setupmenu

SENAITE 的 **Setup 菜单角色管理** add-on：把 `/@@lims-setup` 的配置入口（菜单）
按角色分配给不同人员，并支持 addon 菜单的自动识别与配置。

## 功能

> **"管理员"的定义**：持有 **Manager** 或 **Site Administrator** 角色。
> 注意：**不是**以 `senaite.core: Manage Bika` 权限判定 —— 该权限在 SENAITE
> 里授给了 LabClerk / LabManager / Manager（见 core rolemap.xml），
> 若用它当管理员，LabClerk/LabManager 会绕过过滤、始终看到全部菜单。

- **用户端 Setup 界面 `@@maitux-setup`**：与 `@@lims-setup` 同风格的 tile 网格，
  但只显示分配给当前用户角色的菜单。管理员（Manager/Site Administrator）始终可见全部。
- **管理界面 `@@maitux-setupmenu`**（表格）：逐菜单启用/停用 + 分配允许角色，
  入口位于 Site Setup → **Menu Management**（菜单管理）。
- **右上角齿轮按钮**：所有登录用户可见；管理员点击进入原 `@@lims-setup`，
  非管理员（含 LabClerk、LabManager、Analyst 等）点击进入新的 `@@maitux-setup`。
- **默认行为**：除管理员外，所有菜单默认不可见（安全默认），
  需在管理界面显式启用并分配角色。
- **Addon 菜单自动识别**：内容建在 `setup` / `bika_setup` 文件夹，
  或实现 `IMenuEntryProvider` 注册（见下），自动进入管理界面，无需二次开发。
- **双语支持**：英文 / 中文（`locales/`，随界面语言切换）。

## 安装

1. 将本包放入 addons 目录（与其它 `maitux.*` 一致），重新 buildout/启动容器。
2. Add-ons 页面安装 **Maitux Setup Menu**。

> ⚠️ 已安装的站点若更新了 `profiles/default/`（registry.xml 等），
> 必须 **Uninstall → Install** 重跑 profile 才生效（开发规则 R3）。

## 生效方式（改动后）

| 改动内容 | 生效方式 |
|---------|---------|
| `.py` / `.zcml` | 重启容器 |
| `.pt` 模板 | 重启即可 |
| `.js` / `.css` | 重启 + 浏览器硬刷新 `Ctrl+Shift+R` |
| `profiles/*.xml` | 重启 + 重跑 profile（R3） |

## 使用

1. 管理员进入 Site Setup → **Menu Management**（或直接访问 `@@maitux-setupmenu`）。
2. 默认"启用基于角色的菜单过滤"为开启状态：
   - 表格中勾选某菜单的 **Enabled**，并勾选允许看到的 **角色**；
   - 未启用或未分配角色的菜单，非管理员看不到。
3. 关闭全局过滤开关后，所有菜单对所有人可见（恢复原 `@@lims-setup` 行为）。
4. 普通用户通过右上角齿轮进入 `@@maitux-setup`，看到分配给自己的菜单。

## Addon 接入（新增菜单，无需改本包）

### 方式 A：内容对象（零代码）

把内容建在门户的 `setup`（新）或 `bika_setup`（旧）文件夹下，
即自动出现在管理界面与用户端界面。

### 方式 B：实现 `IMenuEntryProvider`（推荐，可定义默认隐藏）

1. 实现 provider 类：

```python
from maitux.setupmenu.interfaces import IMenuEntryProvider


class MenuProvider(object):
    """声明式注册 Setup 菜单条目"""

    def get_menu_entries(self):
        return [{
            "menu_id": "my.addon.settings",   # 必填，全局唯一
            "title": "My Addon Settings",      # 必填
            "url": "/@@my-settings",           # 必填，相对门户
            "icon": "fas fa-cog",              # 可选，FontAwesome
            "enabled": False,                  # 可选，默认隐藏，分配后可见
        }]
```

2. 在 addon 的 ZCML 注册：

```xml
<utility component=".menus.MenuProvider"
         provides="maitux.setupmenu.interfaces.IMenuEntryProvider"
         name="my.addon"/>
```

注册后自动出现在管理界面，无需改动 maitux.setupmenu。

## 卸载

Add-ons 页面卸载即可：安装标记、浏览器层、Site Setup configlet、
registry 记录都会被清理，齿轮按钮恢复原行为。

## 开发

- 翻译文件：`src/maitux/setupmenu/locales/<lang>/LC_MESSAGES/maitux.setupmenu.po`
  修改后运行 `tools/compile_mo.py` 重新编译 `.mo`。
- 单测（无 Plone 运行时，stub 模式）：
  `python -m unittest maitux.setupmenu.tests.test_setupmenu`
- 本包遵循 `SENAITE-Addon开发规则.md`（R1 权限注册顺序、R3 profile 重跑、
  R9b configlet title ASCII 等）。
