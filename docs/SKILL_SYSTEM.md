# Skill 系统说明

本轮把 Skill 从「Prompt 里的一段描述」升级为统一注册、可匹配、可执行、
可观测的能力模块。Skill 仍然是方法论脚手架，不冒充领域数据库或联网检索。

## 1. 统一规范

每个 Skill 对应一个 `SkillSpec`（`backend/app/agents/config.py`），字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 唯一标识，默认等于 `name` |
| `name` | 工具内使用的技能名 |
| `version` | 版本号，默认 `1.0.0` |
| `category` | 能力分类，用于匹配与展示 |
| `description` | 能力描述 |
| `applicable_agents` | 授权 Agent 列表 |
| `trigger_conditions` | 触发条件，未填时由 `when_to_use` 生成 |
| `input_schema` | JSON Schema，含 `required` |
| `execution_steps` | 可选，显式执行步骤；未填时由 handler 返回 |
| `output_schema` | 必须覆盖的输出字段 |
| `error_handling` | 参数/执行错误处理说明 |
| `limitations` | 能力边界 |
| `enabled` | 是否启用 |
| `execution_logic` | `module:function`，加载时真实 import 校验 |

版本、分类与能力边界集中登记在 `backend/app/skills/catalog.py`；YAML 只描述
「这个技能做什么」。未在 catalog 登记的新 Skill 会在加载时报错，避免无效技能。

## 2. Registry 能力

`backend/app/skills/registry.py` 提供：

- **加载**：遍历三个 Agent 的 persona，校验授权、名称唯一、执行函数可导入。
- **发现**：`for_agent(agent_id)` 返回该 Agent 启用的 Skill。
- **匹配**：`match(profile, query, limit)` 结合 token 重叠、触发条件、
  任务意图分类、人格偏好打分，返回候选 Skill 及必填参数。
- **分层加载**：
  1. System Prompt / 工具描述只给名称、描述、适用条件、必填参数；
  2. 模型选择后调用 `use_skill`，返回完整步骤、检查点、输出字段、边界；
  3. 模型按步骤完成任务。
- **组合**：一次任务可多次调用 `use_skill`（配额 3 次），也可在一次模型响应中
  并行调用多个 Skill。
- **启停**：`set_enabled(name, enabled)`；停用技能不会下发给模型。
- **观测**：`stats()` 返回总数、启用数、调用次数与失败次数；HTTP 接口
  `GET /api/skills`、`GET /api/skills/match` 可查询。
- **执行**：权限 → 必填字段 → JSON Schema → handler；错误包含缺失字段。

Agent 不会在每次请求中收到 18 个技能的完整正文，只收到本轮检索出的前 3 个候选。

## 3. 匹配不是关键词唯一命中

`match()` 的得分：

```
0.45 × 问题与技能文本 token 重叠
+ 0.20 × 触发条件命中/重叠
+ 0.10 × 技能名命中
+ 0.15 × 人格偏好
+ 0.18 × 任务意图分类命中
```

意图分类由 `_INTENTS` 定义（概念解释、逻辑论证、质疑反例、总结归纳、教学拆解）。
例如「请解释什么是边际成本」会优先命中 `category=concept` 的
`concept_explanation`，而不会只因为出现「边际」就命中理论分析。

## 4. 当前 18 个 Skill

| Agent | Skill | 分类 | 必填参数 |
| --- | --- | --- | --- |
| Alex | concept_explanation | concept | concept |
| Alex | theory_analysis | theory | question |
| Alex | logical_reasoning | logic | argument |
| Alex | knowledge_verification | verification | claim |
| Alex | teaching_guidance | pedagogy | topic |
| Alex | answer_evaluation | evaluation | answer |
| Mia | knowledge_organization | organization | items |
| Mia | problem_decomposition | decomposition | question |
| Mia | learning_assistance | scaffolding | stuck_point |
| Mia | information_summarization | summarization | messages |
| Mia | knowledge_gap_detection | diagnosis | explanation |
| Mia | explanation_adaptation | adaptation | audience_signal |
| Ethan | curiosity_exploration | exploration | topic |
| Ethan | critical_questioning | critique | claim |
| Ethan | assumption_detection | assumption | argument |
| Ethan | interdisciplinary_association | analogy | concept |
| Ethan | alternative_hypothesis | hypothesis | phenomenon |
| Ethan | student_perspective_evaluation | perspective | explanation |

## 5. 调用契约

`use_skill` 是真实工具（`backend/app/tools/permissions.py`）：

```json
{
  "skill": "concept_explanation",
  "input": {"concept": "边际成本", "context": "经济学入门"}
}
```

返回：

```json
{
  "skill": "concept_explanation",
  "skill_id": "concept_explanation",
  "version": "1.0.0",
  "category": "concept",
  "required_inputs": ["concept"],
  "steps": ["...", "..."],
  "checks": ["...", "..."],
  "output_fields": ["definition", "boundaries", "confusions"],
  "error_handling": "...",
  "limitations": ["..."]
}
```

模型必须按 `steps` 组织回答，并覆盖 `output_fields`。后端不校验最终文本是否
真的覆盖字段（语义判断不可靠），这一点在改进报告中标为部分实现。

## 6. 错误处理

| 情况 | 行为 |
| --- | --- |
| 缺少必填参数 | 返回 `validation` 错误，列出缺失字段与参数要求；不消耗调用配额 |
| Skill 未授权 | 权限错误，不执行 |
| Skill 已停用 | 拒绝执行 |
| handler 抛异常 | 真实错误返回模型，计入失败次数 |
| 超过调用上限 | `limit` 错误，提示预算已用完 |

模型收到错误后可以补齐参数重试，或改用其他 Skill/Tool；不允许编造成功结果。

## 7. 已知边界

- 18 个 Skill 共享三个通用 handler（`analysis.py`、`teaching.py`、`inquiry.py`），
  返回的是方法论步骤，不是领域计算结果或知识库检索。
- `output_schema` 只作为 Prompt 契约与返回字段，不做最终答案的机器校验。
- 技能只能由本人使用；当前不支持跨 Agent 直接调用他人 Skill。
