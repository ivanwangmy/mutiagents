from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.discussion import DiscussionRunner
from app.agents.graph import agent_graph_factory
from app.agents.registry import registry
from app.core.config import settings
from app.db.session import get_session
from app.memory.runtime import memory_runtime
from app.models import Message, TaskExecution, ToolCall
from app.schemas.conversation import TaskOut, UsageOut
from app.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def _task_out(session: AsyncSession, task: TaskExecution) -> TaskOut:
    result = await session.execute(
        select(Message.id)
        .where(Message.task_id == task.id, Message.sender_type == "agent")
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    return TaskOut(
        id=task.id,
        conversation_id=task.conversation_id,
        status=task.status,
        participating_agent_ids=task.participating_agent_ids,
        turn_count=task.turn_count,
        message_count=task.message_count,
        model_calls=task.model_calls,
        prompt_tokens=task.prompt_tokens,
        completion_tokens=task.completion_tokens,
        stop_reason=task.stop_reason,
        error=task.error,
        assistant_message_id=result.scalar_one_or_none(),
        started_at=task.started_at,
        finished_at=task.finished_at,
    )


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: str, session: AsyncSession = Depends(get_session)) -> TaskOut:
    task = await session.get(TaskExecution, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return await _task_out(session, task)


@router.post("/{task_id}/stop", response_model=TaskOut)
async def stop_task(task_id: str, session: AsyncSession = Depends(get_session)) -> TaskOut:
    task = await session.get(TaskExecution, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in {"pending", "running"}:
        return await _task_out(session, task)
    stopped = await task_service.stop_task(task_id)
    if not stopped:
        task.status = "stopped"
        task.stop_reason = "stopped"
        task.finished_at = datetime.now(timezone.utc)
        await session.commit()
    else:
        for _ in range(10):
            await asyncio.sleep(0.1)
            await session.refresh(task)
            if task.status not in {"pending", "running"}:
                break
    return await _task_out(session, task)


@router.post("/{task_id}/resume", response_model=TaskOut)
async def resume_task(task_id: str, session: AsyncSession = Depends(get_session)) -> TaskOut:
    task = await session.get(TaskExecution, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in {"stopped", "failed"}:
        raise HTTPException(status_code=400, detail="只有已停止或失败的任务可以恢复")
    if not await task_service.resume_task(task_id):
        raise HTTPException(status_code=400, detail="无法恢复该任务")
    for _ in range(10):
        await asyncio.sleep(0.1)
        await session.refresh(task)
        if task.status not in {"pending", "running"}:
            break
    return await _task_out(session, task)


@router.get("/{task_id}/checkpoint")
async def task_checkpoint(
    task_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    """读取该任务在 PostgreSQL Checkpointer 中的短期状态（不含模型密钥）。"""
    task = await session.get(TaskExecution, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if memory_runtime.checkpointer is None:
        return {"enabled": False, "task_id": task_id}

    if len(task.participating_agent_ids) > 1:
        runner = DiscussionRunner(
            conversation_id=task.conversation_id,
            task_id=task.id,
            question="",
            participants=list(task.participating_agent_ids),
        )
        graph = runner.build_graph()
        thread_id = f"task:{task.id}"
    else:
        profile = registry.get(task.participating_agent_ids[0])
        graph = agent_graph_factory.create(profile)
        thread_id = f"task:{task.id}:{profile.id}"

    snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    values = snapshot.values or {}
    usage = values.get("usage") or {}
    messages = values.get("messages") or values.get("chat_messages") or []
    return {
        "enabled": True,
        "task_id": task_id,
        "thread_id": thread_id,
        "checkpoint_id": (snapshot.config or {}).get("configurable", {}).get("checkpoint_id"),
        "next": list(snapshot.next),
        "state_keys": sorted(values),
        "turn": values.get("turn"),
        "active_agent": values.get("active_agent"),
        "stop_reason": values.get("stop_reason"),
        "message_count": len(messages),
        "model_calls": values.get("model_calls", values.get("iterations")),
        "tokens": (values.get("prompt_tokens", 0) or 0)
        + (values.get("completion_tokens", 0) or 0)
        + (usage.get("prompt_tokens", 0) or 0)
        + (usage.get("completion_tokens", 0) or 0),
    }


@router.get("/{task_id}/usage", response_model=UsageOut)
async def task_usage(task_id: str, session: AsyncSession = Depends(get_session)) -> UsageOut:
    task = await session.get(TaskExecution, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    end = task.finished_at or datetime.now(timezone.utc)
    started = task.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return UsageOut(
        task_id=task.id,
        model_calls=task.model_calls,
        prompt_tokens=task.prompt_tokens,
        completion_tokens=task.completion_tokens,
        total_tokens=task.prompt_tokens + task.completion_tokens,
        token_budget=settings.task_token_budget,
        seconds_elapsed=round((end - started).total_seconds(), 2),
    )


@router.get("/{task_id}/tool-calls")
async def task_tool_calls(
    task_id: str, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    """真实工具执行日志（ToolExecutionLog）。"""
    task = await session.get(TaskExecution, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    result = await session.execute(
        select(ToolCall)
        .where(ToolCall.task_id == task_id)
        .order_by(ToolCall.created_at.asc())
    )
    return [
        {
            "id": call.id,
            "agent_id": call.agent_id,
            "tool_name": call.tool_name,
            "arguments": call.arguments,
            "result": call.result,
            "status": call.status,
            "error": call.error,
            "duration_ms": call.duration_ms,
            "created_at": call.created_at.isoformat(),
        }
        for call in result.scalars().all()
    ]
