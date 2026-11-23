# AI 智播课堂

拟人化多智能体教学互动平台：Alex（教师）、Mia（助教）、Ethan（学生）三个独立 Agent 在同一课堂中真实讨论。

## 目录

```
multi-agent-classroom/
├─ frontend/                 React + TypeScript + Vite + Tailwind
├─ backend/                  FastAPI + SQLAlchemy + LangGraph
├─ docs/                     产品、架构、数据库、路线图、技术栈
└─ docker-compose.yml        PostgreSQL 16（开发/生产统一）
```

## 环境要求

- Python 3.11+（本机 3.14.0 实测通过）
- Node.js 18+（本机 24.11.1）
- Docker Desktop（本机已安装并启动，PostgreSQL 16 容器实测通过）
- Redis 7（仅多进程部署 SSE 时需要；`docker compose up -d redis`，本机实测通过）
- DeepSeek API Key（后端 `.env`）

## 后端启动

```powershell
# 1. 先启动数据库（Docker Desktop 需已运行）
cd multi-agent-classroom
docker compose up -d postgres

# 2. 启动后端
cd backend
Copy-Item .env.example .env   # 首次：填入 DEEPSEEK_API_KEY
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
.\.venv\Scripts\python.exe run_server.py
```

- 健康检查：http://127.0.0.1:8000/api/health
- 接口文档：http://127.0.0.1:8000/docs
- 模型能力探测：`.venv\Scripts\python.exe scripts\probe_model.py`

## 前端启动

```powershell
cd multi-agent-classroom\frontend
npm install
npm run dev
```

访问 http://localhost:5173 。开发服务器已将 `/api` 代理到后端 8000 端口。

前端为桌面优先的双栏课堂界面：顶部导航、左侧讨论舞台、右侧 Agent 面板、底部提问输入区；支持 1–3 个 Agent 选择/取消、Markdown 与 LaTeX 公式渲染、Enter 发送 / Shift+Enter 换行、停止生成与继续生成、对话历史、设置面板（真实系统信息）、移动端参与者抽屉与对话历史抽屉。

所有 Agent、对话、消息、任务、Token 与工具调用数据均来自真实后端接口；课堂页通过 SSE（`GET /api/conversations/{id}/events`）实时接收事件，断线自动重连并用 `Last-Event-ID` 补拉，任务终态后关闭连接，不再使用定时器轮询。

第 10 轮新增 Agent 经验系统：任务结束、工具成败、用户反馈与 Agent 协作会产生候选经验，经验经真实性/可复用性/重复/风险验证后才成为长期经验；后续任务只按相关度注入少量已验证经验，避免把全部历史塞进上下文。课堂顶部“经验库”可查看每个 Agent 的经验、验证状态、置信度与使用次数，助手消息支持点赞/点踩并附带改进说明。安全上，经验不能修改 System Prompt、工具权限、安全规则或其他 Agent 配置。

构建校验：

```powershell
cd multi-agent-classroom\frontend
npm run build
```

## PostgreSQL（Docker，默认数据库）

```powershell
docker compose up -d postgres
```

`backend/.env` 默认已指向：

```
postgresql+psycopg://classroom:classroom_dev_password@127.0.0.1:5432/ai_classroom
```

首次或模型变更后执行 `alembic upgrade head`。容器状态可用
`docker ps --filter name=ai-classroom-postgres` 查看；健康检查命令：

```powershell
docker exec ai-classroom-postgres pg_isready -U classroom -d ai_classroom
```

> 本机 Docker 引擎与 PostgreSQL 16 容器均已实测通过（容器 healthy，当前迁移版本 `c8d9e0f1a2b3`）。

## Redis（SSE 多进程广播，可选）

单进程开发默认使用进程内事件广播；部署多个后端 worker / 实例时，需要 Redis Pub/Sub 让任意实例产生的事件实时推送到所有 SSE 连接：

```powershell
docker compose up -d redis
docker exec ai-classroom-redis redis-cli ping
```

在所有后端实例的 `backend/.env` 中设置同一个地址（或启动前注入环境变量）：

```
REDIS_URL=redis://127.0.0.1:6379/0
EVENT_CHANNEL_PREFIX=classroom:sse:
```

启动多个实例示例（共用同一 PostgreSQL 与 Redis）：

```powershell
$env:REDIS_URL='redis://127.0.0.1:6379/0'
.\.venv\Scripts\python.exe run_server.py --port 8001
.\.venv\Scripts\python.exe run_server.py --port 8002
```

验证方式：`GET /api/health` 返回 `"events":"redis"`。任务在实例 A 执行、SSE 连接落在实例 B 时，事件仍可实时到达（数据库 `task_events` 负责补拉与去重）。未配置 `REDIS_URL` 时为 `"events":"memory"`；开发环境 Redis 连接失败会自动降级并打印 WARNING，`APP_ENV=production` 则启动失败。

## 测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

## 配置与安全

- 密钥只存在于 `backend/.env`，已被 `.gitignore` 排除。
- 前端只能拿到 `config-status` 的布尔能力信息，不会接触密钥。
- Token 预算参数见 `docs/TECH_STACK.md`。

## 文档

- [产品需求](docs/PRD.md)
- [技术架构](docs/ARCHITECTURE.md)
- [数据库设计](docs/DATABASE_DESIGN.md)
- [开发路线图](docs/DEVELOPMENT_ROADMAP.md)
- [技术栈与环境](docs/TECH_STACK.md)
