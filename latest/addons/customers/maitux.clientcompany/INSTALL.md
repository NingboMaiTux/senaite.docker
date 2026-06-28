# maitux.clientcompany 安装说明

## 功能

本插件为 SENAITE 的 `Client` 增加一个 `Company` 字段，并在客户列表页面显示该字段。

安装后预期效果：

- 在 `Client` 新增/编辑页面可以输入公司名称
- 在 `http://127.0.0.1:8083/senaite/clients` 列表中显示 `Company` 列
- 旧客户数据如果没有公司名称，则显示为空

## 目录位置

推荐将客户插件源码放在宿主机目录：

```text
addons/customers/maitux.clientcompany
```

## buildout 配置

项目主配置 `buildout.cfg` 已自动 `extends = custom-addon.cfg`。

客户插件配置文件放在：

```text
addons/customers/custom-addon.cfg
```

默认情况下，`custom-addon.cfg` 保持为空，这样镜像构建阶段不会安装 `customers` 下的插件。

当你需要在容器内安装当前插件时，再把下面内容写入 `addons/customers/custom-addon.cfg`：

```ini
[buildout]
[buildout]
develop +=
    /opt/addons/customers/maitux.clientcompany

eggs +=
    maitux.clientcompany

[instance]
zcml +=
    maitux.clientcompany
```

## 安装步骤

1. 通过 `docker-compose.yml` 将 `./addons/customers` 挂载到容器内的 `/opt/addons/customers`
2. 通过 `docker-compose.yml` 将 `./addons/customers/custom-addon.cfg` 挂载到容器内的 `/home/senaite/senaitelims/custom-addon.cfg`
3. 保持镜像内只安装 `common` 插件，先正常启动容器
4. 需要安装本插件时，将上面的配置写入 `addons/customers/custom-addon.cfg`
5. 进入容器后执行一次 `buildout`
6. 重启容器或重启实例

## 关于运行时挂载

当前方案只挂载 `./addons/customers:/opt/addons/customers`，不挂载 `common`。

原因是：

- `common` 插件由镜像构建阶段直接安装，更稳定
- `customers` 插件保留为运行时挂载，更适合按客户需要手工 buildout 安装
- 避免运行时覆盖整个 `/opt/addons`，把已经在镜像里准备好的 `common` 插件元数据一并覆盖掉

注意：仅把源码挂载进容器还不够，`customers` 插件必须在容器内执行过 `buildout` 后才会被识别。

## 卸载

如需卸载，可在 Plone/SENAITE 的插件管理中执行对应 uninstall profile，或移除 buildout 中的配置后重新构建。
