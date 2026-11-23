from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from jsonschema import SchemaError, ValidationError, validate

from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.events.broker import event_broker
from app.models import ToolCall
from app.tools.base import ToolContext, ToolDefinition, ToolResult

logger = get_logger(__name__)

MAX_RESULT_CHARS = 4000


def _json_safe(payload: Any) -> Any:
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


class ToolExecutor:
    """真实执行工具：权限 → 参数校验 → 超时执行 → 写入 ToolExecutionLog。"""

    async def execute(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        tool: ToolDefinition | None,
        context: ToolContext,
        task_id: str | None,
        conversation_id: str | None,
        call_id: str | None = None,
    ) -> ToolResult:
        started = time.perf_counter()
        call_id = call_id or f"{name}-{int(started * 1000)}"

        if tool is None:
            return await self._finish(
                name=name,
                arguments=arguments,
                context=context,
                task_id=task_id,
                conversation_id=conversation_id,
                result=ToolResult(
                    ok=False,
                    error=f"工具未注册或未授权给当前 Agent：{name}",
                    error_type="permission",
                ),
                started=started,
                call_id=call_id,
            )

        allowed, reason = context.can_call(name)
        if not allowed:
            return await self._finish(
                name=name,
                arguments=arguments,
                context=context,
                task_id=task_id,
                conversation_id=conversation_id,
                result=ToolResult(
                    ok=False, error=reason or "工具调用不被允许", error_type="limit"
                ),
                started=started,
                call_id=call_id,
            )

        try:
            validate(instance=arguments, schema=tool.parameters)
        except (ValidationError, SchemaError) as exc:
            message = getattr(exc, "message", str(exc))
            return await self._finish(
                name=name,
                arguments=arguments,
                context=context,
                task_id=task_id,
                conversation_id=conversation_id,
                result=ToolResult(
                    ok=False, error=f"参数校验失败：{message}", error_type="validation"
                ),
                started=started,
                call_id=call_id,
            )

        await self._emit(
            "tool_call_started",
            context=context,
            task_id=task_id,
            conversation_id=conversation_id,
            payload={
                "call_id": call_id,
                "tool": name,
                "category": tool.category,
                "arguments": _json_safe(arguments),
            },
        )

        try:
            value = await asyncio.wait_for(
                tool.handler(arguments), timeout=tool.timeout_seconds
            )
            result = ToolResult(ok=True, result=value)
            context.record(name)
        except TimeoutError:
            result = ToolResult(
                ok=False,
                error=f"工具执行超时（>{tool.timeout_seconds} 秒）",
                error_type="timeout",
            )
            context.record(name)
        except ValueError as exc:
            # 参数/契约错误属于可重试错误，不消耗调用配额
            logger.info("工具参数错误：%s error=%s", name, exc)
            result = ToolResult(
                ok=False, error=f"{type(exc).__name__}: {exc}", error_type="validation"
            )
        except Exception as exc:  # noqa: BLE001 - 工具失败必须回传模型
            logger.warning("工具执行失败：%s error=%s", name, exc)
            result = ToolResult(
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                error_type="execution",
            )
            context.record(name)

        return await self._finish(
            name=name,
            arguments=arguments,
            context=context,
            task_id=task_id,
            conversation_id=conversation_id,
            result=result,
            started=started,
            call_id=call_id,
        )

    async def _finish(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
        task_id: str | None,
        conversation_id: str | None,
        result: ToolResult,
        started: float,
        call_id: str,
    ) -> ToolResult:
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        payload = _json_safe(result.to_payload())
        if len(json.dumps(payload, ensure_ascii=False)) > MAX_RESULT_CHARS:
            payload["result"] = str(payload.get("result"))[: MAX_RESULT_CHARS // 2]
            payload["truncated"] = True
        try:
            async with SessionLocal() as session:
                session.add(
                    ToolCall(
                        task_id=task_id,
                        conversation_id=conversation_id,
                        agent_id=context.agent_id,
                        tool_name=name,
                        arguments=_json_safe(arguments),
                        result=payload,
                        status="success" if result.ok else "error",
                        error=result.error,
                        duration_ms=result.duration_ms,
                    )
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001 - 日志失败不影响工具结果
            logger.warning("工具执行日志写入失败：%s", exc)

        await self._emit(
            "tool_call_completed" if result.ok else "tool_call_failed",
            context=context,
            task_id=task_id,
            conversation_id=conversation_id,
            payload={
                "call_id": call_id,
                "tool": name,
                "status": "success" if result.ok else "error",
                "error_type": result.error_type,
                "error": result.error,
                "duration_ms": result.duration_ms,
                "result_preview": str(payload.get("result"))[:500],
            },
        )
        return result

    async def _emit(
        self,
        event_type: str,
        *,
        context: ToolContext,
        task_id: str | None,
        conversation_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        if not conversation_id:
            return
        try:
            await event_broker.emit(
                event_type,
                conversation_id=conversation_id,
                task_id=task_id,
                agent_id=context.agent_id,
                payload=payload,
            )
        except Exception as exc:  # noqa: BLE001 - 事件失败不影响工具执行
            logger.warning("工具事件写入失败：type=%s error=%s", event_type, exc)


tool_executor = ToolExecutor()
