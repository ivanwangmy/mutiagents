# 多智能体系统真实性审计报告：Skills 与 Tools 实际运行能力

- 审计日期：2026-11-23
- 审计对象：`d:\eduagents\multi-agent-classroom`
- 审计方式：源码链路审查 + 真实后端 HTTP 调用 + 真实 DeepSeek 模型 + 真实工具执行 + 数据库日志核对
- 审计原则：**只审计，不修改任何业务代码**；未使用预设回答、模拟工具调用或硬编码结果。
- 原始证据：
  - `backend/scripts/capability_audit_results.json`
  - `backend/scripts/capability_audit_supplement.json`
  - PostgreSQL `tool_calls`、`task_events`、`messages` 表
  - 2026-11-23 16:20—16:26 的真实运行日志

---

## 1. 项目现有 Agent 架构

### 1.1 技术栈与运行方式

| 项目 | 实际情况 |
| --- | --- |
| 后端 | FastAPI + LangGraph + SQLAlchemy 2 async + PostgreSQL 16 |
| 前端 | React + TypeScript + Vite |
| 模型 | DeepSeek `deepseek-flash`，OpenAI 兼容协议 |
| 启动 | `backend/run_server.py`（SelectorEventLoop），端口 8000 |
| 任务编排 | 单 Agent 子图 + 多 Agent 父图，动态 `dispatch`，非固定轮询 |
| 事件 | `task_events` 持久化 + SSE（单进程 InProcess / Redis Pub/Sub） |

### 1.2 三个 Agent 是否独立

| Agent | 配置文件 | System Prompt | Skills | Tools | 记忆命名空间 |
| --- | --- | --- | --- | --- | --- |
| Alex | `app/agents/personas/alex.yaml` | `app/agents/prompts/alex.md` | 6 个 | calculator / datetime / python_sandbox / use_skill | `("agents","alex","memories")` |
| Mia | `app/agents/personas/mia.yaml` | `app/agents/prompts/mia.md` | 6 个 | calculator / datetime / use_skill（**无 python_sandbox**） | `("agents","mia","memories")` |
| Ethan | `app/agents/personas/ethan.yaml` | `app/agents/prompts/ethan.md` | 6 个 | calculator / datetime / python_sandbox / use_skill | `("agents","ethan","memories")` |

结论：【已实现】三者不是"一个模型用同一提示词扮演三个名字"。

证据链：

1. `app/agents/registry.py:30-57` 强制加载三个固定 Agent，缺少任一 YAML / MD 即启动失败。
2. `app/agents/registry.py:45-47` 校验 Prompt 必须包含该 Agent 姓名锚点，防止提示词串用。
3. `app/agents/registry.py:48-50` 校验 Skill 的 `applicable_agents`，未授权 Skill 无法挂载。
4. `app/agents/registry.py:60-75` 为每个 Agent 独立拼接 System Prompt：人格 Prompt + 本人 Skills + 课堂协议 + 身份确认。
5. 每次发言独立调用模型，消息、工具调用、Token 分别归属具体 `agent_id`；数据库中三条 Agent 消息独立存储。

需要说明的边界：三者使用**同一模型供应商与同一模型名**，差异来自人格、温度、工具权限、Skills 与记忆，而不是不同模型。这是常见且合理的多 Agent 设计，但不应描述为"三个不同模型"。

### 1.3 统一模型适配与上下文/状态

- `app/model/base.py` 定义 `ModelProvider`、`ModelResponse`、`ToolCallRequest`、`ModelStreamChunk`。
- `app/model/deepseek.py:104-147` 实现 `complete()`：真实 HTTP 请求、解析文本/usage/`tool_calls`。
- `app/model/deepseek.py:149-158` 实现 `stream()`：真实流式；**未传 tools**（见第 4 节限制）。
- 上下文：当前问题 + 最近公开消息 + 该 Agent 的记忆/经验 + 任务预算，由 `AgentExecutor` 构建。
- 状态：`TaskExecution` 维护 pending/running/completed/failed/stopped 与 stop_reason；SSE 事件持久化。
- 异常：模型错误、工具错误、超时、用户停止均有独立分支与终态事件。

