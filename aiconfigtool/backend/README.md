# AiConfigTool 后端

零第三方运行时依赖（纯 Python 标准库），HTTP 用 stdlib `http.server` + 自定义路由。

## 运行

需要 Python 3.11+（本机用 `py` launcher 指向 3.12）。**在 `backend/` 目录下运行**，确保 `domain/services/...` 可被导入：

```bash
cd aiconfigtool/backend
py -m web.server --host 127.0.0.1 --port 8787
```

启动后：

```bash
curl http://127.0.0.1:8787/api/health
```

前端开发时 vite 已配好代理（`/api → 127.0.0.1:8787`），`npm run dev` 后直接访问
`http://localhost:5173`，页面的 `/api` 请求会转发到后端。

## 目录结构

```
backend/
├── web/                  HTTP 层
│   ├── server.py         入口：请求解析 → 路由 → Result → 统一响应
│   ├── router.py         极简路由（method + {param} 模板）
│   └── response.py       统一响应格式 {success,data,error,meta}
├── api/                  各资源 handler（返回 shared.Result）
│   ├── companies.py
│   ├── sites.py
│   └── inventory.py
├── infrastructure/
│   └── config_repository.py   读 data/ 下的 JSON 配置（camelCase，对齐前端）
├── shared/
│   ├── result.py         Result 模式
│   └── errors.py         错误码 + HTTP 状态映射
├── domain/  services/  engines/  schemas/   （骨架，待填业务逻辑）
```

## 当前已实现的端点（骨架期，只读）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/companies` | 公司列表 |
| GET | `/api/companies/{code}` | 单个公司 |
| GET | `/api/companies/{code}/sites` | 某公司的站点 |
| GET | `/api/sites/{code}` | 单个站点 |
| GET | `/api/sites/{code}/inventories` | 某站点的摸底文件 |
| GET | `/api/inventories?siteCode=` | 摸底文件（可按站点过滤） |

## 数据来源

读取工作空间目录（默认 `backend/../data`，可用环境变量 `AICONFIG_WORKSPACE` 覆盖）：

```
data/
├── companies/{code}/company.json
└── sites/{code}/
    ├── config.json
    └── inventories/{id}.json
```

这些是**真实的 JSON 配置文件**（非内存 mock），由 `ConfigRepository` 读取。
`data/` 按设计为运行时数据、随 volume 挂载（已 gitignore）。骨架期附带了少量种子数据用于验证；
后续写入能力（新增公司/站点、摸底产出）补齐后，这里会成为唯一数据源。

## 统一响应格式

成功：
```json
{ "success": true, "data": ..., "error": null, "meta": { "request_id": "...", "duration_ms": 0 } }
```

失败：
```json
{ "success": false, "data": null,
  "error": { "code": "NOT_FOUND", "message": "...", "details": {}, "suggestion": "..." },
  "meta": { ... } }
```

错误码与 HTTP 状态映射见 `shared/errors.py`。
