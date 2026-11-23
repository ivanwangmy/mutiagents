from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.registry import registry
from app.agents.seed import seed_agents
from app.api.router import api_router
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.session import SessionLocal, init_db
from app.events import event_broker
from app.memory.runtime import memory_runtime
from app.skills.registry import skills_registry

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    settings.ensure_data_dir()
    registry.load()
    skills_registry.load()
    await init_db()
    async with SessionLocal() as session:
        await seed_agents(session)
    logger.info("数据库初始化完成：%s", "sqlite" if settings.is_sqlite else "postgresql")
    await event_broker.startup()
    await memory_runtime.start()
    logger.info("模型：%s（已配置密钥：%s）", settings.deepseek_model, settings.model_configured)
    yield
    await memory_runtime.stop()
    await event_broker.shutdown()
    logger.info("应用关闭")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