---

## 2. Skills 清单与真实运行情况

### 2.1 清单

| Agent | Skill | 用途（when_to_use 摘要） | 执行入口 |
| --- | --- | --- | --- |
| Alex | concept_explanation | 概念定义、边界、常见混淆 | `app.skills.builtin.analysis:run` |
| Alex | theory_analysis | 理论框架、前提假设、推论链 | 同上 |
| Alex | logical_reasoning | 逻辑推理与反例检验 | 同上 |
| Alex | knowledge_verification | 核查说法与证据 | 同上 |
| Alex | teaching_guidance | 教学路径与练习设计 | 同上 |
| Alex | answer_evaluation | 评价回答的强弱与缺口 | 同上 |
| Mia | knowledge_organization | 知识结构化整理 | `app.skills.builtin.teaching:run` |
| Mia | problem_decomposition | 问题拆解 | 同上 |
| Mia | learning_assistance | 学习困难支持 | 同上 |
| Mia | information_summarization | 信息总结 | 同上 |
| Mia | knowledge_gap_detection | 知识缺口识别 | 同上 |
| Mia | explanation_adaptation | 讲解方式适配 | 同上 |
| Ethan | curiosity_exploration | 好奇心驱动的探索 | `app.skills.builtin.inquiry:run` |
| Ethan | critical_questioning | 批判性提问 | 同上 |
| Ethan | assumption_detection | 隐含假设识别 | 同上 |
| Ethan | interdisciplinary_association | 跨学科联想 | 同上 |
| Ethan | alternative_hypothesis | 替代假设 | 同上 |
| Ethan | student_perspective_evaluation | 学生视角评价 | 同上 |

每个 Skill 均具备：唯一名称、描述、适用 Agent、`when_to_use`、输入 Schema、输出 Schema、执行入口、示例、权限（`app/agents/personas/alex.yaml:21-55`）。

### 2.2 Skill 是否为"可执行模块"

【部分实现】

- 是真实 Python 模块：`app/skills/registry.py:23-34` 通过 `importlib` 导入 `module:function`，不可调用则启动失败。
- 加载时校验重名与授权：`app/skills/registry.py:43-54`。
- 执行前校验输入 Schema 与权限：`app/skills/registry.py:75-86`。
- 真实执行返回结构化结果，数据库可查：

```json
{"skill":"theory_analysis","description":"围绕问题梳理理论框架、前提假设与推论链",
 "inputs":{"question":"..."},"steps":["列出分析依赖的前提假设", "..."],
 "checks":["前提是否被明确写出而非默认", "..."]}
```

- 但 `app/skills/builtin/analysis.py:13-102` 显示：所有 Alex Skill 共用同一个 `run()`，返回的是**静态方法论步骤与检查点**，没有领域计算、外部检索或知识库访问；`teaching.py`、`inquiry.py` 同理。
- `output_schema` 只写在配置中，代码没有校验模型回答是否覆盖；属于"仅有定义"。

因此：**Skill 是真实的"流程脚手架执行器"，不是"领域能力执行器"**。它能被执行、被记录、能影响回答结构，但不能独立完成经济学计算、资料检索等实质任务。

### 2.3 Agent 是否自主选择 Skill

【部分实现】

| 测试 | 是否自然触发 use_skill | 结果 |
| --- | --- | --- |
| C：边际成本概念讲解 | 否（0 次） | 模型直接回答，质量尚可 |
| D：增量成本计算 + 经济含义 | 否（0 次） | 模型心算 30 元/件，未用技能/计算器 |
| C2：显式要求加载 concept_explanation | 是（成功） | 返回定义/边界/混淆步骤，回答按步骤展开 |
| D2：显式要求 theory_analysis + 计算器 | 是（成功） | 先算 30，再按理论步骤解释 |
| I：要求同时加载两个 Skill | 部分失败 | 输入 Schema 错误、调用次数上限，见 2.5 |

