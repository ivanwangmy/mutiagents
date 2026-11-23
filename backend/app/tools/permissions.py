from __future__ import annotations

from typing import Any

from app.agents.config import AgentProfile
from app.core.logging import get_logger
from app.skills.registry import skills_registry
from app.tools.base import ToolDefinition
from app.tools.registry import ToolRegistry, tool_registry

logger = get_logger(__name__)

USE_SKILL = "use_skill"


class ToolPermissionManager:
    """按 AgentProfile 构建真实可用的工具集合。

    权限来源只有 persona 中的 tool_permissions，未登记的工具不会下发给模型，
    也不会在 ToolExecutor 中被执行。
    """

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or tool_registry

    def tools_for(self, profile: AgentProfile) -> dict[str, ToolDefinition]:
        tools: dict[str, ToolDefinition] = {}
        for permission in profile.tool_permissions:
            if permission.name == USE_SKILL:
                tool = self._build_use_skill_tool(profile)
                if tool is not None:
                    tools[USE_SKILL] = tool
                continue
            if not self.registry.has(permission.name):
                logger.warning(
                    "Agent %s 配置了未注册的工具：%s", profile.id, permission.name
                )
                continue
            tools[permission.name] = self.registry.get(permission.name)
        return tools

    def schemas_for(self, profile: AgentProfile) -> list[dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self.tools_for(profile).values()]

    def max_calls_for(self, profile: AgentProfile) -> dict[str, int]:
        return {
            permission.name: permission.max_calls_per_task
            for permission in profile.tool_permissions
        }

    def _build_use_skill_tool(self, profile: AgentProfile) -> ToolDefinition | None:
        skill_names = [skill.name for skill in skills_registry.for_agent(profile.id)]
        if not skill_names:
            return None

        async def handler(arguments: dict[str, Any]) -> Any:
            skill_name = str(arguments.get("skill", ""))
            inputs = arguments.get("input")
            if not isinstance(inputs, dict):
                # 兼容模型把 Skill 字段直接放在顶层的情况，避免无谓失败
                inputs = {
                    key: value
                    for key, value in arguments.items()
                    if key not in {"skill", "input"}
                }
            execution = skills_registry.execute(profile, skill_name, inputs)
            return execution.to_payload()

        lines = []
        for skill in profile.skills:
            if skill.name not in skill_names:
                continue
            required = "、".join(skill.required_inputs) or "无"
            lines.append(
                f"- {skill.name}（{skill.category}）：{skill.description}；"
                f"何时用：{skill.when_to_use or '按需'}；必填参数：{required}"
            )
        catalog = "\n".join(lines)
        return ToolDefinition(
            name=USE_SKILL,
            description=(
                "加载并执行你专属的 Skill 能力模块，返回该能力的执行步骤、检查点"
                "与必须覆盖的输出字段。调用后请按返回步骤完成回答。\n"
                "可用 Skill（必须带齐必填参数）：\n"
                f"{catalog}"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "skill": {
                        "type": "string",
                        "enum": skill_names,
                        "description": "只能选择你自己拥有的 Skill",
                    },
                    "input": {
                        "type": "object",
                        "description": (
                            "Skill 的输入参数；请按所选 Skill 的「必填参数」填写，"
                            "例如 concept_explanation 需要 concept。"
                        ),
                        "additionalProperties": True,
                    },
                },
                "required": ["skill"],
                "additionalProperties": True,
            },
            handler=handler,
            timeout_seconds=5.0,
            category="skill",
            error_policy=(
                "缺少必填参数时返回 validation 错误与缺失字段，模型可补齐后重试；"
                "重试不消耗调用配额。"
            ),
        )


tool_permission_manager = ToolPermissionManager()
