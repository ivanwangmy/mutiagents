from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.agents.config import AgentProfile
from app.agents.registry import registry
from app.schemas.agent import AgentSummary, RuntimeInfo, SkillInfo

router = APIRouter(tags=["agents"])


def _to_summary(profile: AgentProfile) -> AgentSummary:
    return AgentSummary(
        id=profile.id,
        name=profile.name,
        role=profile.role,
        role_label=profile.role_label,
        avatar=profile.avatar,
        theme_color=profile.theme_color,
        short_description=profile.short_description,
        introduction=profile.introduction,
        personality_tags=profile.personality_tags,
        skills=[
            SkillInfo(
                name=s.name,
                id=s.id or s.name,
                version=s.version,
                category=s.category,
                description=s.description,
                execution_logic=s.execution_logic,
                when_to_use=s.when_to_use,
                trigger_conditions=s.trigger_conditions,
                required_inputs=s.required_inputs,
                limitations=s.limitations,
            )
            for s in profile.skills
        ],
        runtime=RuntimeInfo(
            model=profile.runtime.model,
            temperature=profile.runtime.temperature,
            max_output_tokens=profile.runtime.max_output_tokens,
            max_context_tokens=profile.runtime.max_context_tokens,
        ),
        tool_permissions=[tool.name for tool in profile.tool_permissions],
    )


@router.get("/agents", response_model=list[AgentSummary])
async def list_agents() -> list[AgentSummary]:
    return [_to_summary(profile) for profile in registry.all()]


@router.get("/agents/{agent_id}", response_model=AgentSummary)
async def get_agent(agent_id: str) -> AgentSummary:
    try:
        profile = registry.get(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Agent 不存在：{agent_id}") from exc
    return _to_summary(profile)
