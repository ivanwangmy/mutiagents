from __future__ import annotations

from pydantic import BaseModel


class SkillInfo(BaseModel):
    name: str
    id: str = ""
    version: str = "1.0.0"
    category: str = "method"
    description: str
    execution_logic: str
    when_to_use: str = ""
    trigger_conditions: list[str] = []
    required_inputs: list[str] = []
    limitations: list[str] = []


class RuntimeInfo(BaseModel):
    model: str
    temperature: float
    max_output_tokens: int
    max_context_tokens: int


class AgentSummary(BaseModel):
    id: str
    name: str
    role: str
    role_label: str
    avatar: str
    theme_color: str
    short_description: str
    introduction: str
    personality_tags: list[str]
    skills: list[SkillInfo]
    runtime: RuntimeInfo
    tool_permissions: list[str]
