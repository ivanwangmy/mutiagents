"""第 11 轮补充验收：定向质疑 + 三 Agent 全员发言 + 模型自主 FINISH。

针对主脚本中“双 Agent 组合未出现定向消息”“三 Agent 仅两人发言”的观察，
用更明确但不指定内容的提问，验证系统本身具备定向消息与自然结束能力。

用法（cwd=backend）：
    .\\.venv\\Scripts\\python.exe scripts/acceptance_round11_extra.py
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000/api"
OUT = Path(__file__).resolve().parent / "round11_extra.json"
client = httpx.Client(base_url=BASE, timeout=httpx.Timeout(30.0, read=150.0))
results: list[dict] = []


def create(agents: list[str], title: str) -> dict:
    r = client.post("/conversations", json={"title": "【R11-补充】" + title, "selected_agent_ids": agents})
    r.raise_for_status()
    return r.json()


def wait(task_id: str, timeout: float = 150.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] in {"completed", "failed", "stopped"}:
            return task
        time.sleep(1.2)
    return client.get(f"/tasks/{task_id}").json()


def run(label: str, agents: list[str], question: str) -> None:
    started = time.perf_counter()
    conv = create(agents, label)
    sent = client.post(f"/conversations/{conv['id']}/messages", json={"content": question}).json()
    task = wait(sent["task_id"])
    detail = client.get(f"/conversations/{conv['id']}").json()
    msgs = [m for m in detail["messages"] if m["sender_type"] == "agent"]
    elapsed = round(time.perf_counter() - started, 2)
    item = {
        "label": label,
        "conversation_id": conv["id"],
        "task_id": sent["task_id"],
        "agents": agents,
        "status": task["status"],
        "stop_reason": task["stop_reason"],
        "elapsed_s": elapsed,
        "model_calls": task["model_calls"],
        "tokens": task["prompt_tokens"] + task["completion_tokens"],
        "messages": [
            {
                "sender_agent_id": m["sender_agent_id"],
                "receiver_agent_id": m["receiver_agent_id"],
                "message_type": m["message_type"],
                "content": m["content"],
            }
            for m in msgs
        ],
    }
    results.append(item)
    senders = sorted({m["sender_agent_id"] for m in msgs if m["sender_agent_id"]})
    challenges = [m for m in msgs if m["message_type"] == "challenge"]
    directed = [m for m in msgs if m["receiver_agent_id"]]
    print(
        f"== {label} status={task['status']} stop={task['stop_reason']} "
        f"senders={senders} msgs={len(msgs)} challenge={len(challenges)} "
        f"directed={len(directed)} {elapsed}s",
        flush=True,
    )


def main() -> None:
    run(
        "双Agent-alex+mia-定向",
        ["alex", "mia"],
        "请 alex 用两三句话解释光合作用。mia 必须用 CHALLENGE 指出 alex 解释中的一个具体分歧点，"
        "alex 再用一句话回应。双方发言结束后都选择 FINISH。",
    )
    run(
        "双Agent-mia+ethan-定向",
        ["mia", "ethan"],
        "请 mia 用两三句话通俗解释独立事件。ethan 必须用 CHALLENGE 质疑 mia 说法中的一个具体点，"
        "mia 再用一句话回应。双方发言结束后都选择 FINISH。",
    )
    run(
        "三Agent-全员",
        ["alex", "mia", "ethan"],
        "为什么会有四季？alex 用一句话讲原理，ethan 用一句话质疑其中一点，mia 用一句话总结。"
        "每人只发言一次，发言后选择 FINISH。",
    )
    payload = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "tasks": results,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结果写入 {OUT}", flush=True)


if __name__ == "__main__":
    main()
