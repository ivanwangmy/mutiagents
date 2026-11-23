# Agent 能力升级报告

本轮基于 `docs/AGENT_CAPABILITY_AUDIT.md` 的真实问题做定向修复，没有更换技术栈、
没有新增第四个 Agent、没有重写稳定模块。所有验收结论来自运行中的后端与真实
DeepSeek 模型，不使用模拟工具或硬编码答案。

## 1. 修改文件清单

### 后端

| 文件 | 变更 |
| --- | --- |
| `app/agents/config.py` | SkillSpec 增加 id/version/category/trigger_conditions/execution_steps/error_handling/limitations/enabled；新增 BehaviorSpec |
| `app/agents/registry.py` | Prompt 注入行为策略、任务决策清单、Skill 必填参数 |
| `app/agents/executor.py` | 候选 Skill 注入；流式原生 Tool Calling 闭环；Skill 事件 |
| `app/agents/graph.py` | 工具调用传 call_id；skill_selected/loaded/completed/failed 事件 |
| `app/agents/discussion.py` | 候选 Skill 注入；决策新增 next_speaker；行为动作规范；Skill 事件 |
| `app/agents/personas/*.yaml` | 三个 Agent 的 behavior 策略；use_skill 配额 3 |
| `app/model/base.py` | ModelStreamChunk 支持 tool_calls / meta；stream 支持 tools |
| `app/model/deepseek.py` | 流式累积 tool_calls 增量并产出完整调用 |
| `app/skills/base.py` | SkillExecution 完整元数据；build_execution |
| `app/skills/registry.py` | 目录合并、启停、匹配、缺失参数错误、调用统计 |
| `app/skills/catalog.py` | **新增**：18 个 Skill 的版本、分类、能力边界 |
| `app/skills/builtin/*.py` | 返回完整 Skill 元数据 |
| `app/tools/base.py` | ToolDefinition 增加 category/error_policy；ToolResult 增加 error_type |
| `app/tools/executor.py` | 错误分类；可重试错误不扣配额；canonical 工具事件 |
| `app/tools/permissions.py` | use_skill 描述含技能目录与必填参数；兼容顶层参数 |
| `app/schemas/agent.py`、`api/routes/agents.py` | 暴露 Skill 新字段 |
| `app/api/routes/tools.py` | 工具元数据；新增 `/api/skills`、`/api/skills/match` |
| `app/memory/manager.py` | 只注入 active 记忆；新增 promote() |
| `app/services/task_service.py` | 流式传入 task/conversation；记录模型调用数、工具轮次；agent_started/completed/failed |
| `tests/test_tools.py` | 新增元数据、匹配、缺失参数、行为差异测试 |
| `scripts/capability_upgrade_verify.py` | **新增**：8 项端到端验收 + 流式工具测试 |

### 前端

| 文件 | 变更 |
| --- | --- |
| `src/types/classroom.ts` | 新增 skill_* / tool_call_* / agent_waiting / agent_failed 事件 |
| `src/store/classroom.ts` | 消费真实事件更新 liveToolCalls 与 agentStatuses |

### 文档

`docs/AGENT_ARCHITECTURE.md`、`docs/SKILL_SYSTEM.md`、`docs/TOOL_CALLING.md`、
`docs/AGENT_PERSONALITY.md`、`docs/AGENT_IMPROVEMENT_REPORT.md`。

## 2. 关键架构变化

1. **流式原生 Tool Calling**：流式响应中的 `tool_calls` 增量被累积解析、真实执行、
   回填后再次流式生成；不再是「流式模式没有工具」。
2. **Skill 分层加载**：System Prompt/工具描述只给名称、描述、触发条件与必填参数；
   模型选中后 `use_skill` 返回完整步骤与输出字段。
3. **任务感知的技能检索**：每轮按问题计算候选 Skill，结合 token 重叠、触发条件、
   意图分类与人格偏好，而不是固定下发全部技能。
4. **真实错误分类**：permission/limit/validation 不消耗配额；timeout/execution
   消耗配额。模型收到真实错误后决定重试或换方案。
5. **行为策略进入 Prompt**：三个 Agent 的决策、工具、Skill、协作、不确定性策略
   由 YAML 驱动并强制进入 System Prompt。
6. **自主路由**：多 Agent 决策新增 `next_speaker`；调度器只校验合法性与参与度，
   不替 Agent 决定观点。
7. **统一事件**：skill_selected/loaded/completed/failed、tool_call_started/
   completed/failed、agent_started/waiting/completed/failed；前端直接消费。

## 3. 分阶段实施结果

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| P0 | 原生 Tool Calling（含流式）、错误分类、权限与预算 | 已完成 |
| P1 | 统一 Skill 规范、Registry、匹配、启停、分层加载 | 已完成 |
| P2 | 候选 Skill 注入、Skill/Tool 组合、配额调整 | 已完成 |
| P3 | 三 Agent 行为策略差异化 | 已完成 |
| P4 | 自主路由、事件可观测性、前端同步 | 已完成 |
| P5 | 记忆只注入 active、候选提升接口 | 已完成（轻量） |

## 4. 验收测试与真实结果

脚本：`backend/scripts/capability_upgrade_verify.py`
结果：`backend/scripts/capability_upgrade_results.json`

