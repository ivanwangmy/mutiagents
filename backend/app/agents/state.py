from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """单个 Agent 回合的 LangGraph 状态（可序列化，供 Checkpointer 使用）。"""

    agent_id: str
    task_id: str
    conversation_id: str
    question: str
    chat_messages: list[dict[str, Any]]
    content: str
    finish_reason: str
    tool_calls: list[dict[str, Any]]
    tool_call_counts: dict[str, int]
    tool_rounds: int
    tool_log: list[dict[str, Any]]
    usage: dict[str, int]
    model: str
    iterations: int
    error: str
