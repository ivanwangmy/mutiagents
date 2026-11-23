from __future__ import annotations

import asyncio
import json

import pytest

from app.agents import discussion
from app.agents.discussion import DiscussionRunner, parse_decision, pick_opening
from app.agents.registry import registry
from app.core.config import settings
from app.messaging.bus import message_bus
from app.model.base import ModelResponse, ModelUsage


class _FakeBusMessage:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def to_dict(self) -> dict:
        return self.payload


class FakeBus:
    """仅替换落库层，路由与消息字段完全走 DiscussionRunner 的真实逻辑。"""

    def __init__(self) -> None:
        self.published: list[dict] = []

    async def history(self, conversation_id: str, limit: int = 30) -> list[dict]:
        return []

    async def publish(self, **kwargs) -> _FakeBusMessage:
        record = {
            "id": f"msg-{len(self.published) + 1}",
            "conversation_id": kwargs["conversation_id"],
            "task_id": kwargs.get("task_id"),
            "sender_type": "agent" if kwargs.get("sender_agent_id") else "user",
            "sender_agent_id": kwargs.get("sender_agent_id"),
            "receiver_agent_id": kwargs.get("receiver_agent_id"),
            "message_type": kwargs.get("message_type", "message"),
            "content": kwargs.get("content", ""),
            "reply_to_message_id": kwargs.get("reply_to_message_id"),
            "timestamp": "2026-01-01T00:00:00+00:00",
            "metadata": kwargs.get("metadata") or {},
        }
        self.published.append(record)
        return _FakeBusMessage(record)


class FakeBroker:
    """记录实时事件，避免单测写真实数据库。"""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def emit(self, event_type: str, **kwargs):
        self.events.append({"event_type": event_type, **kwargs})
        return None


class ScriptedProvider:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    async def complete(self, messages, **kwargs) -> ModelResponse:
        assert self.replies, "脚本回复已用尽，说明调度轮次超出预期"
        self.calls += 1
        return ModelResponse(
            content=self.replies.pop(0),
            finish_reason="stop",
            usage=ModelUsage(prompt_tokens=10, completion_tokens=5),
            model="scripted",
        )


class FakeModelRegistry:
    def __init__(self, provider: ScriptedProvider) -> None:
        self.provider = provider

    def get(self, **kwargs):
        return self.provider


def _load_registry() -> None:
    if not registry.is_loaded():
        registry.load()


def _decision(action: str, receiver: str | None = None, content: str = "内容") -> str:
    return json.dumps(
        {
            "action": action,
            "receiver": receiver,
            "content": content,
            "reason": "测试",
            "tool": None,
            "reply_to": None,
        },
        ensure_ascii=False,
    )


def _run_discussion(
    monkeypatch: pytest.MonkeyPatch,
    replies: list[str],
    participants: list[str],
    question: str,
):
    _load_registry()
    fake_bus = FakeBus()
    fake_broker = FakeBroker()
    provider = ScriptedProvider(replies)

    async def _no_record(self, *args, **kwargs) -> None:
        return None

    monkeypatch.setattr(discussion, "message_bus", fake_bus)
    monkeypatch.setattr(discussion, "event_broker", fake_broker)
    monkeypatch.setattr(discussion, "model_registry", FakeModelRegistry(provider))
    monkeypatch.setattr(DiscussionRunner, "_record_decision", _no_record)

    runner = DiscussionRunner(
        conversation_id="conv-test",
        task_id="task-test",
        question=question,
        participants=participants,
    )
    result = asyncio.run(runner.run())
    return result, fake_bus, provider


def test_parse_decision_valid_json_with_code_fence() -> None:
    text = "```json\n" + _decision("CHALLENGE", "Alex", "我不同意") + "\n```"
    parsed = parse_decision(text, "mia", ["alex", "mia"])
    assert parsed["action"] == "CHALLENGE"
    assert parsed["receiver"] == "alex"
    assert parsed["content"] == "我不同意"
    assert parsed["fallback"] is False


def test_parse_decision_falls_back_to_real_text() -> None:
    parsed = parse_decision("这道题我先讲定义。", "alex", ["alex", "mia"])
    assert parsed["action"] == "RESPOND"
    assert parsed["fallback"] is True
    assert parsed["content"] == "这道题我先讲定义。"


def test_parse_decision_rejects_unknown_or_self_receiver() -> None:
    unknown = parse_decision(_decision("MESSAGE_AGENT", "lucy"), "alex", ["alex", "mia"])
    assert unknown["action"] == "RESPOND"
    assert unknown["receiver"] is None

    self_target = parse_decision(_decision("REQUEST_HELP", "alex"), "alex", ["alex", "mia"])
    assert self_target["action"] == "RESPOND"
    assert self_target["receiver"] is None


def test_parse_decision_salvages_truncated_json() -> None:
    text = (
        '{"action":"RESPOND","receiver":"ethan","content":'
        '"Ethan 这个反驳抓得准，我那句“能不能脱离 AI 复现”确实有前提'
    )
    parsed = parse_decision(text, "mia", ["alex", "mia", "ethan"])
    assert parsed["action"] == "RESPOND"
    assert parsed["receiver"] is None
    assert parsed["content"].startswith("Ethan 这个反驳抓得准")
    assert not parsed["content"].startswith("{")