| 测试 | 输入 | 真实结果 | 判定 |
| --- | --- | --- | --- |
| 1 Skill 独立使用 | 解释边际成本与递增规律 | `use_skill` 成功加载并返回步骤；回答覆盖定义、边界、易混概念 | PASS |
| 2 Tool 自主调用 | 1876 × 2947 | `calculator` 成功，结果 5528572 | PASS |
| 2b 流式 Tool | 987654 × 321 | 流式 token + 真实 `tool_calls`，结果 317036934 | PASS |
| 3 Skill + Tool | 增量成本 600/20 | `use_skill` + `calculator`，结果 30，并解释经济学含义 | PASS |
| 4 多步工具 | 1250×36 → ÷15 → 是否>2500 | 两次 calculator：45000 → 3000，判断成立 | PASS |
| 5 工具失败 | 沙箱执行未定义变量 | `python_sandbox` 返回 NameError；回答如实说明失败，未编造成功 | PASS |
| 6 个体差异 | 是否无条件追求规模扩张 | 三份答案结构、判断方式、提问习惯明显不同 | PASS |
| 7 多 Agent 协作 | 规模扩张与单位成本 | 三名 Agent 依次自主发言；Ethan 使用 CHALLENGE 质疑 Alex，Alex 回应并收紧前提；任务完成 | PASS |
| 8 事件同步 | 测试 2 的任务事件 | 事件含 tool_call_started/completed，与 `tool_calls` 表一致 | PASS |

### 关键证据

- 计算器参数：`{"expression":"1876*2947"}`，结果 `5528572`，耗时 7 ms。
- 多步调用：`1250*36 → 45000`，`45000/15 → 3000`，两次均为 success。
- 失败调用：`python_sandbox` 返回
  `RuntimeError: NameError: name 'undefined_variable_42' is not defined`，
  `error_type=execution`，模型在回答中逐字引用错误。
- 流式完成块：`done.tool_calls` 非空，`tool_rounds >= 1`，内容包含真实乘积。
- 事件序列包含：`agent_started`、`tool_call_started`、`tool_call_completed`、
  `tool_completed`、`agent_message`、`agent_completed`、`task_completed`。
- 多 Agent 决策动作：`CHALLENGE / RESPOND / RESPOND`，说明质疑不是固定轮流的
  RESPOND。
- 测试 3 的 3 次 calculator 参数分别为 `120-100`、`5600-5000`、`600/20`，
  中间结果被真实用于下一步。
- 单测：`45 passed`（`pytest tests --import-mode=importlib`）。
- 前端：`npm run build` 通过。

## 5. 能力实现情况

| 能力 | 实现情况 | 说明 |
| --- | --- | --- |
| Agent 自主选择 Skill | 已实现 | 每轮检索候选；模型决定是否、用哪个、用几个 |
| Skill 真实执行 | 已实现 | Python handler、Schema、权限、日志、结果回填 |
| 原生 Tool Calling（非流式） | 已实现 | 完整闭环，最多 4 轮 |
| 原生 Tool Calling（流式） | 已实现 | 累积 tool_calls 增量并真实执行 |
| Skill + Tool 协同 | 已实现 | 实测同一任务先 Skill 后 Calculator |
| 多步工具与中间结果 | 已实现 | 第二次调用使用第一次结果 |
| 工具失败恢复 | 已实现 | 真实错误回传，不伪造成功 |
| 三 Agent 差异 | 已实现 | 行为策略、技能偏好、工具权限、记忆隔离 |
| 多 Agent 自主协作 | 部分实现 | 可自主发言/质疑/指定下一位；仍受 token 预算与单工具决策限制 |
| 运行事件同步 | 已实现 | 后端事件驱动前端状态 |
| Skill 输出字段强校验 | 未实现 | 只作为契约，不做语义校验 |
| 多 Agent 原生 function calling | 未实现 | 仍使用 JSON 决策协议 |

## 6. 尚未解决的问题

1. **多 Agent 工具协议不是原生 function calling**：每次 `USE_TOOL` 只能执行一个
   工具，复杂多工具任务仍建议单 Agent 完成。
2. **讨论终止常由预算触发**：测试 7 的三方讨论以 `token_budget` 结束，
   而不是全员 FINISH。自然收束仍可优化。
3. **Skill 仍是方法论脚手架**：18 个技能共享三个通用 handler，不提供领域计算、
   知识库检索或联网核查。
4. **output_schema 未机器校验**：模型可能遗漏必需输出字段，当前只靠 Prompt 约束。
5. **候选检索是词法+意图规则**：没有使用 embedding，跨领域同义表达可能召回不足。
6. **token 预算按调用前检查**：最后一次模型调用可能让累计 token 超过阈值
   （实测测试 3 累计 18k，预算 12k），属于「单次调用粒度」的已知边界。
7. **Windows 沙箱中文 stderr 可能乱码**：纯 ASCII 错误信息正常。
8. **无鉴权/限流**：当前是内网演示级接口，公网部署前必须补充。
9. **事件存在 legacy + canonical 两套名称**：为兼容旧前端保留，后续可收敛。

## 7. 后续建议

1. 把多 Agent 的 `USE_TOOL` 升级为真正的 function calling，支持一轮多个工具。
2. 为 18 个 Skill 逐步接入领域执行器（如公式计算、课程知识检索），而不是继续
   扩展通用模板。
3. 增加 `output_schema` 的结构化输出校验：要求模型先输出 JSON 字段，再生成正文。
4. 讨论终止增加「争议已收敛/无新增论点」判断，减少预算硬终止。
5. 为 Skill 匹配引入轻量向量检索，保留当前规则作为兜底与可解释层。
6. 补充鉴权、限流、审计日志与敏感参数脱敏，再考虑公网部署。
