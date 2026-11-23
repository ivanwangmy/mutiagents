from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import registry
from app.db.session import SessionLocal, get_session
from app.events import TERMINAL_EVENT_TYPES, TERMINAL_TASK_STATUSES, event_broker
from app.memory.experience import experience_manager
from app.models import Conversation, Message, TaskEvent, TaskExecution, UserFeedback
from app.schemas.conversation import (
    ConversationCreate,
    ConversationSummary,
    ConversationUpdate,
    MessageOut,
    SendMessageRequest,
    SendMessageResponse,
)
from app.services import conversation_service, task_service

router = APIRouter(prefix="/conversations", tags=["conversations"])

# 仅内部审计使用、不向前端推送的事件类型（可能含内部决策原因，避免暴露思维链）
HIDDEN_EVENT_TYPES = frozenset({"agent.decision", "message.published", "task.finished"})


class FeedbackCreate(BaseModel):
    message_id: str | None = None
    agent_id: str | None = None
    rating: int = Field(ge=-1, le=1)
    comment: str = Field(default="", max_length=800)


async def _summary(session: AsyncSession, conversation: Conversation) -> ConversationSummary:
    last = await session.execute(
        select(Message.content)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    preview = last.scalar_one_or_none()
    return ConversationSummary(
        id=conversation.id,
        title=conversation.title,
        selected_agent_ids=conversation.selected_agent_ids,
        status=conversation.status,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message=(preview[:80] if preview else None),
    )


def _task_event_sse(row: TaskEvent) -> str:
    data = {
        "event_id": row.id,
        "event_type": row.event_type,
        "conversation_id": row.conversation_id,
        "task_id": row.task_id,
        "agent_id": row.agent_id,
        "timestamp": row.created_at.isoformat(),
        "payload": row.payload or {},
    }
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {row.id}\nevent: {row.event_type}\ndata: {body}\n\n"


@router.post("", response_model=ConversationSummary, status_code=201)
async def create_conversation(
    payload: ConversationCreate, session: AsyncSession = Depends(get_session)
) -> ConversationSummary:
    try:
        conversation = await conversation_service.create_conversation(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await event_broker.emit(
        "conversation_started",
        conversation_id=conversation.id,
        payload={
            "title": conversation.title,
            "selected_agent_ids": conversation.selected_agent_ids,
        },
    )
    return await _summary(session, conversation)


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(session: AsyncSession = Depends(get_session)) -> list[ConversationSummary]:
    conversations = await conversation_service.list_conversations(session)
    return [await _summary(session, c) for c in conversations]


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    conversation = await conversation_service.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    messages = await conversation_service.list_messages(session, conversation_id)
    active = await session.execute(
        select(TaskExecution.id)
        .where(
            TaskExecution.conversation_id == conversation_id,
            TaskExecution.status.in_(("pending", "running")),
        )
        .order_by(TaskExecution.started_at.desc())
        .limit(1)
    )
    return {
        "conversation": (await _summary(session, conversation)).model_dump(mode="json"),
        "messages": [
            conversation_service.to_message_out(message).model_dump(mode="json")
            for message in messages
        ],
        "active_task_id": active.scalar_one_or_none(),
        "agents": [
            {
                "id": agent_id,
                "name": registry.get(agent_id).name,
                "role_label": registry.get(agent_id).role_label,
                "avatar": registry.get(agent_id).avatar,
                "theme_color": registry.get(agent_id).theme_color,
            }
            for agent_id in conversation.selected_agent_ids
        ],
    }


@router.get("/{conversation_id}/events")
async def conversation_events(
    conversation_id: str,
    request: Request,
    task_id: str | None = None,
    last_event_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """SSE 实时事件流。

    - 先补拉 `id > Last-Event-ID` 的历史事件，再推送实时事件；
    - 支持 `Last-Event-ID` 请求头（EventSource 自动重连）或 `last_event_id` 查询参数；
    - 指定 `task_id` 时只推送该任务的事件，并在 task_completed/task_failed/task_stopped 后关闭；
    - 每 15 秒发送一次注释心跳，用于探测断线。
    """
    conversation = await conversation_service.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")

    if task_id is not None:
        task = await session.get(TaskExecution, task_id)
        if task is None or task.conversation_id != conversation_id:
            raise HTTPException(status_code=404, detail="任务不存在")

    after = max(last_event_id or 0, 0)
    header_value = request.headers.get("last-event-id")
    if header_value and header_value.strip().isdigit():
        after = max(after, int(header_value.strip()))

    async def generator():
        last = after
        async with event_broker.subscribe(conversation_id) as queue:
            async with SessionLocal() as db:
                stmt = select(TaskEvent).where(
                    TaskEvent.conversation_id == conversation_id,
                    TaskEvent.id > last,
                )
                if task_id is not None:
                    stmt = stmt.where(TaskEvent.task_id == task_id)
                rows = list(
                    (
                        await db.execute(
                            stmt.order_by(TaskEvent.id.asc()).limit(1000)
                        )
                    )
                    .scalars()
                    .all()
                )
                terminal = False
                if task_id is not None:
                    task_row = await db.get(TaskExecution, task_id)
                    terminal = bool(
                        task_row and task_row.status in TERMINAL_TASK_STATUSES
                    )

            for row in rows:
                last = row.id
                if row.event_type in HIDDEN_EVENT_TYPES:
                    continue
                yield _task_event_sse(row)
                if row.event_type in TERMINAL_EVENT_TYPES:
                    terminal = True
            if terminal and (task_id is not None or rows):
                return

            while True:
                try:
                    record = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": keep-alive\n\n"
                    continue
                if task_id is not None and record.task_id != task_id:
                    continue
                if record.event_id <= last:
                    continue
                last = record.event_id
                if record.event_type in HIDDEN_EVENT_TYPES:
                    continue
                yield record.to_sse()
                if record.event_type in TERMINAL_EVENT_TYPES:
                    return

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    session: AsyncSession = Depends(get_session),
) -> ConversationSummary:
    try:
        conversation = await conversation_service.update_conversation(
            session, conversation_id, payload
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return await _summary(session, conversation)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    deleted = await conversation_service.delete_conversation(session, conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="对话不存在")


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: str, session: AsyncSession = Depends(get_session)
) -> list[MessageOut]:
    conversation = await conversation_service.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    messages = await conversation_service.list_messages(session, conversation_id)
    return [conversation_service.to_message_out(message) for message in messages]


@router.post("/{conversation_id}/messages", response_model=SendMessageResponse, status_code=202)
async def send_message(
    conversation_id: str,
    payload: SendMessageRequest,
    session: AsyncSession = Depends(get_session),
) -> SendMessageResponse:
    conversation = await conversation_service.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    try:
        task, user_message = await task_service.create_task_and_message(
            conversation, payload.content.strip()
        )
    except (ValueError, task_service.TaskConflictError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    task_service.start_task(task.id)
    return SendMessageResponse(
        task_id=task.id,
        user_message=conversation_service.to_message_out(user_message),
        status=task.status,
    )


@router.post("/{conversation_id}/feedback", status_code=201)
async def submit_feedback(
    conversation_id: str,
    payload: FeedbackCreate,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """用户明确反馈：写入 UserFeedback 并立即走经验候选提取与验证。"""
    conversation = await conversation_service.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")

    agent_id = payload.agent_id
    if payload.message_id:
        message = await session.get(Message, payload.message_id)
        if message is None or message.conversation_id != conversation_id:
            raise HTTPException(status_code=404, detail="消息不存在")
        agent_id = agent_id or message.sender_agent_id
    if agent_id is None:
        raise HTTPException(status_code=400, detail="反馈必须关联到一个 Agent")
    if agent_id not in conversation.selected_agent_ids:
        raise HTTPException(status_code=400, detail="该 Agent 不在当前对话参与者中")

    feedback = UserFeedback(
        conversation_id=conversation_id,
        message_id=payload.message_id,
        agent_id=agent_id,
        rating=payload.rating,
        comment=payload.comment.strip(),
    )
    session.add(feedback)
    await session.commit()
    await session.refresh(feedback)

    experience = await experience_manager.create_from_feedback(feedback)
    return {
        "id": feedback.id,
        "conversation_id": feedback.conversation_id,
        "message_id": feedback.message_id,
        "agent_id": feedback.agent_id,
        "rating": feedback.rating,
        "comment": feedback.comment,
        "created_at": feedback.created_at.isoformat(),
        "experience": experience,
    }


@router.post("/{conversation_id}/messages/stream")
async def send_message_stream(
    conversation_id: str,
    payload: SendMessageRequest,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    conversation = await conversation_service.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    if len(registry.validate_participants(conversation.selected_agent_ids)) != 1:
        raise HTTPException(status_code=400, detail="当前阶段仅支持单 Agent 流式对话")
    return StreamingResponse(
        task_service.stream_single_agent(conversation, payload.content.strip()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