机制上模型能看到 Skill 列表并决定是否调用：`app/agents/registry.py:61-70` 将名称、描述、适用场景写入 System Prompt；`app/tools/permissions.py:51-91` 将 `use_skill` 作为原生工具下发，`enum` 限制为本 Agent 的 Skill。

但自然提问下两次均未调用，说明"能选择"不等于"会稳定选择"。Skill 的 `when_to_use` 已写进 Prompt，却没有触发策略、置信度或强制规则。

### 2.4 Skill 完整调用链

【已实现】

```
System Prompt 列出 Skills
  → 模型输出原生 tool_call: use_skill(skill, input)        app/model/deepseek.py:130-143
  → ToolExecutor 权限 + 参数校验                          app/tools/executor.py:50-63
  → handler: skills_registry.execute(profile, ...)        app/tools/permissions.py:60-64
  → 模块 run() 返回 steps/checks/output                  app/skills/builtin/analysis.py:93-102
  → ToolExecutor 写入 tool_calls 日志                      app/tools/executor.py:117
  → role=tool 结果回填模型                                app/agents/graph.py:185
  → 模型基于步骤生成最终回答（C2/D2 均发生第二次模型调用）
```

- `tool_calls` 表可查到 `tool_name=use_skill`、`arguments.skill`、`status`、`error`、耗时。
- 消息 `metadata.tool_calls` 也记录本轮工具调用。

### 2.5 Skill 组合与错误处理

【部分实现，且存在明显可用性缺陷】

真实测试 `I` 两个任务共 6 次调用（来自数据库）：

| 调用 | 参数 | 结果 |
| --- | --- | --- |
| concept_explanation | `{"concept":"边际成本",...}` | success |
| theory_analysis | `{"problem":"...","framework":"..."}` | error：缺少必填 `question` |
| theory_analysis | 补上 `question` | error：`use_skill` 已达 2 次上限 |
| concept_explanation | 只给 `question` | error：缺少必填 `concept` |
| theory_analysis | 只给 `question` | success |
| concept_explanation | 补上 `concept` | error：调用次数已达上限 |

根因：`app/tools/permissions.py:72-88` 只把 `input` 定义成通用对象，具体必填字段"见系统提示中的 Skills 说明"；而 `app/agents/registry.py:61-64` 实际只写了名称、描述、适用场景，**没有写每个 Skill 的必填参数**。模型只能试错。

这是本轮审计发现的最高优先级可用性问题：Skill 能执行，但模型很难一次调用正确。

---

## 3. Tools 清单与真实运行情况

### 3.1 工具清单与权限

| 工具 | 功能 | 权限 | 单任务上限 | 超时 | 隔离 |
| --- | --- | --- | --- | --- | --- |
| calculator | AST 安全表达式计算 | alex / mia / ethan | Alex 3、Mia 2、Ethan 3 | 3s | 禁止导入/属性逃逸，指数绝对值≤12 |
| datetime | 当前日期时间/时区 | alex / mia / ethan | Alex 2、Mia 2、Ethan 1 | 3s | 无 |
| python_sandbox | 子进程 Python 执行 | **alex / ethan** | 2 | 5s | AST 黑名单、导入白名单、256MB |
| use_skill | 执行本 Agent 的 Skill | alex / mia / ethan | 2 | 3s | 仅限本人 Skill |

来源：`app/agents/personas/*.yaml:132-141`，权限构建 `app/tools/permissions.py:26-49`。

### 3.2 工具是否真实执行

【已实现】4 个工具都是真实后端函数，执行结果写入 `tool_calls`：

- 计算器：`app/tools/builtin/calculator.py:40-98`，AST 白名单求值，真实返回数值。
- 日期：真实系统时间与时区。
- Python：`app/tools/builtin/python_sandbox.py:167-214` 子进程执行，超时/内存限制。
- Skill：真实导入模块并执行。

数据库证据（`tool_calls`）包含参数、结果、状态、错误、耗时，例如：

