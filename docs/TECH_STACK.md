# AI 智播课堂 — 技术栈与环境

版本：v1.1（第 5 轮，PostgreSQL 已启用）

## 1. 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 前端 | React 18 + TypeScript + Vite | SPA，桌面优先 |
| 样式 | Tailwind CSS + shadcn/ui 风格组件 | 低饱和紫色强调，白/浅灰底 |
| Markdown/公式 | react-markdown + remark-gfm + remark-math + rehype-katex | 消息渲染 |
| 前端状态 | Zustand | 对话、Agent 运行时状态、SSE 连接 |
| 后端 | Python 3.11+、FastAPI、Pydantic v2 | 本机实际 Python 3.14.0 |
| ORM/迁移 | SQLAlchemy 2.x（async）+ Alembic | |
| 多 Agent | LangGraph（StateGraph + Command 动态调度） | 先核对版本 API |
| 模型 | DeepSeek（OpenAI 兼容协议） | `DEEPSEEK_API_KEY` 环境变量 |
| 短期记忆 | LangGraph Checkpointer（PostgreSQL） | thread_id=conversation_id |
| 长期记忆 | LangGraph Store（PostgreSQL） | namespace 按 Agent 隔离 |
| 实时 | SSE（sse-starlette 或原生 StreamingResponse） | REST 负责操作，SSE 负责推送 |
| 数据库 | PostgreSQL 16（Docker，开发/生产统一） | 已通过 docker compose 实际运行 |
| 部署 | Docker Compose | `ai-classroom-postgres` 容器已启动 |
| 测试 | pytest + pytest-asyncio + 真实接口脚本 | 关键路径必须有证据 |

## 2. 本机环境检查结果（第 5 轮复测）

| 项目 | 结果 |
|---|---|
| Python | 3.14.0 ✅（满足 3.11+） |
| Node.js | v24.11.1 ✅ |
| npm | 11.6.2 ✅ |
| Git | 2.51.2 ✅ |
| Docker | 29.9.3 ✅（Docker Desktop 引擎已就绪） |
| PostgreSQL | 16-alpine ✅（容器 `ai-classroom-postgres`，健康检查通过，端口 5432） |

数据库连接：`postgresql+psycopg://classroom:classroom_dev_password@127.0.0.1:5432/ai_classroom`

## 3. 模型接入约定

- 供应商：DeepSeek 官方 API（`https://api.deepseek.com`，OpenAI 兼容）。
- 环境变量：
  - `DEEPSEEK_API_KEY`（后端 `.env`，禁止提交）
  - `DEEPSEEK_BASE_URL`（默认 https://api.deepseek.com）
  - `DEEPSEEK_MODEL`（默认 `deepseek-flash`；账号实际模型以 `/models` 返回为准）
- 能力必须实测：文本、流式、原生 Tool Calling、JSON 结构化输出。探测脚本输出写入 `GET /api/system/config-status`。
- 不支持的能力明确标注，不伪造。

## 4. Token 控制默认参数

| 参数 | 默认值 | 作用 |
|---|---|---|
| `MAX_OUTPUT_TOKENS` | 800 | 全局单条输出上限（Agent 可覆盖） |
| `MAX_CONTEXT_TOKENS` | 3000 | 单次请求上下文预算 |
| `TASK_TOKEN_BUDGET` | 12000 | 单任务总 Token 预算（多 Agent 讨论按参与者数放宽） |
| `TASK_MAX_MODEL_CALLS` | 8 | 单任务模型调用上限 |
| `TASK_MAX_MESSAGES` | 12 | 单任务 Agent 消息上限 |
| `TASK_MAX_TURNS` | 10 | 单任务调度轮次上限 |
| `TASK_MAX_SECONDS` | 120 | 单任务墙钟上限 |

## 5. 启动方式（已实测）

> Windows 上 psycopg 3 异步模式不支持默认的 ProactorEventLoop，必须通过
> `run_server.py` 启动（内部使用 `SelectorEventLoop`）。直接执行
> `uvicorn app.main:app` 会在连接 PostgreSQL 时报错。

```powershell
# 1. 数据库（Docker Desktop 需已启动）
cd multi-agent-classroom
docker compose up -d postgres

# 2. 后端
cd backend
.\.venv\Scripts\Activate.ps1
alembic upgrade head
.\.venv\Scripts\python.exe run_server.py

# 3. 前端
cd ..\frontend
npm install
npm run dev
```

## 6. 风险与对策

| 风险 | 对策 |
|---|---|
| Python 3.14 部分包无 wheel | 第 1 轮实测安装；失败则降级到可用版本或改用 3.12 |
| Docker 引擎未启动 | 先启动 Docker Desktop；`docker compose up -d postgres` 后检查容器 healthy |
| PostgreSQL 迁移失败 | 确认 5432 端口未被占用，`alembic upgrade head` 查看首个错误；SQLite 仅作应急回退 |
| DeepSeek 模型名不确定 | 启动探测 `/models`，以实际返回为准 |
| LangGraph API 版本差异 | 固定版本并在第 4/6 轮核对实际签名 |
| Python 沙箱非容器级 | 子进程 + AST 白名单 + 超时 + 资源限制；报告中标注残余风险 |
