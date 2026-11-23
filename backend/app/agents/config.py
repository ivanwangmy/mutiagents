from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

AGENTS_DIR = Path(__file__).resolve().parent
PERSONA_DIR = AGENTS_DIR / "personas"
PROMPT_DIR = AGENTS_DIR / "prompts"

FIXED_AGENT_IDS = ("alex", "mia", "ethan")


class SkillSpec(BaseModel):
    """统一 Skill 规范。

    id/version/category/trigger_conditions/error_handling/limitations 允许在
    persona 中显式声明；未声明时由技能目录（app/skills/catalog.py）补齐，
    保证每个 Skill 在运行时都具备完整元数据。
    """

    name: str
    id: str = ""
    version: str = "1.0.0"
    category: str = "method"
    description: str
    applicable_agents: list[str] = Field(default_factory=list)
    execution_logic: str
    when_to_use: str = ""
    trigger_conditions: list[str] = Field(default_factory=list)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    execution_steps: list[str] = Field(default_factory=list)
    error_handling: str = ""
    limitations: list[str] = Field(default_factory=list)
    enabled: bool = True
    permission: str = "agent_self"
    examples: list[str] = Field(default_factory=list)

    @field_validator("execution_logic")
    @classmethod
    def _logic_must_reference_module(cls, value: str) -> str:
        if ":" not in value:
            raise ValueError("execution_logic 必须使用 module:function 格式")
        return value

    @model_validator(mode="after")
    def _fill_defaults(self) -> "SkillSpec":
        if not self.id:
            self.id = self.name
        if not self.trigger_conditions and self.when_to_use:
            self.trigger_conditions = [self.when_to_use]
        if not self.error_handling:
            self.error_handling = (
                "输入不满足 input_schema 时返回缺失字段与重试提示；"
                "执行异常由工具层以真实错误回传，不允许编造成功。"
            )
        return self

    @property
    def required_inputs(self) -> list[str]:
        return [str(item) for item in self.input_schema.get("required") or []]


class BehaviorSpec(BaseModel):
    """Agent 的行为策略；与人格文案分离，直接进入 System Prompt。"""

    decision_style: str = ""
    tool_policy: str = ""
    skill_policy: str = ""
    collaboration: str = ""
    uncertainty_policy: str = ""
    preferred_skills: list[str] = Field(default_factory=list)
    answer_checks: list[str] = Field(default_factory=list)


class ToolPermissionSpec(BaseModel):
    name: str
    max_calls_per_task: int = 3


class RuntimeSpec(BaseModel):
    model: str = "deepseek-flash"
    temperature: float = 0.5
    max_output_tokens: int = 600
    max_context_tokens: int = 3000


class PersonaSpec(BaseModel):
    id: str
    name: str
    role: Literal["teacher", "assistant", "student"]
    role_label: str
    avatar: str
    theme_color: str
    short_description: str
    introduction: str
    personality_tags: list[str]
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)
    behavior: BehaviorSpec = Field(default_factory=BehaviorSpec)
    skills: list[SkillSpec] = Field(default_factory=list)
    tool_permissions: list[ToolPermissionSpec] = Field(default_factory=list)

    @field_validator("avatar")
    @classmethod
    def _avatar_must_be_agent_asset(cls, value: str) -> str:
        if not value.startswith("/agents/") or not value.endswith(".png"):
            raise ValueError("头像必须使用 /agents/{id}.png 统一素材")
        return value

    @field_validator("id")
    @classmethod
    def _id_fixed(cls, value: str) -> str:
        if value not in FIXED_AGENT_IDS:
            raise ValueError(f"第一阶段只允许固定 Agent：{FIXED_AGENT_IDS}")
        return value


class AgentProfile(PersonaSpec):
    system_prompt_path: str
    system_prompt: str
