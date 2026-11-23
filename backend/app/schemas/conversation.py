from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    selected_agent_ids: list[str] = Field(min_length=1, max_length=3)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    selected_agent_ids: list[str] | None = Field(default=None, min_length=1, max_length=3)


class ConversationSummary(BaseModel):
    id: str
    title: str
    selected_agent_ids: list[str]
    status: str
    created_at: datetime
    updated_at: datetime
    last_message: str | None = None


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    task_id: str | None
    sender_type: str
    sender_agent_id: str | None
    receiver_agent_id: str | None
    message_type: str
    content: str
    reply_to_message_id: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class SendMessageResponse(BaseModel):
    task_id: str
    user_message: MessageOut
    status: str


class TaskOut(BaseModel):
    id: str
    conversation_id: str
    status: str
    participating_agent_ids: list[str]
    turn_count: int
    message_count: int
    model_calls: int
    prompt_tokens: int
    completion_tokens: int
    stop_reason: str | None
    error: str | None
    assistant_message_id: str | None = None
    started_at: datetime
    finished_at: datetime | None


class UsageOut(BaseModel):
    task_id: str
    model_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    token_budget: int
    seconds_elapsed: float
