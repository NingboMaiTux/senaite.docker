# medai.autopublish

MedAI 实验室数据自动发布与审核工作流增强 Addon for SENAITE LIMS。

---

## 功能列表

### 1. Samples 审核入口分拆

将默认的 Samples 列表按照审核角色拆分为两个独立入口：

| 入口 | 目标角色 | 功能 |
|------|---------|------|
| **待审核测试** | Verifier | 只看有待审核分析项的样品（`to_be_verified > 0` 且 `verified != total`） |
| **待批准样品** | LabManager | 只看所有分析已审核通过、等待批准的样品（`verified == total`） |

- 左侧导航栏增加两个 Portal Folder 入口
- Folder 配置了角色权限隔离（Verifier 看不到"待批准样品"，LabManager 看不到"待审核测试"）
- 样品数量列改为三数格式：**待审核 / 已审核 / 总数**

### 2. Department 部门过滤

按当前用户的 LabContact 所属 Department 过滤 Samples 列表和样品内部的 Analyses 列表。

#### Setup 配置开关

在 Setup → Sampling 页面中增加 **Enable Department Filtering** 开关（默认关闭）：

- 关闭时（默认）：所有用户看到全部样品和分析（适合小实验室）
- 开启时：按 Department 过滤生效（适合大实验室/分部门管理）

#### 样品层过滤（Samples 列表）

- 给 Sample Catalog 新增 `department_uids` 索引（多值 KeywordIndex）
- **非 LabManager/Manager** 的用户：只看到包含本部门分析项目的样品
- **LabManager / Manager**：不受限制，看到所有样品

#### 分析层过滤（Analyses 列表）

点击样品进入详情页后，Lab / Field / QC 三个 Analyses 表格也会按 Department 过滤：

- 给 Analysis Catalog 新增 `getDepartmentUID` 索引（单值 FieldIndex）
- 非 LabManager/Manager 的用户：只看到属于自己部门的分析项目
- 通过 `IListingViewAdapter` subscriber 模式实现，不修改 senaite.core 源码

### 3. Analysis Reports 入口（Portal Folder）

- 左侧导航栏增加 **Analysis Reports** 入口
- 仅 LabManager 可见（Folder View 权限限制）

### 4. Report Drafting 工作流节点

在 `verified → published` 之间插入 `report_drafting` 状态：
- Setup 增加 `report_drafting_enabled` 开关（Setup → Sampling 页面）
- 可按 SampleType 独立启用/禁用

### 5. Auto Publish 自动发布

- SampleType 上增加 `auto_publish` 字段（Disabled / Enabled）
- 启用后，该 SampleType 的样品在最后一个分析 Verified 后自动 Publish
- 在 `report_drafting` 启用时，自动从 `report_drafting` 流转到 `published`

---

## 文件结构

```
medai.autopublish/
├── behaviors/
│   ├── auto_publish.py           # SampleType auto_publish 字段
│   ├── report_drafting_setup.py  # Setup report_drafting 开关
│   └── department_filter.py      # Setup department_filter 开关
├── browser/
│   ├── samples.py                # Samples 视图（审核分拆 + department 过滤）
│   └── analyses_filter.py        # Analyses 列表 department 过滤（IListingViewAdapter）
├── catalog/
│   ├── indexer.py                # department_uids + getDepartmentUID 索引器
│   └── configure.zcml
├── subscribers/
│   ├── auto_publish.py           # 自动发布事件订阅
│   ├── publish_adapter.py        # 发布适配器
│   └── setup_sidebar.py          # 侧边栏 Portal Folder 维护
├── workflows/
│   └── report_drafting.py        # report_drafting 工作流定义
├── setuphandlers.py              # 安装/卸载处理
└── configure.zcml
```

---

## 部署

### 当前开发环境（本机 8083 / 8084）

```bash
# 8083 开发环境
docker exec senaite-source-clean-2x bin/buildout -c buildout.cfg -N
docker restart senaite-source-clean-2x

# 8084 官方环境
docker exec senaite-official-dev bash /home/senaite/entrypoint_no_buildout.sh
docker restart senaite-official-dev
```

### 迁移到其他 Senaite 环境

本 addon 通过 `install.py` 脚本支持快速部署到其他 Senaite Docker 容器（无需 buildout）。

**前提条件：**
- 目标环境基于 Senaite 2.x Docker 镜像
- 容器内路径结构为 `/home/senaite/senaitelims/`

**步骤：**

```bash
# 1. 将 medai.autopublish 文件夹拷贝到目标容器的 src/ 目录
docker cp medai.autopublish <目标容器>:/home/senaite/senaitelims/src/medai.autopublish

# 2. 在容器内运行 install.py（修改 interpreter path + 创建 egg-link + ZCML slug）
docker exec <目标容器> python /home/senaite/senaitelims/src/medai.autopublish/install.py

# 3. 重启容器
docker restart <目标容器>

# 4. 在 Site Setup → Add-ons 中激活 "MedAI Auto Publish"
```

**`install.py` 做了什么：**
| 操作 | 说明 |
|------|------|
| 修改 Zope interpreter | 将 `src/medai.autopublish/src` 加入 `sys.path` |
| 创建 egg-link | `develop-eggs/medai.autopublish.egg-link` 指向包目录 |
| 创建 ZCML slug | `parts/instance/etc/package-includes/` 下生成 configure + overrides slug |

**可选：正式 buildout 部署方式**

如果目标环境使用 buildout 管理包，也可以在 `buildout.cfg` 中配置：

```ini
[buildout]
develop =
    src/medai.autopublish

[instance]
eggs =
    medai.autopublish

zcml =
    medai.autopublish
    medai.autopublish-overrides
```

然后 `bin/buildout -N` + 重启容器。

### 安装后

1. 在 Site Setup → Add-ons 中激活 `MedAI Auto Publish`
2. **注意**：post_install 会自动开启 `AutoVerifySamples`，如需关闭请到 Site Setup 手动关闭
3. Department 过滤功能首次启用后，需要在 ZMI 中重建 `senaite_catalog_sample` 和 `senaite_catalog_analysis` 索引
4. 首次访问 `@@redirect-samples-to-verify` / `@@redirect-samples-to-approve` 会自动创建 Portal Folder

### 更新

仅 addon 代码改动：重启容器即可（`docker restart <container>`）
改 `configure.zcml` / buildout 配置：需要重新 buildout
