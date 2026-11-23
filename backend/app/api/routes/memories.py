from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.registry import registry
from app.memory.manager import MEMORY_TYPES, memory_manager

router = APIRouter(prefix="/agents", tags=["memories"])


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=300)
    memory_type: str = "candidate_memory"
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    keywords: list[str] | None = None


class MemoryPatch(BaseModel):
    content: str | None = Field(default=None, max_length=300)
    memory_type: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: str | None = None
    keywords: list[str] | None = None


def _ensure_agent(agent_id: str) -> None:
    try:
        registry.get(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Agent 不存在：{agent_id}") from exc


@router.get("/{agent_id}/memories")
async def list_memories(agent_id: str, limit: int = 100) -> dict[str, Any]:
    _ensure_agent(agent_id)
    rows = await memory_manager.list(agent_id, limit=limit)
    return {"agent_id": agent_id, "total": len(rows), "memories": rows}


@router.get("/{agent_id}/memories/relevant")
async def relevant_memories(
    agent_id: str, query: str, limit: int | None = None
) -> dict[str, Any]:
    """只返回与 query 相关度超过阈值的记忆，用于证明无关记忆不会进入上下文。"""
    _ensure_agent(agent_id)
    rows = await memory_manager.retrieve(agent_id, query, limit=limit)
    return {"agent_id": agent_id, "query": query, "memories": rows}


@router.post("/{agent_id}/memories", status_code=201)
async def create_memory(agent_id: str, payload: MemoryCreate) -> dict[str, Any]:
    _ensure_agent(agent_id)
    try:
        created = await memory_manager.add(
            agent_id,
            payload.content,
            payload.memory_type,
            confidence=payload.confidence,
            keywords=payload.keywords,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if created is None:
        raise HTTPException(status_code=409, detail="记忆为空、重复或存储不可用")
    return created


@router.patch("/{agent_id}/memories/{key}")
async def update_memory(agent_id: str, key: str, payload: MemoryPatch) -> dict[str, Any]:
    _ensure_agent(agent_id)
    patch = payload.model_dump(exclude_none=True)
    if patch.get("memory_type") not in (None, *MEMORY_TYPES):
        raise HTTPException(status_code=400, detail=f"不支持的记忆类型：{patch['memory_type']}")
    try:
        updated = await memory_manager.update(agent_id, key, patch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return updated


@router.delete("/{agent_id}/memories/{key}", status_code=204)
async def delete_memory(agent_id: str, key: str) -> None:
    _ensure_agent(agent_id)
    if not await memory_manager.delete(agent_id, key):
        raise HTTPException(status_code=404, detail="记忆不存在")
