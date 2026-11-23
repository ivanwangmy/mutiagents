from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Protocol


@dataclass(slots=True)
class ModelConfig:
    provider: str = "deepseek"
    model: str = "deepseek-flash"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    temperature: float = 0.5
    max_tokens: int = 800
    thinking_enabled: bool = False
    timeout_seconds: float = 60.0


@dataclass(slots=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ModelUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(slots=True)
class ModelResponse:
    content: str
    finish_reason: str
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    usage: ModelUsage = field(default_factory=ModelUsage)
    model: str = ""
    reasoning_content: str = ""


StreamEventType = Literal["text", "tool_calls", "done", "error"]


@dataclass(slots=True)
class ModelStreamChunk:
    type: StreamEventType
    text: str = ""
    finish_reason: str | None = None
    usage: ModelUsage | None = None
    error: str | None = None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


class ModelError(RuntimeError):
    def __init__(self, message: str, kind: str = "model_error") -> None:
        super().__init__(message)
        self.kind = kind


class ModelProvider(Protocol):
    name: str

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ModelResponse: ...

    def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[ModelStreamChunk]: ...
