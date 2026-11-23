from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import openai
from openai import AsyncOpenAI

from app.core.logging import get_logger
from app.model.base import (
    ModelConfig,
    ModelError,
    ModelResponse,
    ModelStreamChunk,
    ModelUsage,
    ToolCallRequest,
)

logger = get_logger(__name__)


class DeepSeekProvider:
    """DeepSeek OpenAI 兼容适配器。

    关键约束：
    - 密钥只来自后端配置；
    - 默认关闭 thinking，避免 reasoning tokens 挤占正文并抬高成本；
    - usage 全部回传，供任务预算统计。
    """

    name = "deepseek"

    def __init__(self, config: ModelConfig) -> None:
        if not config.api_key:
            raise ModelError("缺少 DeepSeek API Key", kind="config_error")
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            max_retries=1,
        )

    def _extra_body(self) -> dict[str, Any] | None:
        if self.config.thinking_enabled:
            return None
        return {"thinking": {"type": "disabled"}}

    def _payload(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
        tool_choice: str | None,
        response_format: dict[str, Any] | None,
        max_tokens: int | None,
        temperature: float | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": max_tokens or self.config.max_tokens,
            "temperature": self.config.temperature if temperature is None else temperature,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice
        if response_format:
            payload["response_format"] = response_format
        extra = self._extra_body()
        if extra:
            payload["extra_body"] = extra
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    @staticmethod
    def _usage(raw_usage: Any) -> ModelUsage:
        if raw_usage is None:
            return ModelUsage()
        details = getattr(raw_usage, "completion_tokens_details", None)
        reasoning = getattr(details, "reasoning_tokens", 0) or 0 if details else 0
        return ModelUsage(
            prompt_tokens=raw_usage.prompt_tokens or 0,
            completion_tokens=raw_usage.completion_tokens or 0,
            reasoning_tokens=reasoning,
        )

    def _wrap_error(self, exc: Exception) -> ModelError:
        if isinstance(exc, (openai.APITimeoutError, TimeoutError)):
            return ModelError(f"模型调用超时：{exc}", kind="timeout")
        if isinstance(exc, openai.AuthenticationError):
            return ModelError("模型鉴权失败，请检查 API Key", kind="auth_error")
        if isinstance(exc, openai.RateLimitError):
            return ModelError("模型限流，请稍后重试", kind="rate_limit")
        if isinstance(exc, openai.APIError):
            return ModelError(f"模型服务错误：{exc}", kind="api_error")
        return ModelError(f"模型调用失败：{type(exc).__name__}: {exc}", kind="unknown")

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ModelResponse:
        payload = self._payload(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
        )
        try:
            completion = await self.client.chat.completions.create(**payload)
        except Exception as exc:  # noqa: BLE001
            raise self._wrap_error(exc) from exc

        choice = completion.choices[0]
        message = choice.message
        tool_calls: list[ToolCallRequest] = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"__raw__": call.function.arguments}
            tool_calls.append(
                ToolCallRequest(id=call.id, name=call.function.name, arguments=arguments)
            )

        return ModelResponse(
            content=message.content or "",
            finish_reason=choice.finish_reason or "stop",
            tool_calls=tool_calls,
            usage=self._usage(completion.usage),
            model=completion.model,
            reasoning_content=getattr(message, "reasoning_content", "") or "",
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[ModelStreamChunk]:
        payload = self._payload(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            response_format=None,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        usage: ModelUsage | None = None
        finish_reason: str | None = None
        pending: dict[int, dict[str, str]] = {}
        try:
            stream = await self.client.chat.completions.create(**payload)
            async for chunk in stream:
                if chunk.usage:
                    usage = self._usage(chunk.usage)
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                delta = choice.delta
                if delta is None:
                    continue
                for call in delta.tool_calls or []:
                    index = call.index or 0
                    entry = pending.setdefault(
                        index, {"id": "", "name": "", "arguments": ""}
                    )
                    if call.id:
                        entry["id"] = call.id
                    if call.function is not None:
                        if call.function.name:
                            entry["name"] += call.function.name
                        if call.function.arguments:
                            entry["arguments"] += call.function.arguments
                if delta.content:
                    yield ModelStreamChunk(type="text", text=delta.content)

            tool_calls: list[ToolCallRequest] = []
            for index in sorted(pending):
                entry = pending[index]
                if not entry["name"]:
                    continue
                try:
                    arguments = json.loads(entry["arguments"] or "{}")
                except json.JSONDecodeError:
                    arguments = {"__raw__": entry["arguments"]}
                tool_calls.append(
                    ToolCallRequest(
                        id=entry["id"] or f"call_{index}",
                        name=entry["name"],
                        arguments=arguments,
                    )
                )
            if tool_calls:
                yield ModelStreamChunk(type="tool_calls", tool_calls=tool_calls)
            yield ModelStreamChunk(type="done", finish_reason=finish_reason, usage=usage)
        except Exception as exc:  # noqa: BLE001
            logger.warning("流式模型调用失败：%s", exc)
            yield ModelStreamChunk(type="error", error=self._wrap_error(exc).kind)
