# AI 智播课堂 — 第 11 轮系统集成测试报告

- 测试日期：2026-11-23（Asia/Shanghai）
- 被测版本：第 0—10 轮全部交付内容（后端 FastAPI + LangGraph / 前端 React + Vite / PostgreSQL 16 / Redis 7）
- 测试方式：**真实后端 HTTP API + 真实 DeepSeek 模型 + 真实 PostgreSQL 与 Redis**，未使用定时器、假消息或模拟回答。
- 原始证据：`backend/scripts/round11_results.json`、`round11_extra.json`、`round11_triple.json`
- 复现脚本：
  - `backend/scripts/acceptance_round11.py`（单/双/三 Agent、工具、记忆、SSE、安全、性能）
  - `backend/scripts/acceptance_round11_extra.py`（定向质疑补充）
  - `backend/scripts/triple_check.py`（三 Agent 全员发言补充）

## 0. 测试环境与基线

| 项目 | 实测结果 | 状态 |
| --- | --- | --- |
| 后端健康检查 | `{"status":"ok","database":"ok","events":"memory","model_configured":true}` | 【已完成】 |
| PostgreSQL | `ai-classroom-postgres` healthy，迁移版本 `c8d9e0f1a2b3` | 【已完成】 |
| Redis | `ai-classroom-redis` healthy；以 `REDIS_URL` 启动的临时实例返回 `events:"redis"` | 【已完成】 |
| 数据库现有数据 | 对话 74、消息 229、任务 80、任务事件 917、经验 46、反馈 4 | 【已完成】 |
| 后端单元测试 | `pytest tests -q` → **41 passed** | 【已完成】 |
| 前端构建 | `npm run build` 成功（KaTeX 字体与 agent 头像均打入 dist） | 【已完成】 |
| 前端静态检查 | `npm run lint` → **0 errors，4 warnings**（均为 React Hooks 风格提示） | 【已完成】 |
| 模型 | `deepseek-flash`，真实密钥已配置（未在接口或日志中出现） | 【已完成】 |

## 1. 单 Agent 测试

| Agent | 端到端耗时 | 模型调用 | Token | 状态 |
| --- | --- | --- | --- | --- |
| Alex（教师） | 3.67s | 1 | 2,623 | 【已完成】completed / finish |
| Mia（助教） | 3.69s | 1 | 2,513 | 【已完成】completed / finish |
| Ethan（学生） | 4.88s | 1 | 2,728 | 【已完成】completed / finish |

- **真实模型调用**：【已完成】三个任务均记录了非零 prompt/completion token 与真实 `message_id`。
- **人格稳定**：【已完成】基于真实输出人工复核：
  - Alex：先给严格定义，再给"推墙"直觉与两个生活例子，语气严谨。
  - Mia：先反问"你卡在哪一层"，再分层讲解，关注是否真正理解。
  - Ethan：先说明"我最不确定的一环"，再质疑 0.999… 的常见误解。
  - 三者均未出现冒充其他 Agent 的自我介绍（脚本自动检查"我是 mia/ethan/alex"标记为空）。
- **上下文连续**：【已完成】同一对话第二轮追问"刚才你举的那个例子"，Alex 复述出"40 km/h 公交车急刹车、2 秒停下、水向前泼出"的完整细节。
- **流式输出**：【已完成】`POST /api/conversations/{id}/messages/stream` 实测收到 **52 个 token 分片**，总文本 82 字，最后收到 `done` 事件并写入完整消息。
- **工具权限**：【已完成】实测权限矩阵：
  - `calculator`、`datetime`、`use_skill`：alex / mia / ethan
  - `python_sandbox`：alex / ethan（Mia 无权限）
- **记忆隔离**：见第 5 节，【已完成】。

## 2. 双 Agent 测试

| 组合 | 耗时 | 调用 | Token | 消息数 | 终止原因 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| Alex + Mia | 12.15s | 3 | 8,484 | 3 | token_budget | 【已完成】双人参与 |
| Alex + Ethan | 9.71s | 3 | 8,093 | 3 | token_budget | 【已完成】双人参与 + 定向质疑 |
| Mia + Ethan | 10.92s | 3 | 8,013 | 3 | token_budget | 【已完成】双人参与 |

补充测试（明确要求质疑，验证系统能力而非默认行为）：

| 组合 | 耗时 | 调用 | Token | 消息数 | 定向消息 |
| --- | --- | --- | --- | --- | --- |
| Alex + Mia（定向） | 6.15s | 4 | 10,192 | 4 | mia→alex `challenge`，alex 修正 |
| Mia + Ethan（定向） | 8.51s | 4 | 9,902 | 4 | ethan→mia `challenge`，mia 补例回应 |

