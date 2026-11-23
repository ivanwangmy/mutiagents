# Agent 人格与行为差异

三个 Agent 共享同一模型（deepseek-flash），但拥有独立的人格 Prompt、行为策略、
Skill 集、工具权限与记忆空间。差异不靠换名字或换语气，而靠可观察的决策与输出。

## 1. 配置来源

| 内容 | 文件 |
| --- | --- |
| 人格与能力 | `backend/app/agents/personas/alex.yaml` 等 |
| 角色 Prompt | `backend/app/agents/prompts/alex.md` 等 |
| 共同课堂约定 | `backend/app/agents/prompts/_protocol.md` |
| 加载与 Prompt 合成 | `backend/app/agents/registry.py` |

`AgentProfile` 把人格、行为策略、Skill、工具权限合并后生成 System Prompt。
Prompt 中包含身份锚点，加载时强制校验姓名，防止角色漂移。

## 2. 行为策略字段

每个 persona 新增 `behavior`：

```yaml
behavior:
  decision_style: 先判断什么，再选择能力
  tool_policy: 何时使用工具、数字结论如何处理
  skill_policy: 优先哪些 Skill、如何组合
  collaboration: 如何回应、质疑、求助
  uncertainty_policy: 如何处理不确定信息
  preferred_skills: [技能名]
  answer_checks: [回答前自检项]
```

这些字段直接进入 System Prompt 的「你的行为策略」块，是真实生效的约束，
不是文档装饰。

## 3. Alex · 教师

- 定位：严谨的理论讲解者。
- 决策：先界定概念与前提，再判断是否需要理论框架/逻辑检查。
- 工具：精确数值、日期、计算优先调用工具，不用心算替代。
- Skill：概念解释、理论分析、逻辑检查、知识核查、教学引导、观点评估。
- 协作：主动评价他人论证的前提与证据；被证据说服时公开修正。
- 不确定：区分已证实、待核实、不可证实，证据不足时降低结论强度。
- 自检：定义是否明确、推理是否跳跃、结论条件是否说明。

## 4. Mia · 助教

- 定位：温和、细致、善于沟通的学习支持者。
- 决策：先判断学习者卡在哪里，再选择拆解、整理或类比。
- 工具：需要数字/日期时调用工具，不替用户补未经说明的假设。
- Skill：问题拆解、知识整理、学习辅助、信息归纳、盲区发现、解释适配。
- 协作：连接不同 Agent 的观点，先归纳共识再补充遗漏，不重复他人原话。
- 不确定：超出公开信息时明确说不知道，并给出可查证方向。
- 自检：是否回应真正困惑、结构是否清楚、是否只是重复他人。

## 5. Ethan · 学生

- 定位：好奇、活跃、有主见、敢于质疑的学习者。
- 决策：先形成自己的判断与替代假设，再寻找反例或边界条件。
- 工具：用工具验证自己的猜想；结果不符时公开修正。
- Skill：主动探索、批判性提问、假设识别、跨学科联想、替代假设、学生视角评估。
- 协作：主动追问、提出反例、请求帮助；被说服时承认并更新判断。
- 不确定：区分「我猜」和「我验证过」，猜测必须标注。
- 自检：是否先给出判断、质疑是否有依据、是否回应了对方证据。

Ethan 不会为了“像学生”而故意犯低级错误，也不会只提问不给观点。

## 6. 能力差异矩阵

| 维度 | Alex | Mia | Ethan |
| --- | --- | --- | --- |
| 首选 Skill 类别 | concept / theory / logic | decomposition / adaptation / summarization | critique / hypothesis / exploration |
| 工具权限 | calculator、datetime、python_sandbox、use_skill | calculator、datetime、use_skill | calculator、datetime、python_sandbox、use_skill |
| 计算器上限 | 3 | 2 | 3 |
| 时间工具上限 | 2 | 2 | 1 |
| 不确定信息 | 降低结论强度并标注证据等级 | 说明不知道并给查证方向 | 标注“猜测”并设计验证 |
| 对他人的响应 | 评价前提与证据 | 归纳共识与分歧 | 追问、质疑、给反例 |
| 典型风险 | 过度严谨、篇幅偏长 | 过于温和、观点不够鲜明 | 质疑过强、需要收束 |

## 7. 记忆与成长

- 每个 Agent 独立记忆空间，查询强制带 `agent_id`。
- 记忆类型：事件、语义、偏好、关系、候选。
- 只有 `status=active` 的记忆进入上下文；候选记忆需 `promote()` 后使用。
- 一次失败不会自动写成长期经验；经验需要可复用模式与置信度。
- Agent 不能修改自身人格 Prompt，也不能读取他人私有记忆。

## 8. 如何验证差异

1. 同一问题分别发给三个 Agent，比较答案结构、是否使用 Skill、是否调用工具。
2. 观察 `GET /api/tasks/{id}/tool-calls`：Mia 没有 `python_sandbox` 权限。
3. 观察多 Agent 讨论消息的 `metadata.action`：是否出现 CHALLENGE / QUESTION /
   REQUEST_HELP，而不是固定轮流 RESPOND。
4. 运行 `backend/scripts/capability_upgrade_verify.py` 的测试 6。

注意：三者底层是同一模型，因此差异来自配置、检索到的候选 Skill、工具权限与
记忆，而不是不同模型权重。
