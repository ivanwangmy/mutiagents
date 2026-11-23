from __future__ import annotations

import json
from datetime import datetime, timezone

from app.core.config import settings
from app.events import (
    EventRecord,
    InProcessEventBackend,
    RedisEventBackend,
    build_event_backend,
)


def test_event_record_sse_roundtrip() -> None:
    record = EventRecord(
        event_id=12,
        event_type="agent_message",
        conversation_id="conv-1",
        task_id="task-1",
        agent_id="alex",
        payload={"message": {"id": "msg-1", "content": "导数"}},
        timestamp=datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc),
    )
    sse = record.to_sse()
    assert sse.startswith("id: 12\nevent: agent_message\ndata: ")
    assert sse.endswith("\n\n")
    data = json.loads(sse.split("data: ", 1)[1].strip())
    assert EventRecord.from_dict(data) == record


def test_backend_selection_follows_redis_url(monkeypatch) -> None:
    monkeypatch.setattr(settings, "redis_url", "")
    assert isinstance(build_event_backend(), InProcessEventBackend)

    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:6379/0")
    backend = build_event_backend()
    assert isinstance(backend, RedisEventBackend)
    assert backend.name == "redis"
