# AI 智播课堂 — 数据库设计

版本：v1.1（第 5 轮）
数据库：PostgreSQL 16（Docker，开发/生产统一）
ORM：SQLAlchemy 2.x（async），迁移：Alembic

## 1. 职责划分

| 存储 | 负责内容 | 说明 |
|---|---|---|
| 业务表（Alembic 管理） | Agent 配置、会话、消息、任务、事件、工具日志、记忆索引、经验、反馈 | 可查询、可审计、前端数据来源 |
| LangGraph Checkpointer 表 | 图状态、任务中断恢复、checkpoint_writes/blobs | 由 `setup()` 创建，不手工改 |
| LangGraph Store 表 | 长期记忆文档（按 namespace 隔离） | 由 `setup()` 创建 |
| `agent_memories` 业务表 | 记忆元数据与内容快照（管理/删除/审计） | 与 Store 同步写入，不做二次检索 |

## 2. 业务表

### agents
| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | VARCHAR(32) | PK | alex / mia / ethan |
| name | VARCHAR(64) | NOT NULL | 显示名 |
| role | VARCHAR(32) | NOT NULL | teacher / assistant / student |
| avatar_url | VARCHAR(255) | NOT NULL | `/agents/alex.png` |
| theme_color | VARCHAR(16) | NOT NULL | 主题色 |
| short_description | VARCHAR(255) | NOT NULL | 一句话简介 |
| introduction | TEXT | | 详细介绍 |
| personality_tags | JSON | | 人格标签 |
| created_at / updated_at | DATETIME | | |

### agent_configs（1:1 agents）
| 字段 | 类型 | 说明 |
|---|---|---|
| agent_id | FK agents.id, PK | |
| system_prompt_path | VARCHAR(255) | prompts/alex.md |
| model_name | VARCHAR(64) | 默认 deepseek-chat |
| temperature | FLOAT | 0.3–0.8 按人格 |
| max_output_tokens | INT | 900/600/500 |
| max_context_tokens | INT | 默认 3000 |
| memory_namespace | VARCHAR(128) | agents/alex/memories |
| enabled | BOOL | 默认 true |

### agent_skills
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| agent_id | FK agents.id | |
| skill_name | VARCHAR(64) | concept_explanation 等 |
| description | TEXT | |
| input_schema | JSON | |
| output_schema | JSON | |
| enabled | BOOL | |
| UNIQUE(agent_id, skill_name) | | |

### agent_tool_permissions
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| agent_id | FK agents.id | |
| tool_name | VARCHAR(64) | calculator / datetime / python_sandbox |
| max_calls_per_task | INT | 默认 3 |
| enabled | BOOL | |
| UNIQUE(agent_id, tool_name) | | |

### conversations
| 字段 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) PK | UUID |
| title | VARCHAR(200) | 默认取首问前 30 字 |
| selected_agent_ids | JSON | 当前参与者（强制边界） |
| status | VARCHAR(16) | active / archived |
| created_at / updated_at | DATETIME | |

### conversation_participants
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| conversation_id | FK | |
| agent_id | FK | |
| joined_at | DATETIME | |
| UNIQUE(conversation_id, agent_id) | | 落库时校验 selected_agent_ids |

### messages
| 字段 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) PK | message_id |
| conversation_id | FK | |
| task_id | FK task_executions.id, nullable | 用户消息可无任务 |
| sender_type | VARCHAR(16) | user / agent / system |
| sender_agent_id | FK agents.id, nullable | |
| receiver_agent_id | FK agents.id, nullable | |
| message_type | VARCHAR(24) | message/question/response/challenge/request_help/handoff/conclusion |
| content | TEXT | Markdown |
| reply_to_message_id | VARCHAR(36), nullable | 引用关系 |
| metadata | JSON | 引用、工具摘要等 |
| created_at | DATETIME | 索引 (conversation_id, created_at) |

