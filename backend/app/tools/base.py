from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass(slots=True)
class ToolResult:
    ok: bool
    result: Any = None
    error: str | None = None
    duration_ms: int = 0
    truncated: bool = False
    error_type: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "result": self.result,
            "error": self.error,
            "error_type": self.error_type,
            "duration_ms": self.duration_ms,
            "truncated": self.truncated,
        }


@dataclass(slots=True)
class ToolContext:
    agent_id: str
    task_id: str
    conversation_id: str
    call_counts: dict[str, int] = field(default_factory=dict)
    max_calls: dict[str, int] = field(default_factory=dict)

    def can_call(self, tool_name: str) -> tuple[bool, str | None]:
        limit = self.max_calls.get(tool_name)
        if limit is None:
            return False, f"Agent 未被授权使用工具 {tool_name}"
        used = self.call_counts.get(tool_name, 0)
        if used >= limit:
            return False, f"工具 {tool_name} 本任务调用次数已达上限（{limit} 次）"
        return True, None

    def record(self, tool_name: str) -> None:
        self.call_counts[tool_name] = self.call_counts.get(tool_name, 0) + 1


ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    timeout_seconds: float = 10.0
    risk_level: str = "low"
    requires_isolation: bool = False
    category: str = "general"
    error_policy: str = "失败时把真实错误返回模型，由模型决定重试或改用其他方案"

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "timeout_seconds": self.timeout_seconds,
            "risk_level": self.risk_level,
            "requires_isolation": self.requires_isolation,
            "error_policy": self.error_policy,
            "parameters": self.parameters,
        }

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
