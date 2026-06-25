# medai.footercleanup 安装说明

## 包简介

**MEDAI FOOTER CLEANUP** (`medai.footercleanup 0.1.0`)

- 移除 SENAITE 底部栏的版权文字、外部链接和图标组
- 浏览器标签标题自动显示为 **MaiTux LIMS**（覆盖 `plone.htmlhead.title` viewlet，每次请求生效）

通过 `FooterViewlet` / `ColophonViewlet` 重写实现 footer 清理，通过 `TitleViewlet` 覆盖实现标题替换。

依赖：
- `senaite.core`
- `senaite.lims`
- `zope.interface`

---

## 方式一：pip 安装（推荐）

### 1. 将包复制到目标服务器的 SENAITE 自定义 addon 目录

```bash
# 例如
cp -r medai.footercleanup_0.1.0 /path/to/senaite/custom_addons/
```

### 2. 进入包目录，用 pip 以开发模式安装

```bash
cd /path/to/custom_addons/medai.footercleanup_0.1.0
pip install -e .
```

### 3. 重启 SENAITE 实例

```bash
bin/instance restart
```

### 4. 在 SENAITE 站点中激活

1. 登录 SENAITE -> `Site Setup` -> `Add-ons`
2. 找到 **MEDAI FOOTER CLEANUP**
3. 勾选并点击 `Activate`

安装成功后，SENAITE 底部栏的版权文字、外部链接和图标组将被移除。

---

## 方式二：buildout 安装

### 1. 将包放入 SENAITE buildout 自定义源码目录

```bash
cp -r medai.footercleanup_0.1.0 /path/to/buildout/src/
```

### 2. 编辑 `buildout.cfg`，添加 egg 和 develop 路径

```ini
[buildout]
eggs +=
    medai.footercleanup

develop +=
    src/medai.footercleanup_0.1.0

[sources]
medai.footercleanup = fs src/medai.footercleanup_0.1.0
```

### 3. 重新运行 buildout

```bash
bin/buildout
```

### 4. 重启 SENAITE 实例

```bash
bin/instance restart
```

### 5. 在 SENAITE 站点中激活

1. 登录 SENAITE -> `Site Setup` -> `Add-ons`
2. 找到 **MEDAI FOOTER CLEANUP**
3. 勾选并点击 `Activate`

---

## 卸载

1. `Site Setup` -> `Add-ons` -> 取消勾选 **MEDAI FOOTER CLEANUP** -> `Deactivate`
2. 如需完全移除，从 `buildout.cfg` 中移除对应 egg 和 develop 配置后重新运行 `bin/buildout`

---

## 文件清单

```
medai.footercleanup_0.1.0/
├── setup.py
├── README.rst
├── INSTALL.md              ← 本文件
└── src/
    └── medai/
        ├── __init__.py
        └── footercleanup/
            ├── __init__.py
            ├── configure.zcml
            ├── interfaces.py
            ├── browser/
            │   ├── __init__.py
            │   ├── configure.zcml
            │   ├── viewlets.py
            │   └── templates/
            │       ├── colophon.pt
            │       ├── footer.pt
            │       └── title.pt
            ├── profiles/
                ├── default/
                │   ├── browserlayer.xml
                │   ├── metadata.xml
                │   ├── medai.footercleanup.txt
                │   └── setuphandlers.py
                └── uninstall/
                    ├── browserlayer.xml
                    ├── metadata.xml
                    └── medai.footercleanup_uninstall.txt
```
