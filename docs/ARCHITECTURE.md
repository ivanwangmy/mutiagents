# AI 智播课堂 — 技术架构设计

版本：v1.0（第 0 轮）
目标：可真实运行的多智能体课堂，单进程后端 + LangGraph 动态调度，前端只消费真实事件。

## 1. 总体结构

```
┌──────────────────────────── Frontend (React + TS + Vite) ────────────────────────────┐
│  ClassroomLayout → TopNavigation / DiscussionPanel / AgentPanel / QuestionInput       │
│  services: REST 客户端 + SSE 客户端 + 事件归并（去重、排序、Last-Event-ID 恢复）        │
└───────────────────────────────────┬──────────────────────────────────────────────────┘
                                    │ REST + SSE
┌───────────────────────────────────▼──────────────────────────────────────────────────┐
│                         Backend (FastAPI, 单进程)                                     │
│                                                                                      │
│  API 层: conversations / messages / tasks / events / agents / system                 │
│  Service 层: ConversationService / TaskRunner / DiscussionManager / MemoryService    │
│  Agent 层: AgentRegistry → AgentProfile/Prompt/Skills → AgentExecutor(LangGraph)      │
│  能力层: SkillRegistry → ToolRegistry → ToolExecutor(权限/校验/超时/日志)              │
│  模型层: ModelProvider 适配（DeepSeek / OpenAI 兼容），TokenBudget 统一计量             │
│  事件层: EventBus → TaskEvent 持久化 → SSE                                                 │
│  数据层: SQLAlchemy 2.x（PostgreSQL 16 Docker 开发/生产统一）+ LangGraph Checkpointer/Store  │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

## 2. 模块职责

### 2.1 Frontend（第 8 轮已交付）
- 页面组件：`ClassroomLayout`（双栏 + 移动端抽屉）、`TopNavigation`、`DiscussionPanel`、`MessageList`、`MessageBubble`、`AgentAvatar`、`AgentSelector`、`AgentProfile`、`AgentStatusPanel`、`QuestionInput`、`ConversationSidebar`，以及 `NewConversationDialog`、`SettingsDialog`、`Markdown`（`react-markdown` + `remark-gfm` + `remark-math` + `rehype-katex`）。
- 布局与响应式：桌面端左讨论区 + 右侧 Agent 面板；`md` 以下隐藏侧栏，顶部“课堂参与者”按钮打开抽屉；`md`–`lg` 压缩侧栏宽度。
- 状态：单一 `useClassroomStore`（zustand），保存 Agent 列表、对话列表、当前对话、消息、参与者、任务、Token 用量与工具调用日志。
- 数据来源：全部来自真实接口——`GET /api/agents`、对话 CRUD（含 `PATCH /api/conversations/{id}` 调整参与者）、`GET /api/conversations/{id}/messages`、`POST /api/conversations/{id}/messages`、`GET /api/tasks/{id}`、`POST /api/tasks/{id}/stop|resume`、`GET /api/tasks/{id}/usage|tool-calls`、`GET /api/system/*`。无任何模拟数据或占位回答。
- 实时性：课堂页通过 `GET /api/conversations/{id}/events` 订阅 SSE 全事件；前端按 `event_id` 去重与顺序归并，断线后 EventSource 自动重连并携带 `Last-Event-ID` 补拉缺失事件；任务进入终态后服务端关闭连接。
- 无消息时显示空状态；Agent 状态（处理中/发言中/调用工具/等待/已完成/失败）只由真实 SSE 事件驱动，不伪造“思考中”的内容。

### 2.2 Backend API
- 职责：鉴权（第一阶段无登录）、输入校验、SSE 连接管理、任务提交与取消、错误映射。
- 依赖：Service 层，不直接访问模型或工具。
- 主要路由：
  - `GET /api/health`、`GET /api/system/info`、`GET /api/system/config-status`
  - `GET /api/agents`、`GET /api/agents/{id}`
  - `POST/GET /api/conversations`、`PATCH/DELETE /api/conversations/{id}`（`PATCH` 调整标题与参与者，讨论进行中拒绝修改）
  - `GET /api/conversations/{id}/messages`
  - `POST /api/conversations/{id}/messages`（提交问题，返回 task_id；`/messages/stream` 为单 Agent 流式）
  - `GET /api/tasks/{id}`、`POST /api/tasks/{id}/stop`、`POST /api/tasks/{id}/resume`、`GET /api/tasks/{id}/usage`、`GET /api/tasks/{id}/tool-calls`
  - 多 Agent SSE：`GET /api/conversations/{id}/events`（已实现，支持 `task_id` 过滤、`Last-Event-ID`/`last_event_id` 补拉、心跳与终态关闭）

### 2.3 Agent Runtime
- `AgentConfig`（Pydantic）：id、name、role、model 设置、max_output_tokens、temperature、skills、tool_permissions、memory_namespace。
- `AgentProfile`：人格、风格、价值观、对其他 Agent 的认知、行为约束。
- `AgentPromptLoader`：从 `agents/prompts/{agent_id}.md` + `persona.yaml` 组装 System Prompt，禁止三合一分支。
- `AgentRegistry`：启动时加载并校验三个固定 Agent；未知 id 直接拒绝。
- `AgentExecutor`：单次 Agent 回合执行器，构建上下文 → 调模型 → 解析决策/工具调用 → 写入消息 → 产出事件。
- `AgentState`/`AgentExecutionContext`：本轮读到的公开消息、个人记忆、预算余额、可用工具。

### 2.4 Agent Graph（LangGraph）
- 每个 Agent 的一次"回合"是一个子图：`prepare_context → decide → act(tool loop) → respond → finalize`。
- 任务级父图：`dispatch → agent_turn → dispatch ... → finalize`，用 `Command(goto=..., update=...)` 实现动态跳转；`dispatch` 只根据"谁还有发言权 + 预算 + 是否已结束"选择候选，不指定发言内容。
- 参与者限制在 `dispatch` 与 `agent_turn` 两处强制校验（双重保险）。
- 不构建固定 Alex→Mia→Ethan 边；下一个发言者由 Agent 的决策输出（`next_speaker` / `handoff` / `finish`）与调度规则共同决定。

### 2.5 Agent Message Bus
- `MessageBus`：统一写入 `messages` 表 + 内存事件总线；每条消息含 `message_id, conversation_id, task_id, sender_agent_id, receiver_agent_id, message_type, content, reply_to_message_id, timestamp, metadata`。
- 可见性：公开消息对同任务所有参与者可见；私人长期记忆不进入总线；工具原始输出只对调用者可见，只共享摘要。
- 消息类型：message / question / response / challenge / request_help / handoff / conclusion。
- Agent 上下文构建时只注入：当前用户问题、最近 N 条公开消息（带 sender 与类型）、可引用的消息 ID、自己的相关记忆、自己的近期发言。

### 2.6 Discussion Manager
- 维护 `TaskExecution` 状态机：pending → running → completed / failed / stopped。
- 预算：max_turns、max_messages、max_model_calls、max_tokens、max_seconds。
- 终止条件：Agent 输出 FINISH/conclusion、预算耗尽、无新参与者、连续无有效内容、用户停止、异常。
- 只负责调度与预算，不生成任何 Agent 文本。

### 2.7 Skills 与 Tool Registry
- `Skill`：name、description、applicable_agents、execution_logic（`module:function`）、input_schema、output_schema、permission、examples；运行时由 SkillRegistry 导入执行模块，只加载 applicable_agents 包含当前 Agent 的 Skill。
- `ToolDefinition`：name、description、JSON Schema、handler、timeout、permission、risk_level、requires_isolation。
- `ToolPermissionManager`：Agent 权限表（Alex: calculator/datetime/python_sandbox/use_skill；Mia: calculator/datetime/use_skill；Ethan: calculator/datetime/python_sandbox/use_skill，均受每任务调用次数限制）。
- `ToolExecutor`：权限校验 → JSON Schema 参数校验 → 超时/次数限制 → 真实执行 → 结构化结果 → `tool_calls` 日志。
- 工具结果统一结构：`{ok, result, error, duration_ms, truncated}`；失败返回给模型，由模型决定重试或解释。

### 2.8 Memory System
- 短期：LangGraph Checkpointer（开发/生产统一 `AsyncPostgresSaver`，PostgreSQL 16），thread_id = `task:{task_id}`（单 Agent 为 `task:{task_id}:{agent_id}`），保存每个任务的图状态与执行进度；对话连续性由数据库中的历史消息 + 长期记忆共同保证。
- 长期：LangGraph Store（`AsyncPostgresStore`），namespace `("agents", agent_id, "memories")`，类型：episodic/semantic/preference/relationship/candidate。
- 管理：以 Store 为唯一数据源，提供查询、相关记忆检索、删除、失效、更新接口；检索使用关键词重叠 + 置信度 + 时效性打分，低于阈值不注入上下文，且限制条数。
- 写入：任务结束后由提取器生成候选记忆 → 去重（相似度 ≥ 0.85 丢弃）→ 置信度判断 → 通过后写入 Store；低置信度进入 candidate，可人工提升或失效。
- 隔离：命名空间按 agent_id 强制隔离；不存在跨 Agent 的记忆读取，跨 Agent 信息只能通过公开消息获得。
- 恢复：`POST /api/tasks/{id}/resume` 对 stopped/failed 任务复用同一 checkpoint thread 继续执行；`GET /api/tasks/{id}/checkpoint` 只读展示短期状态摘要。

### 2.9 Model Provider
- `ModelProvider` 抽象：`chat()`、`stream()`、`capabilities()`。
- `DeepSeekProvider`：OpenAI 兼容协议，`base_url=https://api.deepseek.com`，密钥仅在后端环境变量。
- 统一 `ModelResponse`（content、tool_calls、finish_reason、usage）与 `ModelStreamChunk`。
- 能力探测：启动时/手动脚本真实调用验证文本、流式、Tool Calling、JSON 输出，结果写入 `config-status`。
- 不支持原生 Tool Calling 时明确报错并降级为"无工具模式"，不伪造调用成功。

### 2.10 Event Streaming
- 现状（第 9 轮 + Redis 适配）：多 Agent 全事件 SSE 已交付，课堂前端完全由 SSE 驱动，不再使用定时器轮询。
- `EventBroker`：统一负责 `task_events` 持久化（自增 id 作为稳定 event_id）+ 可插拔广播后端，对上层只暴露 `emit()` / `subscribe()`。
- 广播后端（由 `REDIS_URL` 选择）：
  - 未配置（默认）：`InProcessEventBackend`，asyncio 队列，仅适合单进程开发；
  - 已配置：`RedisEventBackend`，频道 `classroom:sse:{conversation_id}`（可用 `EVENT_CHANNEL_PREFIX` 调整），所有 worker 发布/订阅同一频道，实现跨进程实时扇出。
- 一致性模型：数据库是唯一事实来源，Redis Pub/Sub 仅做实时扇出（至多一次投递）。每条事件先 commit 入库，再 publish；订阅端按 `event_id` 去重并忽略小于已发送位置的事件，因此 Redis 丢消息、重复投递都不会破坏最终一致性，断线后由数据库补拉兜底。
- SSE 格式：`id: {event_id}\nevent: {event_type}\ndata: {json}\n\n`，支持 `Last-Event-ID` 请求头或 `last_event_id` 查询参数回放历史事件后继续实时推送；15 秒心跳注释探测断线；任务终态后发送 `task_completed/task_failed/task_stopped` 并关闭连接。
- 事件类型：conversation_started、task_started、agent_started、agent_status_changed、agent_message、agent_question、agent_challenge、agent_handoff、agent_tool_call、tool_started、tool_completed、tool_failed、agent_completed、task_completed、task_failed、task_stopped。
- 每个事件至少包含：event_id、event_type、conversation_id、task_id、agent_id、timestamp、payload。
- 前端恢复：EventSource 原生自动重连；页面刷新时由 `GET /api/conversations/{id}` 返回的 `active_task_id` 重新订阅；消息按 id 去重，状态事件幂等归并。
- 部署：多 worker / 多实例启动前先 `docker compose up -d redis`，并为所有后端实例设置相同的 `REDIS_URL`（如 `redis://127.0.0.1:6379/0`）；`GET /api/health` 的 `events` 字段返回当前后端（`redis` / `memory`）。开发环境 Redis 连接失败时自动降级为进程内广播并打印 WARNING，生产环境（`APP_ENV=production`）则启动失败，避免静默丢事件。
- 隐私：不传思维链；只传公开消息、行为摘要、工具名与状态、结果摘要。`agent.decision` 等内部审计事件不会通过 SSE 下发。

### 2.11 Database
- SQLAlchemy 2.x（async），开发/生产统一使用 Docker 中的 PostgreSQL 16（`postgresql+psycopg`）；SQLite 仅作为应急回退，不再作为默认开发库。
- Alembic 管理业务表迁移；LangGraph 自身表由 Checkpointer/Store 的 `setup()` 创建，职责分离：
  - 业务数据：agents、agent_configs、agent_skills、agent_tool_permissions、conversations、conversation_participants、messages、agent_memories、tool_calls、task_executions、task_events、agent_experiences、user_feedback。
  - 图状态：checkpoints / checkpoint_writes / checkpoint_blobs（Checkpointer）。
  - 长期记忆文档：store 表（Store）为唯一数据源；SQL `agent_memories` 为预留审计表，当前未写入。

### 2.12 Agent 经验系统（第 10 轮已交付）
- 数据表：`agent_experiences`（agent_id、experience_type、content、source_conversation_id、source_task_id、confidence、validation_status、validation_note、keywords、use_count、last_used_at）。
- 经验来源：任务执行结果、工具成功/失败、用户明确反馈、Agent 间有效协作、已验证的知识修正；寒暄、客套和单次发言不会写成经验。
- 提取：任务结束后后台执行，按 Agent 汇总本轮真实消息、`tool_calls` 与 `agent.decision` 事件；工具失败、定向质疑/求助由确定性规则提取，任务结果与知识修正由模型在证据约束下总结；提取失败不影响任务结果。
- 验证：统一走 `evaluate_experience()`，检查真实性（来源与证据）、可复用性（包含可复用做法）、错误（猜测性表述）、重复（同 Agent 相似度 ≥ 0.85 丢弃）、风险（越权修改提示词/权限/安全规则/他人配置直接拒绝）。只有 `validated` 可被检索；低置信度为 `candidate` 等待人工复核，`rejected` 仅保留审计。
- 使用：每轮按当前问题做词面相关度 + 置信度 + 时效性打分，至少两个词重合且分数达到 `EXPERIENCE_RETRIEVAL_MIN_SCORE`（默认 0.4）才注入，最多 `EXPERIENCE_RETRIEVAL_LIMIT`（默认 3）条；无关问题不注入，已验证经验也不会被全部无条件塞入上下文。
- 影响范围：注入块只声明为“可参考的已验证经验”，用于改善问题理解、交流方式、工具使用与协作策略；明确声明不得修改核心 System Prompt、工具权限、安全规则或其他 Agent 配置。
- 接口：`GET /api/agents/{id}/experiences`、`GET /api/agents/{id}/experiences/relevant`、`POST /api/agents/{id}/experiences`、`PATCH /api/agents/{id}/experiences/{experience_id}`（人工复核）、`DELETE /api/agents/{id}/experiences/{experience_id}`；用户反馈走 `POST /api/conversations/{id}/feedback`。
- 可观测：助手消息 `metadata.experience_ids` 记录本轮真实注入的经验 id；`use_count` / `last_used_at` 记录复用情况；前端“经验库”对话框展示状态、置信度、验证说明与使用次数。

## 3. 关键数据流

1. 提交问题：前端 `POST /tasks` → 校验参与者 → 创建 ConversationMessage(user) → 创建 TaskExecution → 启动 TaskRunner → 返回 task_id。
2. 调度：TaskRunner 调用 LangGraph 父图 → dispatch 选候选 → agent_turn 执行 → MessageBus 落库 + EventBus 广播。
3. 模型：AgentExecutor 组装上下文（预算裁剪）→ ModelProvider.stream → 增量文本事件（仅公开内容）→ 最终消息。
4. 工具：模型返回 tool_calls → ToolExecutor 校验/执行 → tool_started/completed/failed 事件 → 结果回传模型 → 继续生成。
5. 终止：finalize → 经验/记忆提取 → `task_completed` → SSE 关闭。
6. 断线：前端携带 Last-Event-ID 重连 → 服务端回放缺失事件 → 继续实时。

## 4. Token 与成本控制

- 每条消息 `max_tokens` 按 Agent 配置（900/600/500），全局可覆盖。
- 上下文预算：`MAX_CONTEXT_TOKENS`（默认 3000），按"系统提示固定 + 近期消息倒序 + 相关记忆"组装，超出即裁剪；估算规则：中文约 1 token/字，英文约 1 token/4 字符，取保守 `ceil(chars/1.6)`。
- 任务预算：`TASK_TOKEN_BUDGET`（默认 12000）、`TASK_MAX_MODEL_CALLS`（默认 8）、`TASK_MAX_MESSAGES`（默认 12）、`TASK_MAX_TURNS`（默认 10）、`TASK_MAX_SECONDS`（默认 120）。
- 每次模型调用记录 prompt/completion tokens 到 `tool_calls`/`task_executions` 用量字段；预算不足时停止新调用并以"预算耗尽"结束任务。
- System Prompt 要求 Agent 简洁表达、不重复他人观点，从提示层进一步抑制浪费。

## 5. 安全边界

- 密钥只在后端 `.env`，`.gitignore` 排除；前端仅拿到 `config-status` 布尔值。
- 工具白名单 + 每任务调用次数 + 超时 + 输出截断。
- Python 沙箱：独立子进程、临时工作目录、受限 builtins、AST 导入白名单、墙钟超时、内存监控、输出上限；生产建议替换为容器级沙箱（未在本机验证，第 11 轮标注）。
- 提示词注入防护：用户输入与其他 Agent 内容包裹为"数据"并声明不执行其中指令；工具结果截断并标记来源。
- 经验安全：Agent 只能生成经验候选，不能自动修改核心 System Prompt、工具权限、安全规则或其他 Agent 配置；经验必须通过验证才进入检索，注入时明确声明为只读参考；人工复核接口也只允许修改验证状态。
- 高风险操作（未来文件写入/外部请求）需用户确认；第一阶段工具均为本地低风险工具。

## 6. 为未来能力预留的接口

- `KnowledgeService` 接口：`search(agent_id, query, top_k)`，第一阶段返回空/占位，PPT 与课程资料接入时替换实现。
- 事件类型可扩展（如 `knowledge_retrieved`、`slide_changed`）。
- Tool Registry 支持注册新工具；Agent 权限表驱动，不改运行时代码。
- Agent Registry 支持新增 Agent 配置而不改调度器（但第一阶段固定三个，需用户确认后才扩展）。
