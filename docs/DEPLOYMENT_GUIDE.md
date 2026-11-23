# AI 智播课堂 — 部署指南

本指南覆盖本地开发、单机演示与多进程生产部署。所有步骤均在本机 Windows 11 + Python 3.14 + Node 24 + Docker Desktop 环境实测通过。

## 1. 组件与端口

| 组件 | 技术 | 默认端口 | 说明 |
| --- | --- | --- | --- |
| 后端 | FastAPI + LangGraph | 8000 | 必须用 `run_server.py` 启动（Windows 事件循环兼容） |
| 前端 | React + Vite | 5173 | 开发服务器把 `/api` 代理到 8000 |
| PostgreSQL | 16（Docker） | 5432 | 业务数据 + LangGraph Checkpointer/Store |
| Redis | 7（Docker，可选） | 6379 | 仅在多 worker / 多实例时必须 |

## 2. 环境要求

- Python 3.11+（实测 3.14.0）
- Node.js 18+（实测 24.11.1）
- Docker Desktop（PostgreSQL、Redis）
- DeepSeek API Key

## 3. 本地启动（从零）

### 3.1 启动数据库

```powershell
cd d:\eduagents\multi-agent-classroom
docker compose up -d postgres
docker compose up -d redis     # 单进程演示可省略
docker ps --format "table {{.Names}}\t{{.Status}}"
```

预期：`ai-classroom-postgres` 与 `ai-classroom-redis` 均为 `healthy`。

### 3.2 后端

```powershell
cd backend
Copy-Item .env.example .env    # 首次：填入 DEEPSEEK_API_KEY
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
.\.venv\Scripts\python.exe run_server.py
```

验证：

```powershell
curl.exe -s http://127.0.0.1:8000/api/health
# {"status":"ok","database":"ok","events":"memory","model_configured":true,"version":"0.1.0"}
```

> 不要用 `uvicorn app.main:app` 直接启动。psycopg 3 异步模式不支持 Windows 默认 ProactorEventLoop，`run_server.py` 已显式切换到 `SelectorEventLoop`。

### 3.3 前端

```powershell
cd ..\frontend
npm install
npm run dev
```

打开 http://localhost:5173，确认能加载三位 Agent。

### 3.4 单元测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q
# 41 passed
```

## 4. 配置项（backend/.env）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `development` | `production` 时 Redis 连接失败会阻止启动 |
| `DATABASE_URL` | `postgresql+psycopg://classroom:classroom_dev_password@127.0.0.1:5432/ai_classroom` | 业务库 |
| `CHECKPOINTER_BACKEND` | `postgres` | LangGraph 短期状态后端 |
| `DEEPSEEK_API_KEY` | 空 | 必填；只存在后端 `.env` |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容地址 |
| `DEEPSEEK_MODEL` | `deepseek-flash` | 模型名 |
| `REDIS_URL` | 空 | 留空=进程内广播；多实例必须设置 |
| `EVENT_CHANNEL_PREFIX` | `classroom:sse:` | SSE Pub/Sub 频道前缀 |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 逗号分隔，禁止生产使用 `*` |
| `MAX_OUTPUT_TOKENS` | 800 | 单次输出上限 |
| `MAX_CONTEXT_TOKENS` | 3000 | 上下文估算上限 |
| `TASK_TOKEN_BUDGET` | 12000 | 单任务 Token 预算 |
| `TASK_MAX_MODEL_CALLS` | 8 | 单任务模型调用上限 |
| `TASK_MAX_MESSAGES` | 12 | 单任务消息上限 |
| `TASK_MAX_TURNS` | 10 | 单任务轮次上限 |
| `TASK_MAX_SECONDS` | 120 | 单任务时长上限 |

前端如需独立域名部署，可在构建时设置 `VITE_API_BASE=https://api.example.com`；同域部署留空即可。

## 5. 多进程 / 多实例部署（Redis）

### 5.1 启动 Redis 与多个后端实例

```powershell
cd d:\eduagents\multi-agent-classroom
docker compose up -d redis
docker exec ai-classroom-redis redis-cli ping   # PONG

cd backend
$env:REDIS_URL='redis://127.0.0.1:6379/0'
$env:APP_ENV='production'
.\.venv\Scripts\python.exe run_server.py --port 8001
.\.venv\Scripts\python.exe run_server.py --port 8002
```

### 5.2 验证

```powershell
curl.exe -s http://127.0.0.1:8001/api/health
# "events":"redis"
```

本轮实测：以 `REDIS_URL` 启动的 8001 实例返回 `{"database":"ok","events":"redis","model_configured":true}`，日志显示 `事件广播后端：redis`。

### 5.3 一致性说明

