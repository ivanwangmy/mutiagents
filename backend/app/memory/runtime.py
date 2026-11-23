from __future__ import annotations

from contextlib import AsyncExitStack

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg_pool import AsyncConnectionPool

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MemoryRuntime:
    """LangGraph 短期记忆（Checkpointer）与长期记忆（Store）的 PostgreSQL 运行时。

    两者都使用独立的连接池，启动时建表（setup），关闭时统一释放。
    """

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._pool: AsyncConnectionPool | None = None
        self.checkpointer: AsyncPostgresSaver | None = None
        self.store: AsyncPostgresStore | None = None

    @property
    def conninfo(self) -> str:
        return settings.sync_database_url.replace("postgresql+psycopg://", "postgresql://")

    @property
    def enabled(self) -> bool:
        return settings.checkpointer_backend == "postgres" and not settings.is_sqlite

    async def start(self) -> None:
        if not self.enabled or self.checkpointer is not None:
            return
        try:
            self._pool = AsyncConnectionPool(
                conninfo=self.conninfo,
                min_size=1,
                max_size=6,
                open=False,
                kwargs={"autocommit": True, "prepare_threshold": 0},
            )
            await self._pool.open()
            await self._pool.wait()
            self.checkpointer = AsyncPostgresSaver(self._pool)
            await self.checkpointer.setup()
            self.store = AsyncPostgresStore(self._pool)
            await self.store.setup()
            logger.info("记忆运行时就绪：PostgreSQL checkpointer + store")
        except Exception as exc:  # noqa: BLE001 - 记忆不可用不应阻止服务启动
            logger.error("记忆运行时初始化失败：%s", exc)
            await self.stop()

    async def stop(self) -> None:
        self.checkpointer = None
        self.store = None
        await self._stack.aclose()
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


memory_runtime = MemoryRuntime()
