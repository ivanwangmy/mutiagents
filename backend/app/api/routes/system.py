from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import check_database, get_session
from app.events import event_broker
from app.models import Agent
from app.schemas.system import ConfigStatusResponse, HealthResponse, SystemInfoResponse

router = APIRouter(tags=["system"])

CAPABILITY_FILE = Path(__file__).resolve().parents[3] / "data" / "model_capabilities.json"


def _load_capabilities() -> dict:
    if CAPABILITY_FILE.exists():
        try:
            return json.loads(CAPABILITY_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    db_state = "ok"
    try:
        await check_database()
    except Exception as exc:  # noqa: BLE001
        db_state = f"error: {type(exc).__name__}"
    return HealthResponse(
        status="ok" if db_state == "ok" else "degraded",
        database=db_state,
        events=event_broker.backend_name,
        model_configured=settings.model_configured,
        version="0.1.0",
    )


@router.get("/system/info", response_model=SystemInfoResponse)
async def system_info(session: AsyncSession = Depends(get_session)) -> SystemInfoResponse:
    agent_count = (await session.execute(select(func.count()).select_from(Agent))).scalar_one()
    return SystemInfoResponse(
        app_name=settings.app_name,
        app_env=settings.app_env,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        database_backend="sqlite" if settings.is_sqlite else "postgresql",
        checkpointer_backend=settings.checkpointer_backend,
        agent_count=int(agent_count),
        model_name=settings.deepseek_model,
        limits={
            "max_output_tokens": settings.max_output_tokens,
            "max_context_tokens": settings.max_context_tokens,
            "task_token_budget": settings.task_token_budget,
            "task_max_model_calls": settings.task_max_model_calls,
            "task_max_messages": settings.task_max_messages,
            "task_max_turns": settings.task_max_turns,
            "task_max_seconds": settings.task_max_seconds,
        },
    )


@router.get("/system/config-status", response_model=ConfigStatusResponse)
async def config_status() -> ConfigStatusResponse:
    missing: list[str] = []
    if not settings.model_configured:
        missing.append("DEEPSEEK_API_KEY")

    probe = _load_capabilities()
    capabilities: dict[str, str | bool] = {
        "text": "unknown",
        "stream": "unknown",
        "tool_calling": "unknown",
        "structured_output": "unknown",
    }
    if probe:
        for key in ("text", "stream", "tool_calling", "structured_output"):
            value = probe.get(key)
            capabilities[key] = bool(value.get("ok")) if isinstance(value, dict) else "unknown"
        if probe.get("configured_model") and probe["configured_model"] != settings.deepseek_model:
            capabilities["probe_model_mismatch"] = probe["configured_model"]

    return ConfigStatusResponse(
        model_configured=settings.model_configured,
        model_name=settings.deepseek_model,
        provider="deepseek",
        capabilities=capabilities,
        missing=missing,
    )
