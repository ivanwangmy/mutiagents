from __future__ import annotations

import json
import operator
import re
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.agents.config import AgentProfile
from app.agents.registry import registry
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.events import event_broker
from app.memory.experience import experience_manager
from app.memory.manager import memory_manager
from app.memory.runtime import memory_runtime
from app.messaging.bus import message_bus
from app.model.base import ModelError
from app.model.registry import model_registry
from app.models import TaskEvent
from app.skills.registry import skills_registry
from app.tools.base import ToolContext
from app.tools.executor import tool_executor
from app.tools.permissions import tool_permission_manager
from app.utils.tokens import estimate_messages_tokens

logger = get_logger(__name__)

ACTIONS = {
    "RESPOND",
    "ASK_USER",
    "MESSAGE_AGENT",
    "REQUEST_HELP",
    "CHALLENGE",
    "USE_TOOL",
    "WAIT",
    "FINISH",
}
DIRECTED_ACTIONS = {"MESSAGE_AGENT", "REQUEST_HELP", "CHALLENGE", "HANDOFF"}
SPEAKING_ACTIONS = {"RESPOND", "MESSAGE_AGENT", "REQUEST_HELP", "CHALLENGE", "HANDOFF"}

MAX_CONTENT_CHARS = 1600
MAX_TRANSCRIPT_MESSAGES = 12
# 预算预检的固定余量，覆盖消息封装等未计入估算的开销
BUDGET_SAFETY_TOKENS = 200

PROTOCOL = """## 多人课堂协作协议
你是本次课堂的参与者之一，参与者只有：{participants}。
你不能假设存在其他 Agent，也不能代替别人发言。
你必须根据当前讨论内容自主决定本轮行为，不存在固定发言顺序。

可选 action：
- RESPOND：直接回应用户或补充观点。
- ASK_USER：向用户提出一个明确问题。
- MESSAGE_AGENT：向另一位参与者发送消息。
- REQUEST_HELP：请另一位参与者补充或协助。
- CHALLENGE：指出另一位参与者观点中的具体分歧并说明理由。
- USE_TOOL：调用工具获取真实结果；只允许下列工具：{tools}
- WAIT：本轮没有新增价值，不发言。
- FINISH：认为讨论已经充分，结束自己的参与。

输出要求：只输出一个 JSON 对象，不要 markdown 代码块，不要额外解释：
{{"action":"RESPOND","receiver":null,"content":"你的发言正文","reason":"一句话说明为何这样选择","tool":null,"reply_to":null,"next_speaker":null}}

规则：
1. 需要发言时必须给出实质内容，并尽量引用记录中的具体观点，不要泛泛而谈。
2. 没有新增价值时用 WAIT；讨论已充分时用 FINISH。不要为了发言而发言。
2.1 质疑某个具体观点时用 CHALLENGE 并填写 receiver；向具体参与者提问用 QUESTION；
    需要他人能力协助时用 REQUEST_HELP。不要把所有发言都标成 RESPOND。
3. MESSAGE_AGENT / REQUEST_HELP / CHALLENGE 必须填写 receiver，且 receiver 必须是参与者。
4. USE_TOOL 时 tool 填写 {{"name":"工具名","arguments":{{...}}}}，content 可以为空。
5. reply_to 填写你要回应的消息编号（如 m3），没有就填 null。
6. next_speaker 可填写你认为最适合接话的参与者 id；没有明确判断时填 null，由调度器按参与度选择。不要机械轮流。
7. 保持你固定的人格与身份，不要冒充其他参与者。"""


class DiscussionState(TypedDict, total=False):
    question: str
    messages: Annotated[list[dict[str, Any]], operator.add]
    actions: Annotated[list[dict[str, Any]], operator.add]
    turn: int
    model_calls: int
    prompt_tokens: int
    completion_tokens: int
    sent_count: int
    spoken_counts: dict[str, int]
    finished_agents: list[str]
    tool_call_counts: dict[str, int]
    consecutive_waits: int
    active_agent: str
    stop_reason: str
    started_at: float