```
calculator success {"expression":"1876*2947"} → {"value":5528572}
python_sandbox error {"code":"print(未定义变量)"} → NameError
```

---

## 4. 模型原生 Tool Calling 实现情况

### 4.1 单 Agent：完整原生闭环

【已实现】

| 环节 | 代码位置 | 实际情况 |
| --- | --- | --- |
| 向模型传工具定义 | `app/model/deepseek.py:69` | `payload["tools"] = tools` |
| 解析模型 Tool Call | `app/model/deepseek.py:130-143` | 解析 `message.tool_calls` 的 id/name/arguments |
| 权限检查 | `app/tools/executor.py:50` | `context.can_call(name)` |
| 参数校验 | `app/tools/executor.py:63` | `jsonschema.validate` |
| 真实执行 | `app/tools/executor.py:76-83` | 调用真实 handler，带超时 |
| 结果回填 | `app/agents/graph.py:185` | `role: "tool"` + `tool_call_id` |
| 继续生成 | `app/agents/graph.py:192-205` | 有 tool_calls 且未超轮次则回 `generate` |
| 多轮保护 | `app/agents/graph.py:23` | `MAX_TOOL_ROUNDS = 4` |
| 调用记录 | `app/tools/executor.py:117` | 写 `ToolCall` 表 |

补充：任务级 `TaskExecution.model_calls`、`token` 预算同时约束，`app/agents/graph.py:59` 在预算不足时不再允许工具。

### 4.2 多 Agent：不是原生 Tool Calling，而是结构化协议

【部分实现，但执行真实】

多 Agent 讨论没有让模型直接返回原生 `tool_calls`，而是要求模型输出 JSON 决策：

```
{"action":"USE_TOOL","tool":{"name":"calculator","arguments":{...}},"content":""}
```

- 协议定义：`app/agents/discussion.py:39,62,73`。
- 识别：`app/agents/discussion.py:560-561`。
- 真实执行：`app/agents/discussion.py:683-800`，内部同样调用 `tool_executor.execute`，含权限、参数、次数限制。
- 执行后再发起一次模型调用，把真实结果写进公开回答。

因此多 Agent 的工具执行是真实的，但链路是"模型输出 JSON → 后端执行 → 二次生成"，不是原生 function calling。风险是模型可能输出格式错误的 JSON；`parse_decision` 会把损坏的 USE_TOOL 降级为 RESPOND/WAIT（`tests/test_discussion.py:178-184`），不会把普通文本误当工具执行。

### 4.3 流式模式：不调用工具

【未实现】

- `app/model/deepseek.py:149-158` 的 `stream()` 明确 `tools=None`。
- `app/services/task_service.py:475-511` 的 `stream_single_agent` 直接使用 `executor.stream`，没有工具循环。
- 结论：流式回答可以真实流式输出文本，但**不会调用任何工具/Skill**。需要工具时必须走普通任务接口。

### 4.4 模型能力探测

`GET /api/system/config-status` 返回：

```json
{"capabilities":{"text":true,"stream":true,"tool_calling":true,"structured_output":true}}
```

来源 `backend/data/model_capabilities.json`，其中 `tool_calling` 记录了真实调用：

```json
{"ok":true,"calls":["calculator"],"arguments":["{\"expression\": \"12*7+5\"}"],"finish_reason":"tool_calls"}
```

注意：这是**历史探测文件**，不是每次启动实时探测。本轮已用真实任务独立复核，结论一致；但探测结果可能随模型/账号变化而过期。

### 4.5 是否会把普通文本 JSON 误认为工具调用

【未发生，已验证】

测试 G：要求 Alex"不要调用任何工具，只输出 JSON 文本"。两个任务 `tool_calls` 均为 0，回答只是代码块。单 Agent 只解析响应中的原生 `tool_calls` 字段，不解析正文 JSON。

---

## 5. 完整调用链路

### 5.1 单 Agent（非流式）

