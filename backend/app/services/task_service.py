from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from sqlalchemy import select

from app.agents.discussion import DiscussionRunner
from app.agents.executor import AgentExecutor
from app.agents.registry import registry
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.events import event_broker
from app.memory.experience import experience_manager
from app.memory.manager import memory_manager
from app.model.base import ModelError
from app.models import Conversation, Message, TaskExecution
from app.services import conversation_service
from app.utils.tokens import estimate_tokens

logger = get_logger(__name__)
executor = AgentExecutor()

_running: dict[str, asyncio.Task] = {}


class TaskConflictError(RuntimeError):
    pass


async def create_task_and_message(
    conversation: Conversation, content: str
) -> tuple[TaskExecution, Message]:
    """创建用户消息与任务记录，支持 1–3 个 Agent 参与者。"""
    agent_ids = registry.validate_participants(conversation.selected_agent_ids)
    if not 1 <= len(agent_ids) <= 3:
        raise TaskConflictError("参与者数量必须在 1 到 3 之间")

    async with SessionLocal() as session:
        user_message = Message(
            conversation_id=conversation.id,
            sender_type="user",
            sender_agent_id=None,
            message_type="question",
            content=content,
        )
        session.add(user_message)
        await session.flush()

        task = TaskExecution(
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            participating_agent_ids=agent_ids,
            status="pending",
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        await session.refresh(user_message)
        return task, user_message


def start_task(task_id: str, resume: bool = False) -> None:
    if task_id in _running:
        return
    task = asyncio.create_task(run_task(task_id, resume=resume))
    _running[task_id] = task
    task.add_done_callback(lambda _t: _running.pop(task_id, None))


async def resume_task(task_id: str) -> bool:
    """从 Checkpointer 断点恢复被停止/失败的任务。"""
    async with SessionLocal() as session:
        task = await session.get(TaskExecution, task_id)
        if task is None or task.status not in {"stopped", "failed"}:
            return False
        task.status = "pending"
        task.error = None
        task.finished_at = None
        await session.commit()
    start_task(task_id, resume=True)
    return True


async def stop_task(task_id: str) -> bool:
    task = _running.get(task_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


async def _load_task(session, task_id: str) -> TaskExecution | None:
    return await session.get(TaskExecution, task_id)


async def run_task(task_id: str, resume: bool = False) -> None:
    multi: tuple[str, list[str], str, bool] | None = None
    async with SessionLocal() as session:
        task = await _load_task(session, task_id)
        if task is None:
            return
        conversation = await session.get(Conversation, task.conversation_id)
        if conversation is None:
            task.status = "failed"
            task.error = "对话不存在"
            task.finished_at = datetime.now(timezone.utc)
            await session.commit()
            return

        task.status = "running"
        await session.commit()

        participants = list(task.participating_agent_ids)
        await event_broker.emit(
            "task_started",
            conversation_id=task.conversation_id,
            task_id=task.id,
            payload={
                "participants": participants,
                "mode": "multi" if len(participants) > 1 else "single",
                "resumed": resume,
            },
        )
        result = await session.execute(
            select(Message)
            .where(Message.conversation_id == task.conversation_id)
            .order_by(Message.created_at.asc())
        )
        messages = list(result.scalars().all())
        user_message = next((m for m in messages if m.id == task.user_message_id), None)
        question = user_message.content if user_message else ""

        if len(participants) > 1:
            multi = (task.conversation_id, participants, question, resume)
        else:
            agent_id = participants[0]
            profile = registry.get(agent_id)
            history = [m for m in messages if m.id != task.user_message_id]

            await event_broker.emit(
                "agent_started",
                conversation_id=task.conversation_id,
                task_id=task.id,
                agent_id=agent_id,
                payload={
                    "name": profile.name,
                    "role_label": profile.role_label,
                    "avatar": profile.avatar,
                    "theme_color": profile.theme_color,
                },
            )
            await event_broker.emit(
                "agent_status_changed",
                conversation_id=task.conversation_id,
                task_id=task.id,
                agent_id=agent_id,
                payload={"status": "thinking", "detail": "正在思考"},
            )

            try:
                response, _, meta = await executor.run(
                    profile,
                    question,
                    history,
                    task_id=task.id,
                    conversation_id=task.conversation_id,
                    resume=resume,
                )
                assistant_message = Message(
                    conversation_id=task.conversation_id,
                    task_id=task.id,
                    sender_type="agent",
                    sender_agent_id=profile.id,
                    message_type="response",
                    content=response.content,
                    meta={
                        "model": response.model,
                        "usage": {
                            "prompt_tokens": response.usage.prompt_tokens,
                            "completion_tokens": response.usage.completion_tokens,
                        },
                        "finish_reason": response.finish_reason,
                        "tool_rounds": meta["tool_rounds"],
                        "tool_calls": meta["tool_log"],
                        "memory_keys": meta.get("memory_keys") or [],
                        "experience_ids": meta.get("experience_ids") or [],
                    },
                )
                session.add(assistant_message)
                task.status = "completed"
                task.stop_reason = "finish"
                task.turn_count = 1
                task.message_count = 1
                task.model_calls += meta["model_calls"]
                task.prompt_tokens += response.usage.prompt_tokens
                task.completion_tokens += response.usage.completion_tokens
                task.finished_at = datetime.now(timezone.utc)
                await session.commit()
                await event_broker.emit(
                    "agent_status_changed",
                    conversation_id=task.conversation_id,
                    task_id=task.id,
                    agent_id=agent_id,
                    payload={"status": "speaking", "detail": "正在发言"},
                )
                await event_broker.emit(
                    "agent_message",
                    conversation_id=task.conversation_id,
                    task_id=task.id,
                    agent_id=agent_id,
                    payload={
                        "message": conversation_service.to_message_out(
                            assistant_message
                        ).model_dump(mode="json")
                    },
                )
                await event_broker.emit(
                    "agent_completed",
                    conversation_id=task.conversation_id,
                    task_id=task.id,
                    agent_id=agent_id,
                    payload={"status": "completed", "message_id": assistant_message.id},
                )
                await event_broker.emit(
                    "task_completed",
                    conversation_id=task.conversation_id,
                    task_id=task.id,
                    payload={
                        "stop_reason": "finish",
                        "turns": 1,
                        "messages": 1,
                        "model_calls": meta["model_calls"],
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "participants": [agent_id],
                    },
                )
                logger.info(
                    "任务完成：task=%s agent=%s model_calls=%s tool_rounds=%s tokens=%s+%s",
                    task.id,
                    agent_id,
                    meta["model_calls"],
                    meta["tool_rounds"],
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                )
                _schedule_post_task_analysis(
                    task.id, task.conversation_id, [agent_id], question
                )
            except asyncio.CancelledError:
                task.status = "stopped"
                task.stop_reason = "stopped"
                task.finished_at = datetime.now(timezone.utc)
                await session.commit()
                await event_broker.emit(
                    "agent_status_changed",
                    conversation_id=task.conversation_id,
                    task_id=task.id,
                    agent_id=agent_id,
                    payload={"status": "stopped", "detail": "已停止"},
                )
                await event_broker.emit(
                    "task_stopped",
                    conversation_id=task.conversation_id,
                    task_id=task.id,
                    agent_id=agent_id,
                    payload={"stop_reason": "stopped"},
                )
                raise
            except ModelError as exc:
                task.status = "failed"
                task.stop_reason = exc.kind
                task.error = str(exc)
                task.finished_at = datetime.now(timezone.utc)
                await session.commit()
                await event_broker.emit(
                    "agent_status_changed",
                    conversation_id=task.conversation_id,
                    task_id=task.id,
                    agent_id=agent_id,
                    payload={"status": "failed", "detail": str(exc)},
                )
                await event_broker.emit(
                    "task_failed",
                    conversation_id=task.conversation_id,
                    task_id=task.id,
                    agent_id=agent_id,
                    payload={"stop_reason": exc.kind, "error": str(exc)},
                )
                logger.warning("任务失败：task=%s error=%s", task.id, exc)
            except Exception as exc:  # noqa: BLE001
                task.status = "failed"
                task.stop_reason = "error"
                task.error = f"{type(exc).__name__}: {exc}"
                task.finished_at = datetime.now(timezone.utc)
                await session.commit()
                await event_broker.emit(
                    "agent_status_changed",
                    conversation_id=task.conversation_id,
                    task_id=task.id,
                    agent_id=agent_id,
                    payload={"status": "failed", "detail": f"{type(exc).__name__}: {exc}"},
                )
                await event_broker.emit(
                    "task_failed",
                    conversation_id=task.conversation_id,
                    task_id=task.id,
                    agent_id=agent_id,
                    payload={
                        "stop_reason": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                logger.exception("任务异常：task=%s", task.id)

    if multi is not None:
        conversation_id, participants, question, resume = multi
        await _run_multi_task(
            task_id, conversation_id, participants, question, resume=resume
        )


async def _run_multi_task(
    task_id: str,
    conversation_id: str,
    participants: list[str],
    question: str,
    *,
    resume: bool = False,
) -> None:
    """多 Agent 讨论：真实 Message Bus + LangGraph 动态调度。"""
    try:
        result = await asyncio.wait_for(
            DiscussionRunner(
                conversation_id=conversation_id,
                task_id=task_id,
                question=question,
                participants=participants,
            ).run(resume=resume),
            timeout=settings.task_max_seconds + 20,
        )
        async with SessionLocal() as session:
            task = await session.get(TaskExecution, task_id)
            if task is None:
                return
            task.status = "completed"
            task.stop_reason = result.stop_reason
            task.turn_count = result.turns
            task.message_count = result.sent_messages
            task.model_calls = result.model_calls
            task.prompt_tokens = result.prompt_tokens
            task.completion_tokens = result.completion_tokens
            task.finished_at = datetime.now(timezone.utc)
            await session.commit()
        for agent_id in participants:
            await event_broker.emit(
                "agent_status_changed",
                conversation_id=conversation_id,
                task_id=task_id,
                agent_id=agent_id,
                payload={"status": "completed", "detail": "已结束本轮"},
            )
            await event_broker.emit(
                "agent_completed",
                conversation_id=conversation_id,
                task_id=task_id,
                agent_id=agent_id,
                payload={"status": "completed"},
            )
        await event_broker.emit(
            "task_completed",
            conversation_id=conversation_id,
            task_id=task_id,
            payload={
                "stop_reason": result.stop_reason,
                "turns": result.turns,
                "messages": result.sent_messages,
                "model_calls": result.model_calls,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "participants": participants,
            },
        )
        logger.info(
            "多 Agent 任务完成：task=%s agents=%s turns=%s messages=%s calls=%s tokens=%s+%s stop=%s",
            task_id,
            participants,
            result.turns,
            result.sent_messages,
            result.model_calls,
            result.prompt_tokens,
            result.completion_tokens,
            result.stop_reason,
        )
        _schedule_post_task_analysis(task_id, conversation_id, participants, question)
    except asyncio.CancelledError:
        await _mark_task(task_id, "stopped", "stopped")
        raise
    except ModelError as exc:
        await _mark_task(task_id, "failed", exc.kind, str(exc))
    except TimeoutError:
        await _mark_task(task_id, "failed", "timeout", "多 Agent 讨论超时")
    except Exception as exc:  # noqa: BLE001
        logger.exception("多 Agent 任务异常：task=%s", task_id)
        await _mark_task(task_id, "failed", "error", f"{type(exc).__name__}: {exc}")


def _schedule_post_task_analysis(
    task_id: str, conversation_id: str, participants: list[str], question: str
) -> None:
    """后台提取长期记忆与候选经验，不阻塞任务完成，也不计入任务 Token 预算。"""

    async def _analyze() -> None:
        try:
            await memory_manager.extract_after_task(
                task_id=task_id,
                conversation_id=conversation_id,
                participants=participants,
                question=question,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("长期记忆提取失败：task=%s error=%s", task_id, exc)
        try:
            await experience_manager.extract_after_task(
                task_id=task_id,
                conversation_id=conversation_id,
                participants=participants,
                question=question,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("经验提取失败：task=%s error=%s", task_id, exc)

    asyncio.create_task(_analyze())


async def _mark_task(
    task_id: str, status: str, stop_reason: str, error: str | None = None
) -> None:
    async with SessionLocal() as session:
        task = await session.get(TaskExecution, task_id)
        if task is None:
            return
        task.status = status
        task.stop_reason = stop_reason
        task.error = error
        task.finished_at = datetime.now(timezone.utc)
        conversation_id = task.conversation_id
        participants = list(task.participating_agent_ids)
        await session.commit()
    detail = error or ("已停止" if status == "stopped" else "任务失败")
    for agent_id in participants:
        await event_broker.emit(
            "agent_status_changed",
            conversation_id=conversation_id,
            task_id=task_id,
            agent_id=agent_id,
            payload={"status": status, "detail": detail},
        )
    await event_broker.emit(
        "task_stopped" if status == "stopped" else "task_failed",
        conversation_id=conversation_id,
        task_id=task_id,
        payload={"stop_reason": stop_reason, "error": error},
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_single_agent(conversation: Conversation, content: str) -> AsyncIterator[str]:
    """单 Agent 流式回答（SSE）。每 token 来自真实模型流。"""
    task, user_message = await create_task_and_message(conversation, content)
    agent_id = task.participating_agent_ids[0]
    profile = registry.get(agent_id)

    yield _sse(
        "meta",
        {
            "task_id": task.id,
            "conversation_id": conversation.id,
            "agent_id": agent_id,
            "user_message_id": user_message.id,
            "tokens_budget": settings.task_token_budget,
        },
    )

    async with SessionLocal() as session:
        task_row = await session.get(TaskExecution, task.id)
        if task_row is not None:
            task_row.status = "running"
            await session.commit()
        result = await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.asc())
        )
        history = [m for m in result.scalars().all() if m.id != user_message.id]

    await event_broker.emit(
        "agent_started",
        conversation_id=conversation.id,
        task_id=task.id,
        agent_id=agent_id,
        payload={"mode": "single", "question": content[:200]},
    )

    buffer: list[str] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    meta: dict = {}
    error: str | None = None
    try:
        async for chunk in executor.stream(
            profile,
            content,
            history,
            task_id=task.id,
            conversation_id=conversation.id,
        ):
            if chunk.type == "text":
                buffer.append(chunk.text)
                yield _sse("token", {"text": chunk.text, "agent_id": agent_id})
            elif chunk.type == "done":
                if chunk.usage:
                    usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                    }
                meta = chunk.meta or {}
            elif chunk.type == "error":
                error = chunk.error or "模型流式调用失败"
        answer = "".join(buffer).strip()
        if error is None and not answer:
            error = "模型返回空内容"
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    async with SessionLocal() as session:
        task_row = await session.get(TaskExecution, task.id)
        if task_row is None:
            yield _sse("error", {"message": "任务不存在"})
            return
        if error:
            task_row.status = "failed"
            task_row.error = error
            task_row.stop_reason = "error"
            task_row.finished_at = datetime.now(timezone.utc)
            await session.commit()
            await event_broker.emit(
                "agent_failed",
                conversation_id=conversation.id,
                task_id=task.id,
                agent_id=agent_id,
                payload={"error": error},
            )
            yield _sse("error", {"message": error, "task_id": task.id})
            return

        message = Message(
            conversation_id=conversation.id,
            task_id=task.id,
            sender_type="agent",
            sender_agent_id=agent_id,
            message_type="response",
            content=answer,
            meta={
                "model": profile.runtime.model,
                "usage": usage,
                "streamed": True,
                "tool_calls": meta.get("tool_log") or [],
                "tool_rounds": meta.get("tool_rounds", 0),
            },
        )
        session.add(message)
        task_row.status = "completed"
        task_row.stop_reason = "finish"
        task_row.turn_count = 1
        task_row.message_count = 1
        task_row.model_calls += int(meta.get("model_calls", 1) or 1)
        task_row.prompt_tokens += usage["prompt_tokens"]
        task_row.completion_tokens += usage["completion_tokens"]
        task_row.finished_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(message)

        await event_broker.emit(
            "agent_completed",
            conversation_id=conversation.id,
            task_id=task.id,
            agent_id=agent_id,
            payload={
                "message_id": message.id,
                "tool_calls": len(meta.get("tool_log") or []),
                "tool_rounds": meta.get("tool_rounds", 0),
            },
        )

        yield _sse(
            "done",
            {
                "task_id": task.id,
                "message_id": message.id,
                "agent_id": agent_id,
                "content": answer,
                "usage": usage,
                "model_calls": meta.get("model_calls", 1),
                "tool_rounds": meta.get("tool_rounds", 0),
                "tool_calls": meta.get("tool_log") or [],
                "estimated_prompt_tokens": estimate_tokens(content),
            },
        )