@dataclass(slots=True)
class DiscussionResult:
    turns: int
    sent_messages: int
    model_calls: int
    prompt_tokens: int
    completion_tokens: int
    stop_reason: str
    actions: list[dict[str, Any]] = field(default_factory=list)


def _extract_json(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _salvage_content(text: str) -> str | None:
    """JSON 被 max_tokens 截断时，尽量取出 content 字段的真实正文。"""
    match = re.search(r'"content"\s*:\s*"', text)
    if match is None:
        return None
    rest = text[match.end() :]
    chars: list[str] = []
    escaped = False
    for char in rest:
        if escaped:
            chars.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            chars.append(char)
            continue
        if char == '"':
            break
        chars.append(char)
    raw = "".join(chars).rstrip(' ,}')
    try:
        return json.loads(f'"{raw}"').strip() or None
    except json.JSONDecodeError:
        return raw.replace("\\n", "\n").replace('\\"', '"').strip() or None


def parse_decision(
    text: str, agent_id: str, participants: list[str]
) -> dict[str, Any]:
    """解析 Agent 的结构化决策；解析失败时回退为真实文本发言，绝不编造。"""
    raw = _extract_json(text)
    fallback = raw is None
    data = raw or {}
    action = str(data.get("action", "")).strip().upper()
    if action == "SPEAK":
        action = "RESPOND"
    if action == "MESSAGE":
        action = "MESSAGE_AGENT"
    if action not in ACTIONS:
        action = "RESPOND" if text.strip() else "WAIT"

    content = str(data.get("content") or "").strip()[:MAX_CONTENT_CHARS]
    if not content and fallback and text.strip():
        content = (_salvage_content(text) or text.strip())[:MAX_CONTENT_CHARS]

    receiver = data.get("receiver")
    receiver = receiver.strip().lower() if isinstance(receiver, str) else None
    if action in DIRECTED_ACTIONS:
        if receiver not in participants or receiver == agent_id:
            action = "RESPOND"
            receiver = None
    else:
        # 只有定向动作才允许 receiver，避免 RESPOND 携带残留接收者
        receiver = None

    if action in SPEAKING_ACTIONS and not content:
        action = "WAIT"

    tool = data.get("tool")
    if action == "USE_TOOL":
        if not isinstance(tool, dict) or not tool.get("name"):
            action = "RESPOND" if content else "WAIT"
        elif not isinstance(tool.get("arguments"), dict):
            tool = {"name": tool["name"], "arguments": {}}
    else:
        tool = None

    reply_to = data.get("reply_to")
    reply_to = reply_to.strip() if isinstance(reply_to, str) else None

    next_speaker = data.get("next_speaker")
    next_speaker = next_speaker.strip().lower() if isinstance(next_speaker, str) else None
    if next_speaker not in participants or next_speaker == agent_id:
        next_speaker = None

    return {
        "action": action,
        "receiver": receiver,
        "content": content,
        "reason": str(data.get("reason") or "")[:200],
        "tool": tool,
        "reply_to": reply_to,
        "next_speaker": next_speaker,
        "fallback": fallback,
    }


def pick_opening(participants: list[str], question: str) -> str:
    """根据问题类型选择首位发言者；不是固定轮流。"""
    text = question.lower()
    scores = {"alex": 0, "mia": 0, "ethan": 0}
    if any(k in text for k in ("定义", "概念", "原理", "机制", "为什么", "理论", "分析", "区别")):
        scores["alex"] += 3
    if any(k in text for k in ("不懂", "不会", "怎么学", "步骤", "总结", "整理", "帮我", "基础", "通俗")):
        scores["mia"] += 3
    if any(k in text for k in ("质疑", "反例", "真的", "是否", "问题", "追问", "缺点", "局限")):
        scores["ethan"] += 3
    order = {agent_id: index for index, agent_id in enumerate(participants)}
    return max(participants, key=lambda item: (scores.get(item, 0), -order[item]))


class DiscussionRunner:
    """Discussion Manager + LangGraph 动态调度。

    管理器只负责预算、参与者与路由，不生成任何 Agent 发言内容。
    """

    def __init__(
        self,
        *,
        conversation_id: str,
        task_id: str,
        question: str,
        participants: list[str],
    ) -> None:
        self.conversation_id = conversation_id
        self.task_id = task_id
        self.question = question
        self.participants = participants
        self._names = {agent_id: registry.get(agent_id).name for agent_id in participants}
        self._tool_max_calls = {
            agent_id: tool_permission_manager.max_calls_for(registry.get(agent_id))
            for agent_id in participants
        }

    # ---------- manager ----------
    def check_budget(self, state: DiscussionState) -> str | None:
        if state.get("turn", 0) >= settings.task_max_turns:
            return "max_turns"
        if state.get("model_calls", 0) >= settings.task_max_model_calls:
            return "max_model_calls"
        if state.get("sent_count", 0) >= settings.task_max_messages:
            return "max_messages"
        spent = state.get("prompt_tokens", 0) + state.get("completion_tokens", 0)
        if spent >= settings.task_token_budget:
            return "token_budget"
        started = state.get("started_at") or time.monotonic()
        if time.monotonic() - started >= settings.task_max_seconds:
            return "timeout"
        return None

    def next_agent(
        self, state: DiscussionState, after: str, preferred: str | None = None
    ) -> str | None:
        finished = set(state.get("finished_agents") or [])
        if preferred in self.participants and preferred not in finished and preferred != after:
            return preferred
        spoken = state.get("spoken_counts") or {}
        order = {agent_id: index for index, agent_id in enumerate(self.participants)}
        candidates = [
            agent_id
            for agent_id in self.participants
            if agent_id != after and agent_id not in finished
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda item: (spoken.get(item, 0), order[item]))

    # ---------- prompt ----------
    def _transcript(self, messages: list[dict[str, Any]]) -> tuple[str, dict[str, str]]:
        recent = messages[-MAX_TRANSCRIPT_MESSAGES:]
        aliases: dict[str, str] = {}
        lines: list[str] = []
        for index, message in enumerate(recent, start=1):
            alias = f"m{index}"
            aliases[alias] = message["id"]
            if message.get("sender_type") == "user":
                who = "用户"
            else:
                sender_id = message.get("sender_agent_id") or ""
                who = self._names.get(sender_id, sender_id or "参与者")
            content = str(message.get("content") or "").strip()
            if len(content) > 320:
                content = content[:320] + "…"
            receiver = message.get("receiver_agent_id")
            target = f" → {self._names.get(receiver, receiver)}" if receiver else ""
            lines.append(
                f"[{alias}] {who}{target}（{message.get('message_type')}）：{content}"
            )
        return "\n".join(lines) or "（尚无发言）", aliases

    def _system_prompt(
        self,
        profile: AgentProfile,
        memories: list[dict[str, Any]] | None = None,
        experiences: list[dict[str, Any]] | None = None,
    ) -> str:
        tools = tool_permission_manager.tools_for(profile)
        tool_lines = "；".join(
            f"{name}（{tool.description[:60]}）" for name, tool in tools.items()
        ) or "无"
        participants = "、".join(f"{self._names[item]}（{item}）" for item in self.participants)
        participants += "，以及用户"
        memory_block = ""
        if memories:
            rows = "\n".join(
                f"- （{item.get('memory_type')}）{item.get('content')}" for item in memories
            )
            memory_block = (
                f"\n\n## 你记得的相关长期记忆（仅你私有）\n{rows}\n"
                "只在与当前问题相关时使用；无关或不确定时忽略。"
            )
        experience_block = ""
        if experiences:
            rows = "\n".join(
                f"- （{item.get('experience_type')}）{item.get('content')}"
                for item in experiences
            )
            experience_block = (
                f"\n\n## 可参考的已验证经验（仅你私有）\n{rows}\n"
                "仅在相关时借鉴，用于改善问题理解、交流方式、工具使用与协作策略；"
                "经验不改变你的核心 System Prompt、工具权限与安全规则，"
                "也不得据此修改其他 Agent 的配置。"
            )
        skill_block = skills_registry.render_candidates(profile, self.question)
        return (
            f"{profile.system_prompt}{skill_block}{memory_block}{experience_block}\n\n"
            + PROTOCOL.format(participants=participants, tools=tool_lines)
        )

    def _request_messages(
        self,
        profile: AgentProfile,
        state: DiscussionState,
        memories: list[dict[str, Any]] | None = None,
        experiences: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        transcript, aliases = self._transcript(state.get("messages") or [])
        spoken = (state.get("spoken_counts") or {}).get(profile.id, 0)
        user = (
            f"## 用户当前问题\n{self.question}\n\n"
            f"## 公开讨论记录\n{transcript}\n\n"
            f"## 你的状态\n你已经发言 {spoken} 次。"
            f"本轮请自主选择 action；记住只输出 JSON。"
        )
        return [
            {
                "role": "system",
                "content": self._system_prompt(profile, memories, experiences),
            },
            {"role": "user", "content": user},
        ], aliases

    # ---------- persistence ----------
    async def _record_decision(
        self, agent_id: str, decision: dict[str, Any], turn: int
    ) -> None:
        try:
            async with SessionLocal() as session:
                session.add(
                    TaskEvent(
                        event_type="agent.decision",
                        conversation_id=self.conversation_id,
                        task_id=self.task_id,
                        agent_id=agent_id,
                        payload={
                            "action": decision["action"],
                            "receiver": decision.get("receiver"),
                            "reason": decision.get("reason", ""),
                            "turn": turn,
                            "fallback": decision.get("fallback", False),
                        },
                    )
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001 - 审计失败不影响讨论
            logger.warning("决策事件写入失败：%s", exc)

    async def _publish(
        self,
        *,
        agent_id: str,
        message_type: str,
        content: str,
        receiver: str | None,
        decision: dict[str, Any],
        reply_to: str | None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = {
            "action": decision["action"],
            "reason": decision.get("reason", ""),
            "model": registry.get(agent_id).runtime.model,
        }
        if extra:
            metadata.update(extra)
        await self._emit_status(agent_id, "speaking", "正在发言")
        bus_message = await message_bus.publish(
            conversation_id=self.conversation_id,
            task_id=self.task_id,
            sender_agent_id=agent_id,
            receiver_agent_id=receiver,
            message_type=message_type,
            content=content,
            reply_to_message_id=reply_to,
            metadata=metadata,
        )
        return bus_message.to_dict()

    # ---------- realtime events（只发送公开可观测信息，不含思维链） ----------
    async def _emit_status(self, agent_id: str, status: str, detail: str | None = None) -> None:
        payload: dict[str, Any] = {"status": status}
        if detail:
            payload["detail"] = detail
        await event_broker.emit(
            "agent_status_changed",
            conversation_id=self.conversation_id,
            task_id=self.task_id,
            agent_id=agent_id,
            payload=payload,
        )

    async def _emit_agent_started(self, profile: AgentProfile) -> None:
        await event_broker.emit(
            "agent_started",
            conversation_id=self.conversation_id,
            task_id=self.task_id,
            agent_id=profile.id,
            payload={
                "name": profile.name,
                "role_label": profile.role_label,
                "avatar": profile.avatar,
                "theme_color": profile.theme_color,
            },
        )

    async def _emit_message_event(
        self, agent_id: str, message_type: str, message: dict[str, Any]
    ) -> None:
        """按消息类型补发 agent_question / agent_challenge / agent_handoff。"""
        receiver = message.get("receiver_agent_id")
        if message_type == "question":
            await event_broker.emit(
                "agent_question",
                conversation_id=self.conversation_id,
                task_id=self.task_id,
                agent_id=agent_id,
                payload={
                    "message_id": message["id"],
                    "content": message.get("content", ""),
                    "receiver_agent_id": None,
                },
            )
        elif message_type == "challenge":
            await event_broker.emit(
                "agent_challenge",
                conversation_id=self.conversation_id,
                task_id=self.task_id,
                agent_id=agent_id,
                payload={
                    "message_id": message["id"],
                    "content": message.get("content", ""),
                    "receiver_agent_id": receiver,
                },
            )
        elif receiver and message_type in {"message", "handoff", "request_help"}:
            await event_broker.emit(
                "agent_handoff",
                conversation_id=self.conversation_id,
                task_id=self.task_id,
                agent_id=agent_id,
                payload={
                    "message_id": message["id"],
                    "content": message.get("content", ""),
                    "receiver_agent_id": receiver,
                },
            )

    # ---------- graph ----------
    def build_graph(self):
        builder = StateGraph(DiscussionState)
        builder.add_node("dispatch", self._dispatch)
        builder.add_node("agent_turn", self._agent_turn)
        builder.add_edge(START, "dispatch")
        return builder.compile(checkpointer=memory_runtime.checkpointer)

    async def _dispatch(self, state: DiscussionState) -> Command:
        reason = self.check_budget(state)
        if reason:
            return Command(goto=END, update={"stop_reason": reason})
        if not self.participants:
            return Command(goto=END, update={"stop_reason": "no_participants"})
        opening = pick_opening(self.participants, self.question)
        return Command(
            goto="agent_turn",
            update={
                "active_agent": opening,
                "started_at": state.get("started_at") or time.monotonic(),
            },
        )

    async def _agent_turn(self, state: DiscussionState) -> Command:
        agent_id = state.get("active_agent") or self.participants[0]
        reason = self.check_budget(state)
        if reason:
            return Command(goto=END, update={"stop_reason": reason})

        profile = registry.get(agent_id)
        await self._emit_agent_started(profile)
        await self._emit_status(agent_id, "thinking", "正在思考")
        provider = model_registry.get(
            model=profile.runtime.model,
            temperature=profile.runtime.temperature,
            max_tokens=min(profile.runtime.max_output_tokens, settings.max_output_tokens),
        )
        memories = await memory_manager.retrieve(agent_id, self.question)
        memory_keys = [item["key"] for item in memories]
        experiences = await experience_manager.retrieve(agent_id, self.question)
        experience_ids = [item["id"] for item in experiences]
        messages, aliases = self._request_messages(
            profile, state, memories, experiences
        )
        max_tokens = min(profile.runtime.max_output_tokens, settings.max_output_tokens)
        spent = state.get("prompt_tokens", 0) + state.get("completion_tokens", 0)
        projected = estimate_messages_tokens(messages) + max_tokens + BUDGET_SAFETY_TOKENS
        if spent + projected > settings.task_token_budget:
            return Command(goto=END, update={"stop_reason": "token_budget"})
        try:
            response = await provider.complete(
                messages,
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
                temperature=profile.runtime.temperature,
            )
        except ModelError as exc:
            if exc.kind != "api_error":
                raise
            response = await provider.complete(
                messages,
                max_tokens=max_tokens,
                temperature=profile.runtime.temperature,
            )

        turn = state.get("turn", 0) + 1
        update: dict[str, Any] = {
            "turn": turn,
            "model_calls": state.get("model_calls", 0) + 1,
            "prompt_tokens": state.get("prompt_tokens", 0) + response.usage.prompt_tokens,
            "completion_tokens": state.get("completion_tokens", 0)
            + response.usage.completion_tokens,
            "tool_call_counts": dict(state.get("tool_call_counts") or {}),
        }
        decision = parse_decision(response.content, agent_id, self.participants)

        tool_meta: dict[str, Any] | None = None
        if decision["action"] == "USE_TOOL":
            decision, followup_usage, tool_meta = await self._run_tool(
                profile, state, messages, response.content, decision, update
            )
            update["model_calls"] += 1
            update["prompt_tokens"] += followup_usage[0]
            update["completion_tokens"] += followup_usage[1]

        await self._record_decision(agent_id, decision, turn)
        update["actions"] = [
            {
                "agent": agent_id,
                "turn": turn,
                "action": decision["action"],
                "receiver": decision.get("receiver"),
                "reason": decision.get("reason", ""),
            }
        ]

        finished = list(state.get("finished_agents") or [])
        spoken = dict(state.get("spoken_counts") or {})
        sent_count = state.get("sent_count", 0)
        consecutive_waits = state.get("consecutive_waits", 0)
        reply_to = aliases.get(decision.get("reply_to") or "", decision.get("reply_to"))
        action = decision["action"]

        if action == "WAIT":
            await self._emit_status(agent_id, "waiting", "本轮不发言，等待其他参与者")
            update["consecutive_waits"] = consecutive_waits + 1
            update["spoken_counts"] = spoken
            if consecutive_waits + 1 >= len(self.participants):
                update["stop_reason"] = "no_participant_willing"
                return Command(goto=END, update=update)
            nxt = self.next_agent(state, agent_id, decision.get("next_speaker"))
            if nxt is None:
                update["stop_reason"] = "finish"
                return Command(goto=END, update=update)
            update["active_agent"] = nxt
            return Command(goto="agent_turn", update=update)

        if action == "FINISH":
            if agent_id not in finished:
                finished.append(agent_id)
            update["finished_agents"] = finished
            update["spoken_counts"] = spoken
            update["consecutive_waits"] = 0
            if decision.get("content"):
                published = await self._publish(
                    agent_id=agent_id,
                    message_type="conclusion",
                    content=decision["content"],
                    receiver=None,
                    decision=decision,
                    reply_to=reply_to,
                )
                update["messages"] = [published]
                sent_count += 1
                update["sent_count"] = sent_count
            await self._emit_status(agent_id, "completed", "已结束本轮参与")
            await event_broker.emit(
                "agent_completed",
                conversation_id=self.conversation_id,
                task_id=self.task_id,
                agent_id=agent_id,
                payload={"status": "completed"},
            )
            if all(item in finished for item in self.participants):
                update["stop_reason"] = "finish"
                return Command(goto=END, update=update)
            nxt = self.next_agent(state, agent_id, decision.get("next_speaker"))
            if nxt is None:
                update["stop_reason"] = "finish"
                return Command(goto=END, update=update)
            update["active_agent"] = nxt
            return Command(goto="agent_turn", update=update)

        if action == "ASK_USER":
            published = await self._publish(
                agent_id=agent_id,
                message_type="question",
                content=decision["content"],
                receiver=None,
                decision=decision,
                reply_to=reply_to,
            )
            update["messages"] = [published]
            update["sent_count"] = sent_count + 1
            update["spoken_counts"] = {**spoken, agent_id: spoken.get(agent_id, 0) + 1}
            update["stop_reason"] = "waiting_user"
            await self._emit_message_event(agent_id, "question", published)
            await self._emit_status(agent_id, "waiting", "等待用户回答")
            return Command(goto=END, update=update)

        message_type = {
            "RESPOND": "response",
            "MESSAGE_AGENT": "handoff" if action == "HANDOFF" else "message",
            "REQUEST_HELP": "request_help",
            "CHALLENGE": "challenge",
        }.get(action, "response")
        extra = {"tool": tool_meta, "memory_keys": memory_keys, "experience_ids": experience_ids}
        published = await self._publish(
            agent_id=agent_id,
            message_type=message_type,
            content=decision["content"],
            receiver=decision.get("receiver"),
            decision=decision,
            reply_to=reply_to,
            extra=extra,
        )
        update["messages"] = [published]
        update["sent_count"] = sent_count + 1
        update["spoken_counts"] = {**spoken, agent_id: spoken.get(agent_id, 0) + 1}
        update["consecutive_waits"] = 0
        await self._emit_message_event(agent_id, message_type, published)
        await self._emit_status(agent_id, "waiting", "等待其他 Agent 发言")

        nxt = self.next_agent(
            state, agent_id, decision.get("receiver") or decision.get("next_speaker")
        )
        if nxt is None:
            update["stop_reason"] = "finish"
            return Command(goto=END, update=update)
        update["active_agent"] = nxt
        return Command(goto="agent_turn", update=update)

    async def _run_tool(
        self,
        profile: AgentProfile,
        state: DiscussionState,
        messages: list[dict[str, Any]],
        raw_decision: str,
        decision: dict[str, Any],
        update: dict[str, Any],
    ) -> tuple[dict[str, Any], tuple[int, int], dict[str, Any]]:
        tool_spec = decision.get("tool") or {}
        name = str(tool_spec.get("name", ""))
        arguments = tool_spec.get("arguments") or {}
        call_id = f"{self.task_id}:{profile.id}:{update.get('turn', 0)}:{name}"
        tools = tool_permission_manager.tools_for(profile)
        context = ToolContext(
            agent_id=profile.id,
            task_id=self.task_id,
            conversation_id=self.conversation_id,
            call_counts=dict(state.get("tool_call_counts") or {}),
            max_calls=self._tool_max_calls.get(profile.id, {}),
        )
        await event_broker.emit(
            "agent_tool_call",
            conversation_id=self.conversation_id,
            task_id=self.task_id,
            agent_id=profile.id,
            payload={"call_id": call_id, "tool": name, "arguments": arguments},
        )
        await self._emit_status(profile.id, "tool_calling", f"调用工具 {name}")
        await event_broker.emit(
            "tool_started",
            conversation_id=self.conversation_id,
            task_id=self.task_id,
            agent_id=profile.id,
            payload={"call_id": call_id, "tool": name, "arguments": arguments},
        )
        if name == "use_skill":
            await event_broker.emit(
                "skill_selected",
                conversation_id=self.conversation_id,
                task_id=self.task_id,
                agent_id=profile.id,
                payload={
                    "call_id": call_id,
                    "skill": (arguments or {}).get("skill") if isinstance(arguments, dict) else None,
                    "inputs": (arguments or {}).get("input") if isinstance(arguments, dict) else None,
                },
            )
        result = await tool_executor.execute(
            name=name,
            arguments=arguments if isinstance(arguments, dict) else {},
            tool=tools.get(name),
            context=context,
            task_id=self.task_id,
            conversation_id=self.conversation_id,
            call_id=call_id,
        )
        if name == "use_skill":
            skill_payload = result.result if isinstance(result.result, dict) else {}
            await event_broker.emit(
                "skill_loaded" if result.ok else "skill_failed",
                conversation_id=self.conversation_id,
                task_id=self.task_id,
                agent_id=profile.id,
                payload={
                    "call_id": call_id,
                    "skill": skill_payload.get("skill")
                    or ((arguments or {}).get("skill") if isinstance(arguments, dict) else None),
                    "steps": skill_payload.get("steps") or [],
                    "required_inputs": skill_payload.get("required_inputs") or [],
                    "error": result.error,
                },
            )
            if result.ok:
                await event_broker.emit(
                    "skill_completed",
                    conversation_id=self.conversation_id,
                    task_id=self.task_id,
                    agent_id=profile.id,
                    payload={"call_id": call_id, "skill": skill_payload.get("skill")},
                )
        result_summary = json.dumps(result.to_payload(), ensure_ascii=False)[:500]
        await event_broker.emit(
            "tool_completed" if result.ok else "tool_failed",
            conversation_id=self.conversation_id,
            task_id=self.task_id,
            agent_id=profile.id,
            payload={
                "call_id": call_id,
                "tool": name,
                "ok": result.ok,
                "duration_ms": result.duration_ms,
                "error": result.error,
                "result": result_summary,
            },
        )
        await self._emit_status(profile.id, "thinking", "正在整理工具结果")
        update["tool_call_counts"] = context.call_counts
        followup = [
            *messages,
            {"role": "assistant", "content": raw_decision},
            {
                "role": "user",
                "content": (
                    "工具真实执行结果：\n"
                    + json.dumps(result.to_payload(), ensure_ascii=False)[:1500]
                    + "\n请基于该结果，用自然的课堂语言给出最终发言正文。"
                    "只输出正文，不要输出 JSON，不要编造工具未返回的数据。"
                ),
            },
        ]
        tool_meta = {
            "tool": name,
            "ok": result.ok,
            "error": result.error,
            "duration_ms": result.duration_ms,
        }
        max_tokens = min(profile.runtime.max_output_tokens, settings.max_output_tokens)
        spent = update["prompt_tokens"] + update["completion_tokens"]
        projected = estimate_messages_tokens(followup) + max_tokens + BUDGET_SAFETY_TOKENS
        if spent + projected > settings.task_token_budget:
            # 预算不足时不再发起模型调用，直接回传真实工具结果，避免编造
            content = (
                f"工具 {name} 的真实返回："
                + json.dumps(result.to_payload(), ensure_ascii=False)[:600]
            )
            return (
                {
                    **decision,
                    "action": "RESPOND",
                    "content": content[:MAX_CONTENT_CHARS],
                    "receiver": None,
                },
                (0, 0),
                {**tool_meta, "summary_skipped": "token_budget"},
            )
        provider = model_registry.get(
            model=profile.runtime.model,
            temperature=profile.runtime.temperature,
            max_tokens=max_tokens,
        )
        response = await provider.complete(
            followup,
            max_tokens=max_tokens,
            temperature=profile.runtime.temperature,
        )
        content = response.content.strip()
        if not content:
            raise ModelError("工具结果总结为空", kind="empty_response")
        decision = {
            **decision,
            "action": "RESPOND",
            "content": content[:MAX_CONTENT_CHARS],
            "receiver": None,
        }
        return decision, (
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
        ), tool_meta

    async def run(self, resume: bool = False) -> DiscussionResult:
        history = await message_bus.history(self.conversation_id, limit=30)
        initial: DiscussionState = {
            "question": self.question,
            "messages": history,
            "actions": [],
            "turn": 0,
            "model_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "sent_count": 0,
            "spoken_counts": {},
            "finished_agents": [],
            "tool_call_counts": {},
            "consecutive_waits": 0,
            "active_agent": "",
            "stop_reason": "",
            "started_at": time.monotonic(),
        }
        graph = self.build_graph()
        config = {
            "recursion_limit": 60,
            "configurable": {"thread_id": f"task:{self.task_id}"},
        }
        if resume and memory_runtime.checkpointer is not None:
            snapshot = await graph.aget_state(config)
            initial = None if snapshot.values else initial
        final = await graph.ainvoke(initial, config)
        return DiscussionResult(
            turns=final.get("turn", 0),
            sent_messages=final.get("sent_count", 0),
            model_calls=final.get("model_calls", 0),
            prompt_tokens=final.get("prompt_tokens", 0),
            completion_tokens=final.get("completion_tokens", 0),
            stop_reason=final.get("stop_reason") or "finish",
            actions=final.get("actions") or [],
        )