```
用户问题
 → TaskService 创建 task + user message
 → LangGraph: prepare_context
 → generate: DeepSeek complete(tools=[...])          deepseek.py:104-147
 → 若 tool_calls：权限 → 参数 → 执行 → 日志 → role=tool → generate（最多 4 轮）
 → 无 tool_calls：写 assistant message + usage + metadata
 → task_completed / agent_message → SSE
```

### 5.2 多 Agent

```
dispatch 选发言者
 → agent_turn: 构建公开上下文 + 本人记忆/经验 + 工具清单
 → 模型返回 JSON 决策（RESPOND / CHALLENGE / USE_TOOL / WAIT / FINISH）
 → USE_TOOL: 权限/参数/次数 → 真实执行 → 二次模型调用生成回答
 → 消息总线写入公开消息
 → dispatch 继续，直到 FINISH/预算/轮次/停止
```

证据：本轮 M 任务（`task_id=34ffeb7e-033f-41b4-9b33-a9209e8de92a`）中 Alex 真实调用计算器得到 5,528,572，公开消息携带该结果，Mia 随后引用并质疑其统计含义。

---

## 6. 六项功能测试结果

测试均通过运行中的后端和真实模型执行，原始数据在 `capability_audit_results.json`。

### 测试 A：简单计算 【已完成】

- 输入：`请计算 1876 × 2947，并说明计算过程中的关键步骤。`
- 实测：`calculator` 1 次，参数 `{"expression":"1876*2947"}`，结果 `5528572`。
- 模型调用 2 次（决策 + 总结），5,138 token，3.69s，`completed/finish`。
- 回答使用真实结果并说明步骤，未编造。

### 测试 B：多步骤计算 【已完成】

- 输入：`先计算 1250 × 36，再将结果除以 15，最后判断结果是否大于 2500。`
- 实测：同一轮返回 2 个工具调用：
  - `1250*36` → `45000`
  - `1250*36/15` → `3000`
- 回答判断"3000 > 2500"，结论正确。
- 说明：第二个调用是模型自行重算完整表达式，并未使用第一次工具返回值。
- 补充 B2 验证真正的"依赖中间结果"：
  - 输入要求分两步、不得合并表达式；
  - 实测 3 次模型调用、2 轮工具：
    - `1876*2947` → `5528572`
    - `5528572*3` → `16585716`
  - 证明框架支持"工具结果 → 再次决策 → 再调用"的真实闭环。

### 测试 C：需要 Skill 的知识问题 【部分完成】

- 输入：`请解释什么是边际成本，并使用一个生活中的例子说明边际成本递增规律。`
- 自然执行：**没有调用 use_skill**，1 次模型调用，2,920 token，回答正确且结构完整。
- 显式执行 C2：要求加载 `concept_explanation` 后，`use_skill` 成功，返回定义/边界/混淆步骤；第二轮模型回答明确"按技能要求"依次展开。
- 结论：Skill 可执行、可影响回答；但模型不会稳定自主选择 Skill。没有"必须使用技能"的判定规则。

### 测试 D：Skill 与 Tool 协同 【部分完成】

- 输入：`100 件总成本 5000，120 件总成本 5600，计算 20 件新增产品的平均增量成本并解释经济含义。`
- 自然执行：**未调用 Skill，也未调用计算器**，模型心算 `600/20=30`，回答正确。
- 显式执行 D2：先 `use_skill(theory_analysis)` 成功，再 `calculator((5600-5000)/20)` 得到 `30`，回答明确"按 theory_analysis 的步骤展开"。
- 结论：Skill + Tool 技术链路可协同；但自然状态下模型倾向于直接作答。

### 测试 E：工具调用失败 【已完成】

| 子测试 | 输入 | 真实结果 |
| --- | --- | --- |
| E1 | 计算器算 `12 ÷ 0` | `ZeroDivisionError: division by zero`，错误回传模型，回答如实说明"除数为 0，无定义" |
| E2 | Python 执行 `print(未定义变量)` | `NameError: name '未定义变量' is not defined`（中文在 stderr 中出现乱码），回答明确说明运行失败 |
| 附加 | Mia 计算 `2**20` | 第一次被计算器拒绝（指数>12），第二次改为 `1024*1024` 得到 `1048576` |

