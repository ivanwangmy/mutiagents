from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.events import event_broker
from app.models import Message

logger = get_logger(__name__)

MESSAGE_TYPES = {
    "message",
    "question",
    "response",
    "challenge",
    "request_help",
    "handoff",
    "conclusion",
}


@dataclass(slots=True)
class BusMessage:
    message_id: str
    conversation_id: str
    task_id: str | None
    sender_agent_id: str | None
    receiver_agent_id: str | None
    message_type: str
    content: str
    reply_to_message_id: str | None
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.message_id,
            "conversation_id": self.conversation_id,
            "task_id": self.task_id,
            "sender_type": "agent" if self.sender_agent_id else "user",
            "sender_agent_id": self.sender_agent_id,
            "receiver_agent_id": self.receiver_agent_id,
            "message_type": self.message_type,
            "content": self.content,
            "reply_to_message_id": self.reply_to_message_id,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    def to_chat_dict(self) -> dict[str, Any]:
        """前端 MessageOut 结构（含 created_at 字段）。"""
        return {
            "id": self.message_id,
            "conversation_id": self.conversation_id,
            "task_id": self.task_id,
            "sender_type": "agent" if self.sender_agent_id else "user",
            "sender_agent_id": self.sender_agent_id,
            "receiver_agent_id": self.receiver_agent_id,
            "message_type": self.message_type,
            "content": self.content,
            "reply_to_message_id": self.reply_to_message_id,
            "created_at": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


class MessageBus:
    """落库的真实消息总线，同时写入 TaskEvent，供后续 SSE 推送使用。"""

    async def publish(
        self,
        *,
        conversation_id: str,
        task_id: str | None,
        sender_agent_id: str | None,
        receiver_agent_id: str | None = None,
        message_type: str = "message",
        content: str,
        reply_to_message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> BusMessage:
        if message_type not in MESSAGE_TYPES:
            raise ValueError(f"不支持的消息类型：{message_type}")
        async with SessionLocal() as session:
            message = Message(
                conversation_id=conversation_id,
                task_id=task_id,
                sender_type="agent" if sender_agent_id else "user",
                sender_agent_id=sender_agent_id,
                receiver_agent_id=receiver_agent_id,
                message_type=message_type,
                content=content,
                reply_to_message_id=reply_to_message_id,
                meta=metadata or {},
            )
            session.add(message)
            await session.flush()
            await session.commit()
            await session.refresh(message)
            bus_message = BusMessage(
                message_id=message.id,
                conversation_id=message.conversation_id,
                task_id=message.task_id,
                sender_agent_id=message.sender_agent_id,
                receiver_agent_id=message.receiver_agent_id,
                message_type=message.message_type,
                content=message.content,
                reply_to_message_id=message.reply_to_message_id,
                timestamp=message.created_at,
                metadata=message.meta or {},
            )
            logger.info(
                "消息总线投递：task=%s from=%s to=%s type=%s",
                task_id,
                sender_agent_id,
                receiver_agent_id,
                message_type,
            )
        await event_broker.emit(
            "agent_message",
            conversation_id=conversation_id,
            task_id=task_id,
            agent_id=sender_agent_id,
            payload={"message": bus_message.to_chat_dict()},
        )
        return bus_message

    async def history(self, conversation_id: str, limit: int = 30) -> list[dict[str, Any]]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(limit)
            )
            rows = list(reversed(result.scalars().all()))
            return [
                {
                    "id": row.id,
                    "sender_type": row.sender_type,
                    "sender_agent_id": row.sender_agent_id,
                    "receiver_agent_id": row.receiver_agent_id,
                    "message_type": row.message_type,
                    "content": row.content,
                    "reply_to_message_id": row.reply_to_message_id,
                    "timestamp": row.created_at.isoformat(),
                    "metadata": row.meta or {},
                }
                for row in rows
            ]


message_bus = MessageBus()
