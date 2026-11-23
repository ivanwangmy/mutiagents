from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.agents.config import SkillSpec


@dataclass(slots=True)
class SkillExecution:
    """一次 Skill 能力模块的真实执行结果（第二层：加载完整内容）。"""

    skill: str
    description: str
    inputs: dict[str, Any]
    steps: list[str]
    checks: list[str]
    output_fields: list[str] = field(default_factory=list)
    skill_id: str = ""
    version: str = "1.0.0"
    category: str = "method"
    required_inputs: list[str] = field(default_factory=list)
    error_handling: str = ""
    limitations: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "skill_id": self.skill_id or self.skill,
            "version": self.version,
            "category": self.category,
            "description": self.description,
            "inputs": self.inputs,
            "required_inputs": self.required_inputs,
            "steps": self.steps,
            "checks": self.checks,
            "output_fields": self.output_fields,
            "error_handling": self.error_handling,
            "limitations": self.limitations,
        }


SkillHandler = Callable[[SkillSpec, dict[str, Any]], SkillExecution]


def build_execution(
    skill: SkillSpec,
    inputs: dict[str, Any],
    steps: list[str],
    checks: list[str],
) -> SkillExecution:
    """把 SkillSpec 的完整元数据与 handler 的执行步骤合并为返回体。"""
    return SkillExecution(
        skill=skill.name,
        skill_id=skill.id or skill.name,
        version=skill.version,
        category=skill.category,
        description=skill.description,
        inputs=inputs,
        required_inputs=skill.required_inputs,
        steps=steps or list(skill.execution_steps),
        checks=checks,
        output_fields=list((skill.output_schema.get("properties") or {}).keys()),
        error_handling=skill.error_handling,
        limitations=list(skill.limitations),
    )