- 未发现"工具失败但回答声称成功"的情况。
- 发现 1 个低优先级缺陷：Python 沙箱错误信息中的中文标识符编码为乱码（见问题清单 I-7）。

### 测试 F：Agent 差异化 【已完成】

同一问题分别问三位 Agent：

| Agent | 输出特征（真实片段） | 工具 |
| --- | --- | --- |
| Alex | "我先给结论方向……先建立直觉……假设你开一家小面馆，厨房、灶台、桌椅都已备好" | 无 |
| Mia | "我先补定义和递增从哪来这两块，再给例子……第一步：先分清平均和边际" | 无 |
| Ethan | "我现在的理解是……不过我想先确认一个容易混的点……比如一家奶茶店" | 无 |

同一 Python 问题：

| Agent | 结果 |
| --- | --- |
| Alex | `python_sandbox` 成功，`2**20 = 1048576` |
| Ethan | `python_sandbox` 成功，`2**20 = 1048576` |
| Mia | 无权限；先尝试 `2**20` 被计算器拒绝，再改用 `1024*1024` 得到 `1048576` |

结论：表达策略、教学视角、工具权限均存在真实差异，不是只换名称和语气。

---

## 7. 三个 Agent 差异化分析

| 维度 | Alex | Mia | Ethan | 是否真实差异 |
| --- | --- | --- | --- | --- |
| 人格 Prompt | 定义→推理→判断标准 | 拆解→逐步确认→自检 | 困惑→质疑→替代解释 | 是 |
| 温度/输出上限 | 0.35 / 900 | 见 persona | 见 persona | 是 |
| Skill 集 | 分析类 6 个 | 教学类 6 个 | 探究类 6 个 | 是 |
| Python 权限 | 有 | **无** | 有 | 是 |
| 记忆命名空间 | alex | mia | ethan | 是 |
| 底层模型 | deepseek-flash | 同左 | 同左 | 否（共用模型） |

需要避免的误判：三者的知识准确性接近，回答质量差异主要来自提示词与工具权限，而不是不同模型能力。若业务要求"不同知识边界"，目前只靠 Prompt 约束，没有独立知识库或检索源。

---

## 8. 多 Agent 协作中的能力调用

【部分实现】

已验证：

1. **自主决定是否参与**：`task_events` 记录 Mia 两次 `WAIT`，Ethan `CHALLENGE`，Alex `RESPOND`，不是固定轮流。
2. **主动提问/质疑**：双 Agent 定向测试出现 `challenge` 类型消息；Ethan 质疑 Alex 的"近日点"解释，Alex 承认并修正。
3. **请求帮助**：协议支持 `REQUEST_HELP`，单测覆盖；本轮未单独触发真实请求帮助。
4. **公开信息共享**：M 任务中 Alex 的计算结果写入公开消息，Mia 能引用 5,528,572 并继续质疑。
5. **各自调用工具**：单 Agent 工具权限在讨论中同样生效（`discussion.py:696-719` 构建本人 `ToolContext`）。
6. **工具结果跨 Agent 传递**：通过公开消息摘要传递，不共享原始 `tool_calls` 记录；符合"工具原始输出仅调用者可见"的设计。
7. **未选 Agent 不参与**：参与者与实际发言者集合一致。

限制：

- 每个讨论回合最多执行一个工具动作，执行后必须二次生成，不能在同一回合内连续多次调用。
- 不支持原生并行 Tool Calling；多工具需求要靠多个回合。
- 未观察到两个 Agent 在同一次任务中各自调用工具的真实样本（系统支持，但未构造成功用例）。

---

## 9. 问题清单（已实现 / 部分实现 / 未实现 / 无法验证）

### 9.1 已实现

