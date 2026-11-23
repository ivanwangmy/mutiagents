from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    database: str
    events: str
    model_configured: bool
    version: str


class SystemInfoResponse(BaseModel):
    app_name: str
    app_env: str
    python_version: str
    platform: str
    database_backend: str
    checkpointer_backend: str
    agent_count: int
    model_name: str
    limits: dict[str, int]


class ConfigStatusResponse(BaseModel):
    model_configured: bool
    model_name: str
    provider: str
    capabilities: dict[str, str | bool]
    missing: list[str]
