from fastapi import APIRouter

from app.api.routes import agents, conversations, experiences, memories, system, tasks, tools

api_router = APIRouter(prefix="/api")
api_router.include_router(system.router)
api_router.include_router(agents.router)
api_router.include_router(memories.router)
api_router.include_router(experiences.router)
api_router.include_router(conversations.router)
api_router.include_router(tasks.router)
api_router.include_router(tools.router)