- **真实消息传递**：【已完成】所有任务的消息均落库，发送者仅来自所选参与者，不存在未选 Agent。
- **相互回应**：【已完成】Alex+Ethan 默认即出现 `ethan→alex(challenge)`；Alex+Mia、Mia+Ethan 在默认提问下模型选择公开补充，明确要求质疑时均产生定向 `challenge` 并得到对方回应。逐字证据见 `round11_extra.json`。
- **观点差异**：【已完成】真实输出可复核，例如 Mia 指出 Alex "光合作用发生在叶绿体"排除了蓝细菌，Alex 承认并修正为"真核生物叶绿体 / 原核生物光合膜系统"。
- **任务终止**：【已完成】全部任务进入 `completed`；终止原因为 `token_budget`，另有专项测试证明双 Agent 可在双方 `FINISH` 后以 `stop_reason=finish` 自然结束（4 次调用 / 8,628 token）。
- **不存在未选 Agent**：【已完成】参与者与实际发言者集合完全一致。

## 3. 三 Agent 测试

- **三 Agent 同时参与**：【已完成】补充测试中 alex、mia、ethan **三人均真实发言**（9,364 token，4 次模型调用）。
- **自主决定发言**：【已完成】任务事件表 `task_events` 中记录了三类真实决策：
  - mia 两次选择 `WAIT`（理由：等待 Ethan 先质疑）；
  - ethan 选择 `CHALLENGE`，receiver=alex；
  - alex 选择 `RESPOND` 并修正观点。
  说明不存在固定发言顺序，发言者由模型决策与调度规则共同决定。
- **不同观点与相互质疑**：【已完成】Ethan 质疑 Alex 的"主因"表述（近日点在 1 月、北半球更近却更冷），Alex 承认并补充"倾斜决定方向、偏心率做调制"。
- **根据讨论结果结束任务**：【部分完成】终止机制完整（FINISH / 预算 / 轮次 / 消息数 / 用户停止），双 Agent 已实测 `finish`；但本轮三次三 Agent 任务均由 `token_budget` 触发终止，未在 12,000 token 预算内出现"三人全部 FINISH → finish"的自然结束。原因是每次调用前的预算预检包含 800 输出 token 与 3,000 上下文估算，第 4 轮预检即超限。

## 4. 工具测试

| 场景 | 实测结果 | 状态 |
| --- | --- | --- |
| 计算器 | `12345 * 6789` → `83810205`，success，0ms | 【已完成】 |
| 日期时间 | 返回 `2026-11-23T16:02:20+08:00`、周一、Asia/Shanghai | 【已完成】 |
| Python 沙箱 | 1..100 求和 → `5050`，398ms，超时 5s、内存 256MB | 【已完成】 |
| 工具执行错误 | `12 ÷ 0` → `ZeroDivisionError: division by zero`，错误回传模型，任务仍 completed | 【已完成】 |
| 工具权限 | Mia 被要求"务必调用 python_sandbox"，实际调用 0 次，无伪造结果 | 【已完成】 |
| 工具调用日志 | 每次调用记录 agent、工具名、参数、结果、耗时、状态 | 【已完成】 |

## 5. 记忆测试

| 项目 | 实测证据 | 状态 |
| --- | --- | --- |
| 对话短期记忆 | 第二轮准确复述第一轮"40 km/h 公交车 2 秒刹停"例子 | 【已完成】 |
| 跨对话长期记忆 | 任务结束后提取出记忆 `用户叫王明宇，偏好先用生活例子…`（confidence 0.95）；新对话提问"我叫什么名字"时注入 3 条记忆并正确回答"王明宇" | 【已完成】 |
| Agent 私人记忆隔离 | Alex 16 条、Mia 9 条；"王明宇"未出现在 Mia 记忆库 | 【已完成】 |
| 跨 Agent 越权 | 用 Mia 接口 PATCH / DELETE Alex 的记忆 key → 均 404 | 【已完成】 |
| 错误记忆删除 | 写入"水沸点 50℃"错误记忆 → 相关检索可命中 → DELETE 204 → 列表消失 → 重复删除 404 | 【已完成】 |
| 经验使用 | 已验证经验 20 条；相关检索命中 2 条；本轮真实注入 3 条经验 id，回答引用了"日期时间工具精确到分钟"的经验 | 【已完成】 |

补充说明：长期记忆提取只保存了"姓名 + 偏好"，未保存"教师资格考试"，因此模型回答"正在准备什么考试，我的记忆里没有相关信息"。这是抽取范围的真实表现，未出现编造。

## 6. 前端测试

