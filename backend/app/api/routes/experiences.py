from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.registry import registry
from app.memory.experience import (
    EXPERIENCE_TYPES,
    VALIDATION_STATUSES,
    experience_manager,
)

router = APIRouter(prefix="/agents", tags=["experiences"])


class ExperienceCreate(BaseModel):
    experience_type: str
    content: str = Field(min_length=8, max_length=300)
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    keywords: list[str] | None = None


class ExperienceReview(BaseModel):
    validation_status: str
    note: str | None = Field(default=None, max_length=300)


def _ensure_agent(agent_id: str) -> None:
    try:
        registry.get(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Agent 不存在：{agent_id}") from exc


@router.get("/{agent_id}/experiences")
async def list_experiences(
    agent_id: str, status: str | None = None, limit: int = 100
) -> dict[str, Any]:
    _ensure_agent(agent_id)
    if status is not None and status not in VALIDATION_STATUSES:
        raise HTTPException(status_code=400, detail=f"不支持的验证状态：{status}")
    rows = await experience_manager.list(agent_id, status=status, limit=limit)
    return {
        "agent_id": agent_id,
        "total": len(rows),
        "counts": await experience_manager.counts(agent_id),
        "experiences": rows,
    }


@router.get("/{agent_id}/experiences/relevant")
async def relevant_experiences(
    agent_id: str, query: str, limit: int | None = None
) -> dict[str, Any]:
    """只返回相关度达标且已验证的经验；预览不增加使用次数。"""
    _ensure_agent(agent_id)
    rows = await experience_manager.retrieve(
        agent_id, query, limit=limit, mark_used=False
    )
    return {"agent_id": agent_id, "query": query, "experiences": rows}


@router.post("/{agent_id}/experiences", status_code=201)
async def create_experience(agent_id: str, payload: ExperienceCreate) -> dict[str, Any]:
    _ensure_agent(agent_id)
    if payload.experience_type not in EXPERIENCE_TYPES:
        raise HTTPException(
            status_code=400, detail=f"不支持的经验类型：{payload.experience_type}"
        )
    created = await experience_manager.create_candidate(
        agent_id=agent_id,
        experience_type=payload.experience_type,
        content=payload.content,
        confidence=payload.confidence,
        keywords=payload.keywords,
    )
    if created is None:
        raise HTTPException(status_code=409, detail="经验为空、重复或类型不支持")
    return created


@router.patch("/{agent_id}/experiences/{experience_id}")
async def review_experience(
    agent_id: str, experience_id: str, payload: ExperienceReview
) -> dict[str, Any]:
    _ensure_agent(agent_id)
    try:
        updated = await experience_manager.update_review(
            agent_id,
            experience_id,
            validation_status=payload.validation_status,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="经验不存在")
    return updated


@router.delete("/{agent_id}/experiences/{experience_id}", status_code=204)
async def delete_experience(agent_id: str, experience_id: str) -> None:
    _ensure_agent(agent_id)
    if not await experience_manager.delete(agent_id, experience_id):
        raise HTTPException(status_code=404, detail="经验不存在")
