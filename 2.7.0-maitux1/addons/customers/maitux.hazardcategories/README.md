# maitux.hazardcategories

危害分类（Hazard Category / 样品性质字典）管理扩展，提供可编辑的危害分类维护列表与 AR 样品性质多选。

## 功能职责

- 内容类型 `HazardCategories`（容器）/ `HazardCategory`（分类项，见 `src/maitux/hazardcategories/content/`）。
- **入口形式：设置主页的入口 tile**。容器建在 `<site>/setup/hazard_categories` 下，senaite.core 设置菜单的 `setupitems()`（`setup.objectValues() + bika_setup.objectValues()`）会自动把它收录成设置页上的一个入口 tile，点进去就是维护列表（`browser/controlpanel.py`，默认视图 `hazardcategories-controlpanel`）。符合开发规则 **R11 的「静态数据」分支**：容器默认视图 + Setup 菜单入口，不注册 `@@overview-controlpanel` configlet。
  - 入口的可见性由 `maitux.setupmenu` 管理：Site Setup → Menu Management（`@@maitux-setupmenu`）里勾选 **Enabled** 并分配 **Allowed roles**，非管理员用户从右上角齿轮进入 `@@maitux-setup` 时按角色过滤。
  - **不再**把容器注册进 BikaSetup 的 `sidebar_folders`（旧版是侧边栏里的一个文件夹节点）；安装/卸载都会主动摘除该旧注册，见 `setuphandlers.remove_from_sidebar`。
  - 旧站点若容器仍在站点根 `<site>/hazard_categories`，安装时会 cut/paste 搬进 `setup`（保留 UID 与全部子项）。
- 容器 `Title()` 返回 **utf-8 字节串**（设置页 `bootstrap.img_tag` 用字节串模板拼 title，含中文的 unicode 会让 Py2 抛 `UnicodeEncodeError` → 设置页 500），约定同 `maitux.glossary`。
- 默认分类（见 `config.py` / `profiles/default/registry.xml`）：GHS01–GHS09、BIO01、RAD01、NIR01、MAG01、ELEC01、HSURF01、HOT01、STEAM01、COLD01、ASPH01，含中英文与图标路径。
- 种子数据 upsert（`setuphandlers.py`）：`ensure_hazardcategory_data_synced` 按 code 幂等写入默认分类；`ensure_setup_catalog_usage_scope_index` / `ensure_hazardcategories_in_setup_catalog` 维护 catalog 索引与列。
- 容器定位统一走 `utils.get_container()`（先 `<site>/setup`、再兜底站点根），其它模块不要自己找容器。
- 翻译工具（`translation.py`）：`translate_with_fallback` 提供本域回退翻译。
- 词汇工厂（`configure.zcml` / `utils.py`）：
  - `maitux.hazardcategories.vocabularies.UsageScope`
  - `...EditableHazardCategories`
  - `...ForReference`（reference 范围）
  - `...ForAR`（AR only 范围）
- 与 AR 关联：样品性质（SampleProperties）多选在 `INNOCARE.arextension` 的 AR 扩展中引用本 addon 词汇，范围 both + AR only。

## 依赖

- `senaite.core` / `senaite.lims`
- `plone.api`、`plone.app.registry`、`plone.supermodel`
- `zope.component`、`zope.interface`、`zope.i18n`
- `Products.CMFPlone`

**不依赖** `INNOCARE.arextension` / `maitux.projects` / `maitux.roles` 或其它客户 ADD-ON。

## 安装注册（buildout）

```ini
[buildout]
develop += /opt/addons/customers/maitux.hazardcategories
eggs    += maitux.hazardcategories
[instance]
zcml    += maitux.hazardcategories
[plonesite]
profiles += maitux.hazardcategories:default
```

## 安装顺序

本 addon **独立部署**，不再依赖 `INNOCARE.arextension`。历史 pickle 别名（`maitux.arextension.* -> INNOCARE.arextension.*`）已迁回 `INNOCARE.arextension` 自己的 `__init__.py`。

目标环境顺序：**先 `maitux.hazardcategories:default`，再 `INNOCARE.arextension:default`**（INNOCARE 的 AR 扩展字段 `SampleProperties` 运行期引用本 addon 的 HazardCategory 内容类型与词汇）。

## 改动后的生效方式

| 改动内容 | 生效方式 |
| --- | --- |
| `.py` / `.zcml` | 重启实例 |
| `profiles/*.xml` | 重启 + 重跑 profile |
| 容器位置 / 入口形式（`setuphandlers.py`） | 重启 + 重跑 `maitux.hazardcategories:default`（Add-ons 页面卸载再安装，或跑 `post_install`），才会执行「搬进 `setup` + 摘除侧边栏注册」 |

重跑 profile 后自查：

1. `<site>/setup` 设置页出现「样品属性」tile（`@@lims-setup`），点进去是维护列表；
2. `<site>` 根目录不再有 `hazard_categories`；
3. `@@maitux-setupmenu` 里能看到该入口（Menu 列），勾选 Enabled + Allowed roles 后 Save。

## 卸载

- 执行 `maitux.hazardcategories:uninstall` profile 后，移除 `custom-addon.cfg` 三处注册。
- 卸载**不删除数据**：`<site>/setup/hazard_categories` 容器与其分类项原样保留在 ZODB 里（同 `maitux.glossary` 的口径），只是摘掉侧边栏旧注册；要彻底清掉请人工删除容器。
