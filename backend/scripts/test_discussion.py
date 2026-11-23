r"""第 6 轮验收：多 Agent 自主协作（真实 DeepSeek 模型 + 真实 Message Bus + PostgreSQL）。

用法（先启动后端 backend\.venv\Scripts\python.exe run_server.py）：
  backend\.venv\Scripts\python.exe scripts\test_discussion.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402

BASE = "http://127.0.0.1:8000/api"
MESSAGE_TYPES = {
    "message",
    "question",
    "response",
    "challenge",
    "request_help",
    "handoff",
    "conclusion",
}
DSN = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
client = httpx.Client(base_url=BASE, timeout=300.0)


def event_counts(task_id: str) -> dict[str, int]:
    """直接查 PostgreSQL，证明事件与消息确实落库。"""
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT event_type, count(*) FROM task_events "
                "WHERE task_id = %s GROUP BY event_type",
                (task_id,),
            )
            return {row[0]: row[1] for row in cur.fetchall()}


def create_conversation(agent_ids: list[str]) -> str:
    resp = client.post("/conversations", json={"selected_agent_ids": agent_ids})
    resp.raise_for_status()
    return resp.json()["id"]


def ask(conversation_id: str, content: str) -> str:
    resp = client.post(
        f"/conversations/{conversation_id}/messages", json={"content": content}
    )
    resp.raise_for_status()
    return resp.json()["task_id"]


def wait_task(task_id: str, timeout: float = 280.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] not in {"pending", "running"}:
            return task
        time.sleep(0.8)
    raise TimeoutError(f"任务 {task_id} 超时未完成")


def agent_messages(conversation_id: str) -> list[dict]:
    messages = client.get(f"/conversations/{conversation_id}/messages").json()
    return [message for message in messages if message["sender_type"] == "agent"]


def run_case(name: str, agent_ids: list[str], prompt: str) -> dict:
    conversation_id = create_conversation(agent_ids)
    task = wait_task(ask(conversation_id, prompt))
    return {
        "case": name,
        "conversation_id": conversation_id,
        "task": task,
        "messages": agent_messages(conversation_id),
        "events": event_counts(task["id"]),
    }


def check_common(case: dict) -> set[str]:
    task = case["task"]
    messages = case["messages"]
    assert task["status"] == "completed", json.dumps(task, ensure_ascii=False)
    assert task["model_calls"] >= 1, "没有真实模型调用"
    assert task["model_calls"] <= settings.task_max_model_calls, task
    spent = task["prompt_tokens"] + task["completion_tokens"]
    assert spent <= settings.task_token_budget, (spent, settings.task_token_budget)
    assert task["turn_count"] <= settings.task_max_turns, task
    assert messages, "Agent 没有产生任何消息"
    senders = {message["sender_agent_id"] for message in messages}
    assert senders <= set(task["participating_agent_ids"]), (
        f"出现未选中 Agent：{senders} - {task['participating_agent_ids']}"
    )
    return senders


def check_bus(case: dict) -> None:
    """核对每一条消息都来自真实 Message Bus 并带决策元数据。"""
    messages = case["messages"]
    task = case["task"]
    for message in messages:
        assert message["task_id"] == task["id"], message
        assert message["message_type"] in MESSAGE_TYPES, message
        metadata = message["metadata"] or {}
        assert metadata.get("action"), f"消息缺少决策来源：{message['id']}"
        assert metadata.get("model") == settings.deepseek_model, metadata
    assert case["events"].get("message.published", 0) == len(messages), case["events"]
    assert case["events"].get("agent.decision", 0) >= len(messages), case["events"]
    assert case["events"].get("task.finished", 0) == 1, case["events"]


def summarize(case: dict) -> dict:
    task = case["task"]
    return {
        "case": case["case"],
        "status": task["status"],
        "stop_reason": task["stop_reason"],
        "participants": task["participating_agent_ids"],
        "turns": task["turn_count"],
        "model_calls": task["model_calls"],
        "tokens": task["prompt_tokens"] + task["completion_tokens"],
        "senders": sorted({m["sender_agent_id"] for m in case["messages"]}),
        "messages": [
            {
                "from": message["sender_agent_id"],
                "to": message["receiver_agent_id"],
                "type": message["message_type"],
                "action": (message["metadata"] or {}).get("action"),
                "content": message["content"][:80],
            }
            for message in case["messages"]
        ],
        "events": case["events"],
    }


def main() -> None:
    report: list[dict] = []

    # 场景一：只选择 Alex，其他 Agent 不得出现（走单 Agent 执行器）
    one = run_case("场景一：仅 Alex", ["alex"], "请用两句话解释导数的定义，并举一个生活例子。")
    senders = check_common(one)
    assert senders == {"alex"}, senders
    report.append(summarize(one))

    # 场景二：Alex 做理论分析，Ethan 提出自己的问题或观点
    two = run_case(
        "场景二：Alex + Ethan",
        ["alex", "ethan"],
        "请 Alex 从理论上解释导数的几何意义；Ethan 请结合自己的理解，"
        "提出至少一个具体疑问或不同观点。",
    )
    senders = check_common(two)
    check_bus(two)
    assert senders == {"alex", "ethan"}, f"两人未都参与：{senders}"
    report.append(summarize(two))

    # 场景三：三个 Agent 自主决定参与程度
    three = run_case(
        "场景三：三 Agent 自主参与",
        ["alex", "mia", "ethan"],
        "我们应该如何理解人工智能对教育的影响？请结合各自角色自主决定是否发言。",
    )
    senders = check_common(three)
    check_bus(three)
    assert len(senders) >= 2, f"三人场景只有 {senders} 参与"
    report.append(summarize(three))

    # 场景四：观点分歧，必须指出具体分歧
    clash = run_case(
        "场景四：观点分歧",
        ["alex", "mia", "ethan"],
        "有观点认为：学生完全不应该用 AI 做作业。请不同角色明确表达立场，"
        "并直接指出你与另一位参与者观点中的具体分歧。",
    )
    check_common(clash)
    check_bus(clash)
    challenges = [
        message
        for message in clash["messages"]
        if message["message_type"] == "challenge"
        or (message["metadata"] or {}).get("action") == "CHALLENGE"
    ]
    assert challenges, "没有出现 CHALLENGE 消息"
    for message in challenges:
        assert message["receiver_agent_id"], message
        assert len(message["content"]) >= 20, message
    report.append(summarize(clash))

    # 场景五：讨论没有必要继续时合理结束，不强制所有人发言
    quick = run_case(
        "场景五：合理结束",
        ["alex", "mia", "ethan"],
        "请只回答：1 + 1 等于几？",
    )
    check_common(quick)
    check_bus(quick)
    assert len(quick["messages"]) <= 3, [m["content"] for m in quick["messages"]]
    assert quick["task"]["status"] == "completed"
    report.append(summarize(quick))

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("\nALL DISCUSSIONS PASSED")


if __name__ == "__main__":
    main()
