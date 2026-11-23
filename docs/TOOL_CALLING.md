# Tool Calling 说明

本文只描述真实可执行的工具链路。判定标准是：模型是否返回原生
`tool_calls`、后端是否执行真实函数、结果是否以 `role="tool"` 回填。

## 1. Tool Registry

`backend/app/tools/registry.py` 注册三个基础工具，`use_skill` 由
`ToolPermissionManager` 按人格动态构建。每个 `ToolDefinition` 包含：

| 字段 | 说明 |
| --- | --- |
| `name` | 工具名 |
| `description` | 给模型的能力说明 |
| `parameters` | JSON Schema |
| `handler` | 真实异步执行函数 |
| `category` | 工具分类 |
| `timeout_seconds` | 超时 |
| `risk_level` | 风险级别 |
| `requires_isolation` | 是否需要隔离进程 |
| `error_policy` | 失败处理规则 |

工具与人格配置分离：persona 只声明 `tool_permissions`
（名称 + 单任务最大次数），Prompt 不包含执行代码。

## 2. 权限矩阵

| 工具 | Alex | Mia | Ethan | 单任务上限 |
| --- | --- | --- | --- | --- |
| calculator | 是 | 是 | 是 | 3 / 2 / 3 |
| datetime | 是 | 是 | 是 | 2 / 2 / 1 |
| python_sandbox | 是 | 否 | 是 | 2 / - / 2 |
| use_skill | 是 | 是 | 是 | 3 |

未授权的工具不会下发给模型；即使模型编造工具名，执行器也会以
`permission` 错误拒绝。

## 3. 原生 Tool Calling 闭环

### 非流式

`backend/app/agents/graph.py`：

```
prepare_context
  → generate（携带 tools）
  → 模型返回 tool_calls
  → tools 节点：权限 → 次数 → JSON Schema → 真实执行
  → messages += role=assistant(tool_calls) + role=tool(result)
  → 回到 generate
  → 最多 4 轮 → finalize
```

### 流式

`backend/app/agents/executor.py` 的 `stream()`：

1. `provider.stream(messages, tools=schemas)`；
2. `DeepSeekProvider.stream()` 累积 `delta.tool_calls` 的 id/name/arguments 分片；
3. 结束后产出 `ModelStreamChunk(type="tool_calls")`；
4. 执行器真实执行工具，再发起下一轮流式请求；
5. 最终 `done` 块携带 `model_calls / tool_rounds / tool_log / usage`。

流式路径不是「先假流式、后补工具」：工具调用来自模型流式响应中的真实
`tool_calls` 增量，工具结果也真实回填。

### 多 Agent

`backend/app/agents/discussion.py` 的 `USE_TOOL` 决策由后端执行真实工具，
再把结果交给同一 Agent 二次生成。该路径使用 JSON 决策协议，不是模型原生
function calling；工具执行本身没有降级。

## 4. 参数校验与错误分类

`backend/app/tools/executor.py` 返回结构化错误：

| `error_type` | 触发条件 | 是否消耗配额 |
| --- | --- | --- |
| `permission` | 工具未注册/未授权 | 否 |
| `limit` | 超过单任务调用上限 | 否 |
| `validation` | JSON Schema 或 Skill 必填字段不满足 | 否，可补齐重试 |
| `timeout` | 超过工具超时 | 是 |
| `execution` | handler 抛异常 | 是 |

错误内容原样进入 `role="tool"` 消息，模型必须基于真实错误决定重试或改用其他
方案。网关不会把失败包装成成功，也不会用模型文本代替工具结果。

## 5. 基础工具实现

### Calculator

- AST 解析 + 白名单节点，不使用 `eval`。
- 支持四则运算、幂、取模、常用数学函数。
- 指数绝对值限制为 12，防止资源耗尽。
- 除零、非法表达式返回真实错误。

### DateTime

- 获取当前日期时间、星期、时间戳。
- 支持两个时间点差值。
- 支持 IANA 时区转换，未知时区返回错误。

### Python Sandbox

- 子进程执行，不进入 FastAPI 主进程。
- 5 秒超时、256 MB 内存限制。
- AST 黑名单 + 导入白名单（数学/统计/JSON 等）。
- 禁止文件、网络、系统调用。
- 返回 stdout / stderr / 退出状态；stderr 中文在 Windows 下可能出现编码乱码，
  属于已知低优先级问题。

### use_skill

- 只允许本人 Skill；工具描述包含技能目录与必填参数。
- 输入统一放 `input`，也兼容模型把字段放在顶层。
- 缺少必填字段时返回 `validation` 与缺失字段，可重试。

## 6. 循环与预算保护

- 单 Agent 工具循环最多 4 轮。
- 任务级模型调用最多 8 次，token/时长/消息数均有上限。
- 预算不足时停止下发工具，要求模型基于已有信息回答。
- 同一工具调用上限由 persona 控制，失败重试不会无限进行。

## 7. 日志与事件

每次调用写入 `tool_calls` 表：`tool_name / arguments / result / status /
error / duration_ms / prompt_tokens / completion_tokens`。

同时发出事件：

- `tool_call_started`
- `tool_call_completed`
- `tool_call_failed`
- `skill_selected / skill_loaded / skill_completed / skill_failed`

前端 `liveToolCalls` 直接消费这些事件，不使用模拟动画。日志不记录 API Key、
密码或完整敏感参数。

## 8. 已验证内容

真实 API 测试覆盖：单次计算、多步计算、Skill+Tool 协同、工具失败、未授权、
参数错误、流式工具调用与事件一致性。结果见
`backend/scripts/capability_upgrade_results.json` 与
`docs/AGENT_IMPROVEMENT_REPORT.md`。
