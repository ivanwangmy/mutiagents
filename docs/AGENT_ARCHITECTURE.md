# Agent 架构说明（本轮升级后）

本文描述当前代码真实运行的智能体架构，不包含未实现的规划项。技术栈保持
FastAPI + LangGraph + SQLAlchemy async + PostgreSQL，模型为 DeepSeek
OpenAI 兼容接口。

## 1. 分层结构

```
HTTP / SSE
  └── app/api/routes/*            对话、任务、事件、Agent、Skills/Tools 查询
        └── app/services/task_service.py   任务生命周期、单 Agent 流式入口
              └── app/agents/executor.py   AgentExecutor：消息组装、模型调用、工具循环
                    ├── app/agents/graph.py         单 Agent LangGraph 子图
                    ├── app/agents/discussion.py    多 Agent 动态调度父图
                    ├── app/skills/*                Skill 注册、匹配、执行
                    ├── app/tools/*                 Tool 注册、权限、执行、日志
                    ├── app/model/*                 模型适配层（complete / stream）
                    ├── app/memory/*                个体记忆与经验
                    └── app/events/broker.py        统一执行事件
```

Agent 人格与能力配置在 `app/agents/personas/*.yaml`，Prompt 在
`app/agents/prompts/*.md`，加载与校验由 `app/agents/registry.py` 负责。
三者通过 `AgentProfile` 合并，禁止在 Prompt 中硬编码工具执行逻辑。

## 2. 单 Agent 执行链

`AgentExecutor` 是唯一模型入口：

1. 读取当前 Agent 的长期记忆与经验（仅本人）。
2. `build_chat_messages()` 组装：
   - 人格 Prompt（含身份锚点、行为策略、任务决策清单）；
   - 本轮候选 Skill（`skills_registry.render_candidates()` 按问题检索）；
   - 记忆/经验块；
   - 最近历史消息与当前问题。
3. 读取权限工具集合（`ToolPermissionManager.tools_for()`），生成 OpenAI
   function schema。
4. `complete()` 或 `stream()` 调用模型。
5. 若返回原生 `tool_calls`：
   - 校验权限、调用次数与 JSON Schema；
   - 真实执行工具（calculator / datetime / python_sandbox / use_skill）；
   - 以 `role="tool"` 回填结果；
   - 再次调用模型，最多 `MAX_TOOL_ROUNDS = 4` 轮。
6. 最终内容写入 Message，任务状态置为 completed，并记录 token 与工具调用。

非流式路径由 `app/agents/graph.py` 的
`prepare_context → generate ↔ tools → finalize` 子图执行；流式路径由
`AgentExecutor.stream()` 直接完成同一闭环，两者共享权限、Schema 与工具执行器。

## 3. 多 Agent 执行链

`DiscussionManager` 构建 LangGraph 父图：

```
dispatch → agent_turn → (USE_TOOL → execute_tool → agent_turn)
                     → dispatch → ... → finalize
```

- `dispatch` 读取当前 `active_agent` 并进入对应 Agent 节点。
- `agent_turn` 调用模型输出 JSON 决策：
  `RESPOND / CHALLENGE / QUESTION / REQUEST_HELP / USE_TOOL / WAIT / FINISH`。
- 决策包含 `receiver`、`next_speaker`、`reply_to`；调度器只做合法性校验和
  参与度兜底，不替 Agent 生成观点。
- `USE_TOOL` 由后端真实执行工具，并把结果交给同一 Agent 二次生成。
- 未选择的 Agent 不在 `participants` 中，无法被路由或调用。
- 终止条件：FINISH、任务预算（token/调用/时长/消息数）、连续 WAIT 上限。

说明：多 Agent 路径使用 JSON 决策协议而非模型原生 function calling；
工具执行仍是真实后端函数，不是模型自述。该差异在
`AGENT_IMPROVEMENT_REPORT.md` 的未解决问题中列明。

## 4. 任务状态与预算

外部任务状态：`pending → running → completed / failed / stopped`。

模型内部执行阶段（Prompt 约束，不输出思维链）：

```
RECEIVED → ANALYZING → EXECUTING → WAITING → COMPLETED / FAILED
```

预算由 `app/core/config.py` 统一控制：

| 预算 | 默认值 |
| --- | --- |
| 单任务 token | 12000 |
| 模型调用次数 | 8 |
| 消息数 | 12 |
| 轮次 | 10 |
| 时长 | 120 秒 |
| 单次输出 token | 800 |
| 工具循环 | 4 轮 |

预算耗尽时 `stop_reason` 记录真实原因（如 `token_budget`），不会伪造完成。

## 5. 事件与可观测性

所有执行事件写入 `task_events` 并通过 `event_broker` 推送：

`agent_started`、`agent_status_changed`、`skill_selected`、`skill_loaded`、
`skill_completed`、`skill_failed`、`tool_call_started`、`tool_call_completed`、
`tool_call_failed`、`agent_message`、`agent_waiting`、`agent_completed`、
`agent_failed`、`task_completed`。

前端只消费真实后端事件；`Skill · xxx` 与工具卡片来自事件负载，不使用前端
定时器或假动画。事件不包含 API Key、密码或完整敏感参数。

## 6. 记忆边界

- 每个 Agent 独立 `memories` 与 `experiences`，查询强制带 `agent_id`。
- 只有 `status=active` 的记忆进入上下文；候选记忆不参与推理。
- 记忆提取不等于聊天原文入库，需经过类型、置信度与去重规则。
- Agent 不能修改自身人格 Prompt；人格只在部署时由 YAML/Markdown 加载。

## 7. 关键文件

| 职责 | 文件 |
| --- | --- |
| 人格与校验 | `backend/app/agents/config.py`、`registry.py` |
| 单 Agent 图 | `backend/app/agents/graph.py` |
| 模型入口 | `backend/app/agents/executor.py` |
| 多 Agent 调度 | `backend/app/agents/discussion.py` |
| 模型适配 | `backend/app/model/deepseek.py` |
| Skill 系统 | `backend/app/skills/registry.py`、`catalog.py` |
| Tool 系统 | `backend/app/tools/registry.py`、`executor.py`、`permissions.py` |
| 任务与事件 | `backend/app/services/task_service.py`、`events/broker.py` |
| 记忆 | `backend/app/memory/manager.py`、`experience.py` |