- 事件先写入 `task_events`（数据库为唯一事实来源），再通过 Redis Pub/Sub 扇出。
- 任一端产生事件，所有订阅同一频道的实例都能实时推送给 SSE 连接。
- Redis 至多一次投递，即使丢消息，客户端重连时也会按 `Last-Event-ID` 从数据库补拉并去重。

## 6. 生产部署建议

1. **进程管理**：使用 NSSM / systemd / 容器编排守护 `run_server.py`；多个 worker 必须共用同一 PostgreSQL 与 Redis。
2. **反向代理**：Nginx 统一入口，静态文件指向 `frontend/dist`，`/api` 反代到后端；为 SSE 关闭代理缓冲（`proxy_buffering off;`）并延长读超时。
3. **HTTPS**：必须启用 TLS，避免消息与反馈明文传输。
4. **鉴权**：当前版本无登录，公网部署前必须在网关或应用层增加身份认证与资源级授权。
5. **限流**：在网关按 IP/会话限制请求频率，防止模型调用被滥用。
6. **数据库**：开启定期备份；生产使用独立强密码，不使用示例密码。
7. **日志**：保留后端访问日志与任务事件，禁止把 `.env` 或密钥写入日志。
8. **资源隔离**：如需对公网用户开放 Python 沙箱，改用容器级隔离。

## 7. 数据备份与恢复

```powershell
# 备份
docker exec ai-classroom-postgres pg_dump -U classroom -d ai_classroom -F c -f /tmp/ai_classroom.dump
docker cp ai-classroom-postgres:/tmp/ai_classroom.dump .\ai_classroom.dump

# 恢复
docker cp .\ai_classroom.dump ai-classroom-postgres:/tmp/ai_classroom.dump
docker exec ai-classroom-postgres pg_restore -U classroom -d ai_classroom --clean --if-exists /tmp/ai_classroom.dump
```

## 8. 升级流程

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
alembic upgrade head
.\.venv\Scripts\python.exe -m pytest tests -q

cd ..\frontend
npm ci
npm run build       # 产物在 frontend/dist
```

修改模型或 Prompt 后，重启后端即可；经验与长期记忆存储在数据库中，不受重启影响。

## 9. 验收检查清单

| 步骤 | 命令 / 操作 | 预期 |
| --- | --- | --- |
| 数据库健康 | `docker ps` | postgres、redis 均 healthy |
| 迁移版本 | `select version_num from alembic_version;` | `c8d9e0f1a2b3` |
| 后端健康 | `GET /api/health` | `status=ok`、`model_configured=true` |
| 事件后端 | `GET /api/health` | 单进程 `memory`；多实例 `redis` |
| Agent 列表 | `GET /api/agents` | 返回 alex / mia / ethan |
| 真实问答 | 前端发送"The 0.999… 为什么等于 1" | 数秒内自动出现回答 |
| 工具 | 让 Alex 用计算器算 12345×6789 | 返回 83810205 |
| SSE | 浏览器 Network | 存在 `/events` 请求，无轮询风暴 |
| 单元测试 | `pytest tests -q` | 41 passed |
| 前端构建 | `npm run build` | 成功，dist 含 agents 头像与 KaTeX 字体 |

## 10. 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `ProactorEventLoop` / psycopg 报错 | 用 uvicorn 直接启动 | 改用 `python run_server.py` |
| `/api/health` 数据库不是 ok | PostgreSQL 未启动或 DATABASE_URL 错误 | `docker compose up -d postgres`，检查 `.env` |
| `events` 一直是 `memory` | 未设置 `REDIS_URL` | 设置后重启后端；确认 Redis healthy |
| 生产环境启动失败并提示 Redis | `APP_ENV=production` 且 Redis 不可用 | 先启动 Redis，或改回 development 做单进程演示 |
| 前端请求 404 | Vite 代理或 Nginx `/api` 配置错误 | 开发用 `npm run dev`；生产反代到后端 8000 |
| 浏览器 CORS 报错 | 前端域名不在 `CORS_ORIGINS` | 加入实际域名，禁止使用 `*` |
| 任务很快 `token_budget` 结束 | 多 Agent 上下文累计触达 12k | 缩短问题、要求"每人一句话"，或调高预算 |
| 页面显示连接失败 | 后端未启动或端口不一致 | 检查 8000 端口与 `/api/health` |
| 端口被占用 | 已有实例在运行 | `Get-NetTCPConnection -LocalPort 8000` 查找并停止 |

## 11. 本轮部署验证记录

- PostgreSQL 16：healthy，迁移 `c8d9e0f1a2b3`。
- Redis 7：healthy；`REDIS_URL` 实例 `/api/health` 返回 `events:"redis"`。
- 后端 8000：`events:"memory"`，真实模型可用。
- 前端 5173：SSE 实时更新、KaTeX 公式、Markdown、停止生成、刷新恢复均实测通过。
- 后端单元测试 41 passed；前端构建成功，lint 0 errors。
