from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    avatar_url: Mapped[str] = mapped_column(String(255), nullable=False)
    theme_color: Mapped[str] = mapped_column(String(16), nullable=False)
    short_description: Mapped[str] = mapped_column(String(255), nullable=False)
    introduction: Mapped[str] = mapped_column(Text, default="")
    personality_tags: Mapped[list[str]] = mapped_column(JSON, default=list)


class AgentConfigModel(Base, TimestampMixin):
    __tablename__ = "agent_configs"

    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    system_prompt_path: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.5)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=600)
    max_context_tokens: Mapped[int] = mapped_column(Integer, default=3000)
    memory_namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AgentSkill(Base, TimestampMixin):
    __tablename__ = "agent_skills"
    __table_args__ = (UniqueConstraint("agent_id", "skill_name", name="uq_agent_skill"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    skill_name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    execution_logic: Mapped[str] = mapped_column(String(255), default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AgentToolPermission(Base, TimestampMixin):
    __tablename__ = "agent_tool_permissions"
    __table_args__ = (UniqueConstraint("agent_id", "tool_name", name="uq_agent_tool"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    max_calls_per_task: Mapped[int] = mapped_column(Integer, default=3)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
