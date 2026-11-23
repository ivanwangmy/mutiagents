from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import registry
from app.models import Agent, AgentConfigModel, AgentSkill, AgentToolPermission


async def seed_agents(session: AsyncSession) -> None:
    """把代码中的 Agent 配置同步到数据库（幂等）。"""
    for profile in registry.all():
        agent = await session.get(Agent, profile.id)
        if agent is None:
            agent = Agent(id=profile.id)
            session.add(agent)
        agent.name = profile.name
        agent.role = profile.role
        agent.avatar_url = profile.avatar
        agent.theme_color = profile.theme_color
        agent.short_description = profile.short_description
        agent.introduction = profile.introduction
        agent.personality_tags = profile.personality_tags

        config = await session.get(AgentConfigModel, profile.id)
        if config is None:
            config = AgentConfigModel(agent_id=profile.id)
            session.add(config)
        config.system_prompt_path = profile.system_prompt_path
        config.model_name = profile.runtime.model
        config.temperature = profile.runtime.temperature
        config.max_output_tokens = profile.runtime.max_output_tokens
        config.max_context_tokens = profile.runtime.max_context_tokens
        config.memory_namespace = f"agents/{profile.id}/memories"
        config.enabled = True

        await session.execute(delete(AgentSkill).where(AgentSkill.agent_id == profile.id))
        for skill in profile.skills:
            session.add(
                AgentSkill(
                    agent_id=profile.id,
                    skill_name=skill.name,
                    description=skill.description,
                    execution_logic=skill.execution_logic,
                    input_schema=skill.input_schema,
                    output_schema=skill.output_schema,
                    enabled=True,
                )
            )

        await session.execute(
            delete(AgentToolPermission).where(AgentToolPermission.agent_id == profile.id)
        )
        for tool in profile.tool_permissions:
            session.add(
                AgentToolPermission(
                    agent_id=profile.id,
                    tool_name=tool.name,
                    max_calls_per_task=tool.max_calls_per_task,
                    enabled=True,
                )
            )
    await session.commit()


async def load_agent_rows(session: AsyncSession) -> list[Agent]:
    result = await session.execute(select(Agent).order_by(Agent.id))
    return list(result.scalars().all())