def test_parse_decision_drops_stray_receiver_for_respond() -> None:
    parsed = parse_decision(_decision("RESPOND", "ethan"), "alex", ["alex", "ethan"])
    assert parsed["action"] == "RESPOND"
    assert parsed["receiver"] is None


def test_parse_decision_downgrades_broken_tool_call() -> None:
    broken = json.dumps({"action": "USE_TOOL", "content": "我算一下", "tool": {"name": ""}})
    parsed = parse_decision(broken, "alex", ["alex"])
    assert parsed["action"] == "RESPOND"

    silent = json.dumps({"action": "USE_TOOL", "content": "", "tool": None})
    assert parse_decision(silent, "alex", ["alex"])["action"] == "WAIT"


def test_parse_decision_empty_text_is_wait() -> None:
    assert parse_decision("   ", "mia", ["alex", "mia"])["action"] == "WAIT"


def test_pick_opening_depends_on_question_type() -> None:
    participants = ["alex", "mia", "ethan"]
    assert pick_opening(participants, "请解释导数的定义和原理") == "alex"
    assert pick_opening(participants, "我不懂，能不能讲讲学习步骤") == "mia"
    assert pick_opening(participants, "这个说法真的有反例吗") == "ethan"
    # 无关键词时保持参与者顺序，而不是固定轮流
    assert pick_opening(participants, "开始吧") == "alex"


def test_next_agent_respects_receiver_and_finished() -> None:
    _load_registry()
    runner = DiscussionRunner(
        conversation_id="c", task_id="t", question="q", participants=["alex", "mia", "ethan"]
    )
    state = {"spoken_counts": {"mia": 3}, "finished_agents": []}
    assert runner.next_agent(state, "alex", preferred="ethan") == "ethan"
    assert runner.next_agent(state, "alex") == "ethan"

    state["finished_agents"] = ["ethan"]
    assert runner.next_agent(state, "alex") == "mia"

    state["finished_agents"] = ["ethan", "mia"]
    assert runner.next_agent(state, "alex") is None


def test_check_budget_stops_on_each_limit() -> None:
    _load_registry()
    runner = DiscussionRunner(
        conversation_id="c", task_id="t", question="q", participants=["alex", "mia"]
    )
    assert runner.check_budget({}) is None
    assert runner.check_budget({"turn": settings.task_max_turns}) == "max_turns"
    assert (
        runner.check_budget({"model_calls": settings.task_max_model_calls})
        == "max_model_calls"
    )
    assert runner.check_budget({"sent_count": settings.task_max_messages}) == "max_messages"
    assert (
        runner.check_budget({"prompt_tokens": settings.task_token_budget // 2 + 1,
                             "completion_tokens": settings.task_token_budget // 2})
        == "token_budget"
    )


def test_discussion_graph_real_routing_and_conclusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies = [
        _decision("RESPOND", content="导数是函数在某点的瞬时变化率。"),
        _decision("CHALLENGE", "alex", "但它只能描述局部，无法覆盖尖点。"),
        _decision("RESPOND", content="同意，前提是函数在该点可导。"),
        _decision("FINISH", content="", ),
        _decision("FINISH", content="结论：导数描述局部变化率。"),
    ]
    result, bus, provider = _run_discussion(
        monkeypatch, replies, ["alex", "mia"], "请解释导数的定义"
    )

    assert provider.calls == 5
    assert result.turns == 5
    assert result.sent_messages == 4
    assert result.stop_reason == "finish"

    senders = [item["sender_agent_id"] for item in bus.published]
    types = [item["message_type"] for item in bus.published]
    assert senders == ["alex", "mia", "alex", "alex"]
    assert types == ["response", "challenge", "response", "conclusion"]
    # 分歧消息必须明确指向具体参与者
    assert bus.published[1]["receiver_agent_id"] == "alex"
    # 消息字段完整，来自真实总线数据结构
    for item in bus.published:
        assert {"id", "task_id", "message_type", "content", "metadata"} <= set(item)


def test_discussion_stops_when_message_budget_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "task_max_messages", 1)
    replies = [_decision("RESPOND", content="我先说一点。")]
    result, bus, provider = _run_discussion(
        monkeypatch, replies, ["alex", "mia"], "随便聊聊"
    )
    assert provider.calls == 1
    assert len(bus.published) == 1
    assert result.stop_reason == "max_messages"


def test_participants_are_strictly_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    """只有两个参与者时，即使模型想找第三人也会被降级为普通发言。"""
    replies = [
        _decision("MESSAGE_AGENT", "ethan", "请 ethan 回答"),
        _decision("FINISH", content="结束。"),
        _decision("FINISH", content=""),
    ]
    result, bus, _ = _run_discussion(
        monkeypatch, replies, ["alex", "mia"], "讨论一下"
    )
    assert bus.published[0]["message_type"] == "response"
    assert bus.published[0]["receiver_agent_id"] is None
    assert {item["sender_agent_id"] for item in bus.published} <= {"alex", "mia"}
    assert result.stop_reason == "finish"


def test_message_bus_rejects_unknown_type() -> None:
    with pytest.raises(ValueError):
        asyncio.run(
            message_bus.publish(
                conversation_id="c",
                task_id="t",
                sender_agent_id="alex",
                message_type="broadcast",
                content="x",
            )
        )
