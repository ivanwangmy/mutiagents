from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.agents.config import AgentProfile

Decision = Literal[
    "RESPOND",
    "ASK_USER",
    "MESSAGE_AGENT",
    "REQUEST_HELP",
    "CHALLENGE",
    "USE_TOOL",
    "WAIT",
    "FINISH",
]


@dataclass(slots=True)
class AgentExecutionContext:
    """一个 Agent 单次回合可访问的全部运行上下文（不包含其他 Agent 的私人记忆）。"""

    conversation_id: str
    task_id: str
    agent: AgentProfile
    user_question: str
    public_messages: list[dict[str, Any]] = field(default_factory=list)
    relevant_memories: list[str] = field(default_factory=list)
    experiences: list[str] = field(default_factory=list)
    available_tools: list[str] = field(default_factory=list)
    token_budget_left: int = 0
    model_calls_left: int = 0


@dataclass(slots=True)
class AgentTurnResult:
    agent_id: str
    decision: Decision
    message_type: str
    content: str
    receiver_agent_id: str | None = None
    reply_to_message_id: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model_usage: dict[str, int] = field(default_factory=dict)


class AgentRuntime(Protocol):
    """Agent 运行时接口：第 4 轮实现单 Agent，第 6 轮接入多 Agent 调度。"""

    async def run_turn(self, context: AgentExecutionContext) -> AgentTurnResult: ...
