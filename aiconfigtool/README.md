# AiConfigTool v2.0

> Senaite 实验室 LIMS 系统的 AI 辅助配置工具。
> 自然语言描述变更需求 → 自动生成 Senaite Addon 包（源码 + 文档 + 部署指南）→ 实施人员部署。

本目录为重构后的 AiConfigTool 工具本体，与 `../latest/`（Senaite Docker 环境）平级。

---

## 目录结构

```
aiconfigtool/
├── frontend/                     # React + TypeScript 前端
│   └── src/
│       ├── features/             # 按业务领域拆分的 Feature 模块
│       │   ├── workspace/        # 🏠 工作台（公司/站点管理）
│       │   ├── addon-studio/     # 🤖 Addon 工坊（一站式生成）★ 核心
│       │   ├── delivery/         # 📦 交付管理
│       │   ├── permissions/      # 🔐 权限工具
│       │   └── settings/         # ⚙️ 设置
│       ├── core/                 # 跨 Feature 共享（组件/hooks/types/utils）
│       ├── routes/               # 路由配置
│       └── mocks/                # 开发用 Mock 数据
│
├── backend/                      # Python 后端（零第三方运行时依赖）
│   └── maitux/aiconfigtool/
│       ├── domain/               # 领域模型层（纯数据 + 基本验证）
│       ├── services/             # 服务层（业务逻辑编排）
│       ├── engines/              # 引擎层（核心算法，可替换）
│       │   ├── ai/               #   AI 引擎（deterministic/ollama/cloud）
│       │   ├── generator/        #   代码生成引擎（field/listing/permission...）
│       │   ├── delivery/         #   交付引擎（package_export/direct_install）
│       │   └── document/         #   文档生成引擎（deploy/readme/checklist）
│       ├── infrastructure/       # 基础设施层（config/audit/log/runner）
│       ├── schemas/              # JSON Schema 验证
│       └── shared/               # 共享工具（errors/result/logger）
│
├── templates/                    # 代码生成与文档模板（非开发人员可改）
│   ├── addon/                    #   Addon 固定骨架模板（.tmpl）
│   └── document/                 #   部署文档模板（.tmpl）
│
├── tests/                        # 测试（unit/integration/e2e）
│
├── output/                       # 生成产物（gitignore，volume 挂载）
│   ├── projects/                 #   生成的 Addon 项目源码
│   └── evidence_packs/           #   证据包
│
├── data/                         # 运行时数据（gitignore，volume 挂载）
│   ├── config.json               #   全局配置
│   ├── audit.db                  #   SQLite 操作记录
│   ├── logs/                     #   JSONL 运行日志
│   ├── companies/                #   公司配置
│   └── sites/                    #   站点配置 + Inventory 快照
│
├── Dockerfile                    # 多阶段构建（前端 build → 后端 serve）
├── docker-compose.yml            # 一键启动
├── .gitignore
└── README.md
```

## 分层依赖规则

| 层 | 允许依赖 |
|------|----------|
| `domain/` | 不依赖任何其他模块（纯净领域模型） |
| `engines/` | 仅 `domain/` + `shared/` |
| `services/` | `domain/` + `engines/` + `infrastructure/`（依赖注入） |
| `web` | 仅 `services/`（依赖注入） |
| `shared/` | 被任何模块使用 |

## 设计约束

- **后端零第三方运行时依赖**：仅使用 Python stdlib + `jsonschema`（离线/气隙环境要求）。
- **配置外部化**：所有可配置项存 JSON 文件，不硬编码。
- **命名空间规范**：通用包 `maitux.*`，客户定制包 `{公司简称}.*`。

## 预置 Senaite Addon 说明

工具运行所依赖的预置 Addon（如 `maitux.capabilityinventory` 能力扫描器、
`maitux.permissionsapply` 权限变更目标）位于 `../latest/addons/`，
随 Senaite Docker 环境一起构建，不在本工具源码树内维护。

---

> 详细设计见 `../docs/重构设计/` 下的三份文档：
> `00_项目理解与现状分析.md`、`01_面向用户的重构设计文档.md`、`02_技术设计文档.md`。
