from __future__ import annotations

import asyncio

import pytest
from langgraph.store.memory import InMemoryStore

from app.memory.manager import MemoryManager, memory_namespace


def _run(coro):
    return asyncio.run(coro)


def _manager() -> MemoryManager:
    return MemoryManager(InMemoryStore())


def test_add_and_retrieve_only_relevant_memory() -> None:
    manager = _manager()
    _run(
        manager.add(
            "alex",
            "用户叫王明宇，希望被这样称呼",
            "preference_memory",
            confidence=0.9,
            keywords=["王明宇", "称呼"],
        )
    )
    _run(
        manager.add(
            "alex",
            "系统沙箱单次运行限制为 256MB 内存",
            "semantic_memory",
            confidence=0.85,
            keywords=["沙箱", "内存"],
        )
    )

    rows = _run(manager.retrieve("alex", "用户叫什么名字？"))
    assert rows and "王明宇" in rows[0]["content"]
    assert all("沙箱" not in item["content"] for item in rows)

    # 与记忆无关的问题不得注入任何记忆
    assert _run(manager.retrieve("alex", "请解释勾股定理的证明")) == []


def test_memory_isolation_between_agents() -> None:
    manager = _manager()
    _run(manager.add("alex", "用户叫王明宇", "preference_memory", confidence=0.9))
    assert _run(manager.retrieve("mia", "用户叫什么名字")) == []
    assert _run(manager.list("mia")) == []
    assert len(_run(manager.list("alex"))) == 1
    # 命名空间严格按 Agent 隔离
    assert memory_namespace("alex") == ("agents", "alex", "memories")


def test_duplicate_memory_is_rejected() -> None:
    manager = _manager()
    first = _run(manager.add("mia", "用户正在学习导数", "episodic_memory", confidence=0.8))
    second = _run(manager.add("mia", "用户正在学习导数。", "episodic_memory", confidence=0.8))
    assert first is not None
    assert second is None
    assert len(_run(manager.list("mia"))) == 1


def test_low_confidence_becomes_candidate_and_invalid_is_filtered() -> None:
    manager = _manager()
    created = _run(manager.add("ethan", "用户可能对物理感兴趣", "semantic_memory", confidence=0.4))
    assert created is not None
    assert created["status"] == "candidate"

    _run(manager.add("ethan", "用户喜欢用反例学习", "preference_memory", confidence=0.9))
    assert _run(manager.retrieve("ethan", "用户喜欢用什么方式学习")) != []

    _run(manager.update("ethan", created["key"], {"status": "invalid"}))
    rows = _run(manager.retrieve("ethan", "用户可能对物理感兴趣"))
    assert all(item["key"] != created["key"] for item in rows)


def test_update_and_delete_memory() -> None:
    manager = _manager()
    created = _run(manager.add("alex", "用户住在杭州", "semantic_memory", confidence=0.8))
    assert created is not None
    updated = _run(
        manager.update("alex", created["key"], {"content": "用户目前住在上海", "confidence": 0.95})
    )
    assert updated is not None
    assert updated["content"] == "用户目前住在上海"

    assert _run(manager.delete("alex", created["key"])) is True
    assert _run(manager.delete("alex", created["key"])) is False
    assert _run(manager.list("alex")) == []


def test_unknown_memory_type_is_rejected() -> None:
    manager = _manager()
    with pytest.raises(ValueError):
        _run(manager.add("alex", "错误类型", "unknown_memory", confidence=0.9))
