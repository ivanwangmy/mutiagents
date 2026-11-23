from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import registry
from app.models import Conversation, ConversationParticipant, Message, TaskExecution
from app.schemas.conversation import ConversationCreate, ConversationUpdate, MessageOut


async def create_conversation(session: AsyncSession, payload: ConversationCreate) -> Conversation:
    agent_ids = registry.validate_participants(payload.selected_agent_ids)
    title = (payload.title or "新课堂").strip() or "新课堂"
    conversation = Conversation(title=title, selected_agent_ids=agent_ids)
    session.add(conversation)
    await session.flush()
    for agent_id in agent_ids:
        session.add(
            ConversationParticipant(conversation_id=conversation.id, agent_id=agent_id)
        )
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def update_conversation(
    session: AsyncSession, conversation_id: str, payload: ConversationUpdate
) -> Conversation | None:
    conversation = await get_conversation(session, conversation_id)
    if conversation is None:
        return None

    if payload.selected_agent_ids is not None:
        running = await session.execute(
            select(TaskExecution.id).where(
                TaskExecution.conversation_id == conversation_id,
                TaskExecution.status.in_(("pending", "running")),
            )
        )
        if running.first() is not None:
            raise ValueError("讨论进行中，暂不能调整参与者")
        agent_ids = registry.validate_participants(payload.selected_agent_ids)
        if len(agent_ids) > 3:
            raise ValueError("参与者数量最多为 3 个")
        if agent_ids != list(conversation.selected_agent_ids):
            await session.execute(
                delete(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == conversation_id
                )
            )
            for agent_id in agent_ids:
                session.add(
                    ConversationParticipant(conversation_id=conversation_id, agent_id=agent_id)
                )
            conversation.selected_agent_ids = agent_ids

    if payload.title is not None:
        title = payload.title.strip()
        if title:
            conversation.title = title

    await session.commit()
    await session.refresh(conversation)
    return conversation


async def list_conversations(session: AsyncSession, limit: int = 50) -> list[Conversation]:
    result = await session.execute(
        select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_conversation(session: AsyncSession, conversation_id: str) -> Conversation | None:
    return await session.get(Conversation, conversation_id)


async def delete_conversation(session: AsyncSession, conversation_id: str) -> bool:
    conversation = await get_conversation(session, conversation_id)
    if conversation is None:
        return False
    await session.execute(delete(Message).where(Message.conversation_id == conversation_id))
    await session.delete(conversation)
    await session.commit()
    return True


async def add_message(
    session: AsyncSession,
    *,
    conversation_id: str,
    sender_type: str,
    content: str,
    task_id: str | None = None,
    sender_agent_id: str | None = None,
    receiver_agent_id: str | None = None,
    message_type: str = "message",
    reply_to_message_id: str | None = None,
    metadata: dict | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        task_id=task_id,
        sender_type=sender_type,
        sender_agent_id=sender_agent_id,
        receiver_agent_id=receiver_agent_id,
        message_type=message_type,
        content=content,
        reply_to_message_id=reply_to_message_id,
        meta=metadata or {},
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return message


async def list_messages(
    session: AsyncSession, conversation_id: str, limit: int = 200
) -> list[Message]:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


def to_message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        task_id=message.task_id,
        sender_type=message.sender_type,
        sender_agent_id=message.sender_agent_id,
        receiver_agent_id=message.receiver_agent_id,
        message_type=message.message_type,
        content=message.content,
        reply_to_message_id=message.reply_to_message_id,
        metadata=message.meta or {},
        created_at=message.created_at,
    )