### task_executions
| 字段 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) PK | task_id |
| conversation_id | FK | |
| user_message_id | FK messages.id | |
| participating_agent_ids | JSON | 任务快照 |
| status | VARCHAR(16) | pending/running/completed/failed/stopped |
| turn_count | INT | |
| message_count | INT | |
| model_calls | INT | |
| prompt_tokens | INT | |
| completion_tokens | INT | |
| stop_reason | VARCHAR(64) | finish/budget/stopped/error |
| error | TEXT | |
| started_at / finished_at | DATETIME | |

### task_events
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | 作为 SSE event_id（单调递增） |
| event_type | VARCHAR(48) | 见架构文档 |
| conversation_id | FK | |
| task_id | FK, nullable | |
| agent_id | VARCHAR(32), nullable | |
| payload | JSON | 公开数据，无思维链 |
| created_at | DATETIME | 索引 (task_id, id) |

### tool_calls
| 字段 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) PK | |
| task_id | FK | |
| agent_id | FK | |
| tool_name | VARCHAR(64) | |
| arguments | JSON | 模型原始参数 |
| result | JSON | 结构化结果/错误 |
| status | VARCHAR(16) | success/failed/denied/timeout |
| error | TEXT | |
| duration_ms | INT | |
| prompt_tokens / completion_tokens | INT | 该次模型调用用量（如适用） |
| created_at | DATETIME | |

### agent_memories
| 字段 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) PK | 与 Store key 对应 |
| agent_id | FK | 隔离键 |
| memory_type | VARCHAR(24) | episodic/semantic/preference/relationship/candidate |
| content | TEXT | |
| source_conversation_id | FK, nullable | |
| confidence | FLOAT | 0–1 |
| status | VARCHAR(16) | active/invalidated/deleted |
| keywords | JSON | 检索用 |
| created_at / updated_at | DATETIME | 索引 (agent_id, memory_type, status) |

### agent_experiences
| 字段 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) PK | |
| agent_id | FK | |
| experience_type | VARCHAR(32) | task_result/tool_usage/user_feedback/collaboration/knowledge_correction |
| content | TEXT | 可复用的做法或判断，最长 300 字 |
| source_conversation_id | FK | |
| source_task_id | FK, nullable | |
| confidence | FLOAT | 0–1 |
| validation_status | VARCHAR(16) | candidate/validated/rejected |
| validation_note | TEXT, nullable | 验证或人工复核说明 |
| keywords | JSON | 经验关键词，用于相关度检索 |
| use_count | INT | 被注入后续任务的次数 |
| last_used_at | DATETIME, nullable | 最近一次注入时间 |
| created_at / updated_at | DATETIME | |

### user_feedback
| 字段 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) PK | |
| conversation_id | FK | |
| message_id | FK, nullable | |
| agent_id | FK, nullable | |
| rating | INT | -1 / 1 |
| comment | TEXT | |
| created_at | DATETIME | |

## 3. 关系

- conversations 1—N messages、1—N task_executions、1—N task_events。
- task_executions 1—N tool_calls、1—N messages。
- agents 1—1 agent_configs，1—N agent_skills / agent_tool_permissions / agent_memories / agent_experiences。
- messages.reply_to_message_id 自引用；messages.receiver_agent_id 指向 agents。

## 4. 索引与约束

- 唯一：agents.id、conversation_participants(conversation_id, agent_id)、agent_skills(agent_id, skill_name)、agent_tool_permissions(agent_id, tool_name)。
- 查询索引：messages(conversation_id, created_at)、task_events(task_id, id)、task_events(conversation_id, id)、agent_memories(agent_id, status, memory_type)、agent_experiences(agent_id, validation_status)。
- 外键：PostgreSQL 原生强制；SQLite 应急模式启用 `PRAGMA foreign_keys=ON`。
- JSON 字段：PostgreSQL 使用 JSONB；SQLite 应急模式以 TEXT 存储。

## 5. 与 LangGraph 的边界

- Checkpointer 的 thread_id = conversation_id，checkpoint_ns = task_id，避免不同任务互相覆盖。
- Store namespace：`agents/{agent_id}/memories/{memory_type}`，key = agent_memories.id。
- 业务表是前端与审计的唯一数据源；图状态只在恢复任务时读取，不直接暴露给前端。
- 删除记忆：先更新 agent_memories.status，再删除 Store 中对应 key，保证一致。