| 编号 | 结论 | 证据 |
| --- | --- | --- |
| I-01 | 三 Agent 独立配置、独立 Prompt、独立调用 | `registry.py:30-75`；三次独立消息与 token |
| I-02 | 原生 Tool Calling 完整闭环（单 Agent 非流式） | `deepseek.py:69,130-143`；`graph.py:111-205` |
| I-03 | 工具真实执行、参数校验、权限、超时、日志 | A/B/E/F 真实 `tool_calls` |
| I-04 | 多轮工具调用 | B2：5528572 → 16585716 |
| I-05 | 工具失败回传与模型如实说明 | E1/E2 |
| I-06 | 纯文本 JSON 不会被误判为工具调用 | G：0 次工具调用 |
| I-07 | Skill 可真实加载、校验、执行并返回结构化结果 | C2/D2；`tool_calls` 中 `use_skill` success |
| I-08 | 多 Agent 自主发言与定向质疑 | `task_events` 中 WAIT/CHALLENGE/RESPOND |
| I-09 | Agent 间通过公开消息共享工具结果 | M 任务 |
| I-10 | 工具调用与 Skill 调用可审计 | `tool_calls`、消息 metadata |

### 9.2 部分实现

| 编号 | 问题 | 严重度 | 证据与影响 |
| --- | --- | --- | --- |
| P-01 | Skill 输入 Schema 未暴露给模型 | **高** | Prompt 只写名称/描述/场景（`registry.py:61-64`）；`use_skill` 的 input 是通用对象（`permissions.py:80-84`）。I 任务 6 次调用中多次因缺少必填字段失败。用户会看到技能"调用了但没成功"。 |
| P-02 | Skill 是流程模板，不是领域能力 | **高** | 每个 Agent 的 6 个 Skill 共用一个 `run()`（`analysis.py:93-102`），只返回静态步骤。不能计算、不能检索、不能生成领域数据。 |
| P-03 | 自然提问下 Skill 触发率低 | 中 | C、D 两次均未调用 `use_skill` |
| P-04 | Skill 组合不稳定 | 中 | 单任务上限 2 次；一次错误就消耗额度，未能完成两个不同 Skill 的成功组合 |
| P-05 | 流式接口不支持工具 | 中 | `deepseek.py:158 tools=None`；`task_service.py:508` |
| P-06 | 多 Agent 使用 JSON 协议而非原生 Tool Calling | 中 | `discussion.py:560-561,683-800`；每回合最多一个工具动作 |
| P-07 | Skill output_schema 未强制 | 低 | 配置有输出规范，代码不校验模型最终回答 |
| P-08 | Python 沙箱错误中文乱码 | 低 | E2 返回 `name 'δ�������' is not defined` |

### 9.3 未实现

| 编号 | 问题 | 影响 |
| --- | --- | --- |
| N-01 | 领域知识库/检索型 Skill | Skill 无法提供课程资料、题库、外部数据 |
| N-02 | Skill 自动编排（多技能链式执行） | 需要模型手动逐个调用，且受 2 次上限约束 |
| N-03 | 流式回答中的工具调用 | 流式模式只能纯文本回答 |
| N-04 | 多 Agent 单回合并行/连续工具调用 | 复杂任务需要跨回合完成 |

### 9.4 无法验证

| 编号 | 项目 | 原因 |
| --- | --- | --- |
| U-01 | 其他模型供应商的原生 Tool Calling | 当前只配置 DeepSeek |
| U-02 | calculator/datetime 的真实超时 | 执行均在毫秒级，未触发 3s 超时 |
| U-03 | 生产多 worker 下工具日志一致性 | 本轮单实例审计 |
| U-04 | 高并发工具调用限流 | 未做压力测试 |
| U-05 | 模型能力探测实时性 | `data/model_capabilities.json` 为历史探测文件 |

---

## 10. 问题严重程度排序

