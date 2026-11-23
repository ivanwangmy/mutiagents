from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.models import TaskEvent

logger = get_logger(__name__)

TERMINAL_EVENT_TYPES = frozenset({"task_completed", "task_failed", "task_stopped"})
TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "stopped"})

# Redis 频道前缀：每个会话一个频道，频道消息体为 EventRecord JSON
CHANNEL_PREFIX = "classroom:sse:"


@dataclass(slots=True)
class EventRecord:
    event_id: int
    event_type: str
    conversation_id: str
    task_id: str | None
    agent_id: str | None
    payload: dict[str, Any]
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "conversation_id": self.conversation_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp.isoformat(),
            "payload": self.payload or {},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventRecord:
        return cls(
            event_id=int(data["event_id"]),
            event_type=str(data["event_type"]),
            conversation_id=str(data["conversation_id"]),
            task_id=data.get("task_id"),
            agent_id=data.get("agent_id"),
            payload=data.get("payload") or {},
            timestamp=datetime.fromisoformat(str(data["timestamp"])),
        )

    def to_sse(self) -> str:
        data = json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))
        return f"id: {self.event_id}\nevent: {self.event_type}\ndata: {data}\n\n"


class InProcessEventBackend:
    """单进程广播：进程内 asyncio 队列，仅适用于单 worker 开发环境。"""

    name = "memory"

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[EventRecord]]] = {}

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        self._subscribers.clear()

    async def publish(self, record: EventRecord) -> None:
        subscribers = self._subscribers.get(record.conversation_id)
        if not subscribers:
            return
        for queue in tuple(subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(record)
            except asyncio.QueueFull:
                logger.warning("SSE 队列已满，丢弃事件：id=%s", record.event_id)

    @asynccontextmanager
    async def subscribe(self, conversation_id: str) -> AsyncIterator[asyncio.Queue[EventRecord]]:
        queue: asyncio.Queue[EventRecord] = asyncio.Queue(maxsize=1000)
        subscribers = self._subscribers.setdefault(conversation_id, set())
        subscribers.add(queue)
        try:
            yield queue
        finally:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(conversation_id, None)

    def subscriber_count(self, conversation_id: str) -> int:
        return len(self._subscribers.get(conversation_id, ()))


class RedisEventBackend:
    """多进程广播：Redis Pub/Sub。

    事件仍以 PostgreSQL `task_events` 为唯一事实来源（自增 id 即 event_id），
    Redis 只负责把「已落库」的事件实时扇出到所有 worker 的 SSE 连接。
    每个 SSE 连接持有独立的 pubsub 连接，断线重连时走数据库补拉，因此
    Pub/Sub 的至多一次投递不影响正确性。
    """

    name = "redis"

    def __init__(self, url: str, channel_prefix: str = CHANNEL_PREFIX) -> None:
        self._url = url
        self._channel_prefix = channel_prefix
        self._client: Any = None

    async def startup(self) -> None:
        client = await self._ensure_client()
        try:
            await client.ping()
        except Exception:
            await self.shutdown()
            raise

    async def shutdown(self) -> None:
        if self._client is not None:
            with suppress(Exception):
                await self._client.aclose()
            self._client = None

    async def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                from redis.asyncio import Redis
            except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确指引
                raise RuntimeError(
                    "REDIS_URL 已配置但未安装 redis 客户端，请执行 pip install redis"
                ) from exc
            self._client = Redis.from_url(self._url, decode_responses=True)
        return self._client

    def _channel(self, conversation_id: str) -> str:
        return f"{self._channel_prefix}{conversation_id}"

    async def publish(self, record: EventRecord) -> None:
        client = await self._ensure_client()
        await client.publish(
            self._channel(record.conversation_id),
            json.dumps(record.to_dict(), ensure_ascii=False, separators=(",", ":")),
        )

    @asynccontextmanager
    async def subscribe(self, conversation_id: str) -> AsyncIterator[asyncio.Queue[EventRecord]]:
        client = await self._ensure_client()
        channel = self._channel(conversation_id)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        queue: asyncio.Queue[EventRecord] = asyncio.Queue(maxsize=1000)

        async def reader() -> None:
            try:
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        record = EventRecord.from_dict(json.loads(message["data"]))
                    except Exception:  # noqa: BLE001
                        logger.warning("忽略无法解析的 Redis 事件：%s", message.get("data"))
                        continue
                    if queue.full():
                        with suppress(asyncio.QueueEmpty):
                            queue.get_nowait()
                    with suppress(asyncio.QueueFull):
                        queue.put_nowait(record)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis 事件订阅中断：conversation=%s error=%s", conversation_id, exc)

        task = asyncio.create_task(reader())
        try:
            yield queue
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
            with suppress(Exception):
                await pubsub.unsubscribe(channel)
            with suppress(Exception):
                await pubsub.aclose()


class EventBroker:
    """PostgreSQL 持久化 + 可插拔广播后端（进程内 / Redis Pub/Sub）。

    事件先写入 `task_events`（自增 id 即稳定 event_id），再交给后端广播。
    配置 `REDIS_URL` 后可在多进程 / 多 worker 部署下跨进程推送 SSE 事件。
    """

    def __init__(self, backend: InProcessEventBackend | RedisEventBackend | None = None) -> None:
        self._backend = backend or build_event_backend()

    @property
    def backend_name(self) -> str:
        return self._backend.name

    async def startup(self) -> None:
        try:
            await self._backend.startup()
        except Exception as exc:  # noqa: BLE001
            if settings.app_env.lower() in {"development", "dev", "test"}:
                logger.warning(
                    "事件后端 %s 启动失败（%s），开发环境降级为进程内广播",
                    self._backend.name,
                    exc,
                )
                self._backend = InProcessEventBackend()
                return
            raise
        logger.info("事件广播后端：%s", self._backend.name)

    async def shutdown(self) -> None:
        await self._backend.shutdown()

    async def emit(
        self,
        event_type: str,
        *,
        conversation_id: str,
        task_id: str | None = None,
        agent_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> EventRecord | None:
        try:
            async with SessionLocal() as session:
                event = TaskEvent(
                    event_type=event_type,
                    conversation_id=conversation_id,
                    task_id=task_id,
                    agent_id=agent_id,
                    payload=payload or {},
                )
                session.add(event)
                await session.commit()
                await session.refresh(event)
                record = EventRecord(
                    event_id=event.id,
                    event_type=event.event_type,
                    conversation_id=event.conversation_id,
                    task_id=event.task_id,
                    agent_id=event.agent_id,
                    payload=event.payload or {},
                    timestamp=event.created_at,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("事件写入失败：type=%s error=%s", event_type, exc)
            return None

        try:
            await self._backend.publish(record)
        except Exception as exc:  # noqa: BLE001
            # 事件已落库，实时推送失败不影响正确性：客户端重连会从数据库补拉
            logger.warning("事件广播失败：id=%s error=%s", record.event_id, exc)
        return record

    @asynccontextmanager
    async def subscribe(self, conversation_id: str) -> AsyncIterator[asyncio.Queue[EventRecord]]:
        async with self._backend.subscribe(conversation_id) as queue:
            yield queue

    def subscriber_count(self, conversation_id: str) -> int:
        counter = getattr(self._backend, "subscriber_count", None)
        return counter(conversation_id) if counter else 0


def build_event_backend() -> InProcessEventBackend | RedisEventBackend:
    url = (settings.redis_url or "").strip()
    if url:
        return RedisEventBackend(url, settings.event_channel_prefix or CHANNEL_PREFIX)
    return InProcessEventBackend()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


event_broker = EventBroker()