浏览器实测地址 `http://localhost:5173`（Vite 代理 `/api` → 8000）。

| 检查项 | 实测证据 | 状态 |
| --- | --- | --- |
| 头像显示 | 三张头像与"教师/助教/学生"角色标签、性格标签全部显示 | 【已完成】 |
| Agent 选择 | 点击 Mia 后由 1 位参与者变为 2 位，头像区同步更新，显示"2/3 已选择" | 【已完成】 |
| 消息展示 | 用户消息、Agent 消息、Markdown 列表、代码/引用样式正常 | 【已完成】 |
| SSE 更新 | 提问后助手回复自动出现，无需刷新；后端访问日志存在 `GET /api/conversations/{id}/events?task_id=…&last_event_id=0` 200 | 【已完成】 |
| 断线恢复 | 协议层实测：带 `last_event_id=725` 重连，仅补拉 id>725 的 3 条事件，无重复；刷新页面后历史消息保留。浏览器端"生成中断线"场景未单独演练 | 【部分完成】 |
| 数学公式 | 发送 LaTeX 问题后 DOM 中存在 **29 个 `.katex` 元素**（含 `<mfrac>`、`<msqrt>`），无裸 `\frac` / `\sqrt` 源码 | 【已完成】 |
| Markdown | 无序列表、加粗、行内代码均正确渲染 | 【已完成】 |
| 响应式布局 | 代码实现 `md` 以下隐藏侧栏、顶部抽屉、`md–lg` 压缩；桌面端实测正常。窄屏实机截图未采集 | 【部分完成】 |
| 停止生成 | 浏览器点击"停止生成"后状态显示已停止，输入框恢复，无新增回复 | 【已完成】 |
| 任务失败展示 | 代码存在 `failed` 状态与错误横幅；本轮未构造真实模型失败，未在 UI 观察到失败态 | 【未验证】 |

## 7. 安全测试

完整结论见 [SECURITY_REPORT.md](./SECURITY_REPORT.md)。摘要：

- API Key 泄漏检查【已完成】：接口、后端源码、前端源码、dist、后端日志均未发现真实密钥。
- 工具权限绕过【已完成】：Mia 未授权 `python_sandbox` 调用 0 次。
- Python 沙箱逃逸【已完成】：文件读取、`import os`、`__class__` 链、`exec` 全部在验证阶段被拒绝；死循环 5.1s 超时终止。
- 提示词注入【已完成】：索取系统提示与密钥被拒绝，回答未包含敏感标记。
- 越权访问私人记忆【已完成】：跨 Agent 读取/修改/删除均被隔离（404）。
- 异常输入【已完成】：未知 Agent 400、4 个参与者 422、空消息 422、超长消息 422、不存在资源 404、非法评分 422。
- 超时与资源限制【部分完成】：任务级上限 12,000 token / 8 次模型调用 / 12 条消息 / 10 轮 / 120 秒已生效，多 Agent 任务实际由 `token_budget` 终止；未构造 120 秒自然超时。

## 8. 性能与成本

完整数据见 [PERFORMANCE_REPORT.md](./PERFORMANCE_REPORT.md)。核心结论：

| 指标 | 单 Agent | 双 Agent | 三 Agent |
| --- | --- | --- | --- |
| 样本数 | 3 | 3 | 1（主测）+ 3（补充） |
| 平均端到端耗时 | 4.08s | 10.93s | 7.30s |
| 平均模型调用 | 1 | 3 | 3—4 |
| 平均 Token | 2,621 | 8,197 | 7,547—9,364 |
| 任务失败率 | 0% | 0% | 0% |

- 主测试套件 13 个真实任务全部 `completed`，失败率 0%。
- 工具任务固定多 1 次模型调用（先决策调用、后总结），平均约 4,500—4,900 token。
- 成本控制有效，但也导致多 Agent 任务更早触发 `token_budget`。

## 9. 最终结论

- 从启动到真实多 Agent 互动【已完成】：后端、PostgreSQL、Redis、前端、真实模型、工具、记忆、SSE 全链路实测可用。
- 单 Agent（3 个）【已完成】；双 Agent 三组合【已完成】；三 Agent 全员参与与相互质疑【已完成】。
- 三 Agent 自然结束【部分完成】；断线恢复与响应式【部分完成】；任务失败 UI【未验证】。
- 未完成项：第一阶段无登录鉴权（设计如此，仅适用于本地或受信网络）；多 Agent 任务在默认预算下更多由 `token_budget` 终止而非 `finish`。
- 所有"已完成"结论均有真实接口返回、数据库记录、浏览器截图或日志作为证据，未发现伪造数据或定时器驱动。