| 优先级 | 编号 | 问题 | 对用户体验的影响 |
| --- | --- | --- | --- |
| 1 | P-01 | Skill 输入 Schema 不可见 | 技能调用频繁失败，用户感觉"技能不好用" |
| 2 | P-02 | Skill 无领域执行能力 | 技能只给步骤，不能真正完成专业任务 |
| 3 | P-03 | 自然触发率低 | 用户不知道何时该用技能，系统也不主动用 |
| 4 | P-04 | 组合受限 | 复杂问题无法一次加载多个能力 |
| 5 | P-05 | 流式无工具 | 流式回答中的计算/时间是模型编造的高风险区 |
| 6 | P-06 | 多 Agent 非原生协议 | 多一次模型调用，格式错误需降级 |
| 7 | P-07 | 输出规范不校验 | 回答可能遗漏技能要求字段 |
| 8 | P-08 | 错误乱码 | 错误信息可读性差 |

---

## 11. 推荐修复顺序

1. **把每个 Skill 的必填参数写进模型可见的位置**：在 System Prompt 的 Skills 段附上 `required` 字段与类型，或将 `use_skill.input` 改为按 Skill 名区分的 `oneOf` 结构。目标是让模型一次调用成功。
2. **为 Skill 增加触发策略**：在 Prompt 中给出"何时必须调用"的判定条件，并在服务端增加关键词/任务类型兜底；记录触发率。
3. **让 Skill 具备真实领域逻辑**：至少为教学场景接入知识库/检索或计算模块；否则应把 Skill 明确标注为"方法论模板"，避免过度承诺。
4. **强制 output_schema 校验**：技能返回后检查模型回答是否覆盖必填输出字段，缺失时要求补全。
5. **流式链路接入工具，或在 UI 明确提示"流式模式不支持工具"**，避免模型在流式中口算冒充工具结果。
6. **统一多 Agent 工具协议**：优先改为原生 Tool Calling；若保留 JSON 协议，应支持单回合多工具并共享结构化结果。
7. **修复沙箱 stderr 编码**（设置 UTF-8 环境），并补充中文错误用例。
8. **将模型能力探测改为启动时或按需实时探测**，并记录时间戳。

---

## 12. 最终结论

| 问题 | 结论 |
| --- | --- |
| 当前 Agent 是否真正能够使用 Skills？ | **部分能够**。`use_skill` 是真实原生工具，Skill 是真实 Python 模块，能执行并返回步骤；但 Skill 只是流程模板，且模型自然触发率低、参数常传错。 |
| 当前 Agent 是否真正能够调用 Tools？ | **是**。calculator / datetime / python_sandbox 均为真实后端函数，有权限、参数校验、超时、次数限制和数据库日志；A/B/B2/E/F 均有真实结果。 |
| 是否实现完整的原生 Tool Calling 闭环？ | **单 Agent 非流式：是**（定义→调用→执行→role=tool→继续生成→多轮）。**多 Agent：否**，使用 JSON 决策协议；**流式：否**，未传 tools。 |
| Skills 与 Tools 是否能够协同工作？ | **技术上可以**。D2 实测 `use_skill` + `calculator` 得到 30 并输出结构化解释；但需要显式要求，自然状态下模型可能两者都不用。 |
| 三个 Agent 是否具有真实的能力差异？ | **是**。人格、Prompt、Skill 集、工具权限、记忆隔离均不同；Mia 无 Python 权限并以计算器回退，是可直接观察的差异。底层模型相同。 |
| 距离真正可用的多智能体系统还有哪些关键差距？ | ① Skill 输入契约对模型不可见；② Skill 缺少领域执行能力；③ 自主选择 Skill 不可靠；④ 流式无工具；⑤ 多 Agent 非原生工具协议且单回合单工具；⑥ 无鉴权与限流（部署层面）。 |

**总体判定：Tools 能力为"已实现且真实闭环"；Skills 能力为"真实可执行但能力层级较浅、调用可靠性不足"；多 Agent 协作真实存在，但工具调用协议尚未统一为原生 Tool Calling。**

本轮未修改任何业务代码；所有测试均可通过以下脚本复现：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts/capability_audit.py
.\.venv\Scripts\python.exe scripts/capability_audit_supplement.py --direct
```
