from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.agents.registry import registry
from app.skills.registry import skills_registry
from app.tools.registry import tool_registry

router = APIRouter(tags=["tools"])


@router.get("/tools")
async def list_tools() -> list[dict]:
    """列出真实注册的工具、风险级别与可使用的 Agent。"""
    items: list[dict] = []
    for tool in tool_registry.all():
        items.append(
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category,
                "risk_level": tool.risk_level,
                "requires_isolation": tool.requires_isolation,
                "timeout_seconds": tool.timeout_seconds,
                "error_policy": tool.error_policy,
                "allowed_agents": [
                    profile.id
                    for profile in registry.all()
                    if any(
                        permission.name == tool.name
                        for permission in profile.tool_permissions
                    )
                ],
            }
        )
    items.append(
        {
            "name": "use_skill",
            "description": "加载 Agent 专属 Skill 能力模块并返回执行步骤",
            "category": "skill",
            "risk_level": "low",
            "requires_isolation": False,
            "timeout_seconds": 5.0,
            "error_policy": "缺少必填参数时返回 validation 错误与缺失字段，可补齐后重试",
            "allowed_agents": [
                profile.id
                for profile in registry.all()
                if any(
                    permission.name == "use_skill"
                    for permission in profile.tool_permissions
                )
            ],
        }
    )
    return items


@router.get("/skills")
async def list_skills(agent_id: str | None = None) -> dict:
    """列出 Skill 注册表真实状态；可按 Agent 过滤。"""
    if agent_id is not None:
        try:
            profile = registry.get(agent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Agent 不存在：{agent_id}") from exc
        skills = skills_registry.for_agent(profile.id)
        return {
            "agent_id": profile.id,
            "skills": [
                {
                    "name": skill.name,
                    "id": skill.id,
                    "version": skill.version,
                    "category": skill.category,
                    "description": skill.description,
                    "when_to_use": skill.when_to_use,
                    "required_inputs": skill.required_inputs,
                    "limitations": skill.limitations,
                }
                for skill in skills
            ],
        }
    return {
        "stats": skills_registry.stats(),
        "agents": {
            profile.id: [skill.name for skill in skills_registry.for_agent(profile.id)]
            for profile in registry.all()
        },
    }


@router.get("/skills/match")
async def match_skills(
    agent_id: str = Query(..., description="Agent id"),
    query: str = Query(..., min_length=1, description="任务描述"),
    limit: int = Query(3, ge=1, le=6),
) -> dict:
    """按任务描述检索候选 Skill，用于验证技能发现与选择机制。"""
    try:
        profile = registry.get(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Agent 不存在：{agent_id}") from exc
    matches = skills_registry.match(profile, query, limit=limit)
    return {
        "agent_id": profile.id,
        "query": query,
        "matches": [item.to_payload() for item in matches],
    }
