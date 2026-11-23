r"""第 7 轮验收：Checkpointer 短期记忆 + Store 长期记忆（真实模型 + PostgreSQL）。

用法（先启动后端 backend\.venv\Scripts\python.exe run_server.py）：
  backend\.venv\Scripts\python.exe scripts\test_memory.py
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
DSN = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
client = httpx.Client(base_url=BASE, timeout=180.0)


def create_conversation(agent_ids: list[str]) -> str:
    response = client.post("/conversations", json={"selected_agent_ids": agent_ids})
    response.raise_for_status()
    return response.json()["id"]


def ask(conversation_id: str, content: str) -> str:
    response = client.post(
        f"/conversations/{conversation_id}/messages", json={"content": content}
    )
    response.raise_for_status()
    return response.json()["task_id"]


def wait_task(task_id: str, timeout: float = 150.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] not in {"pending", "running"}:
            return task
        time.sleep(0.6)
    raise TimeoutError(f"任务 {task_id} 超时")


def agent_messages(conversation_id: str) -> list[dict]:
    rows = client.get(f"/conversations/{conversation_id}/messages").json()
    return [row for row in rows if row["sender_type"] == "agent"]


def memories(agent_id: str) -> list[dict]:
    response = client.get(f"/agents/{agent_id}/memories")
    response.raise_for_status()
    return response.json()["memories"]


def wait_memory(agent_id: str, keyword: str, timeout: float = 40.0) -> list[dict]:
    deadline = time.time() + timeout
    latest: list[dict] = []
    while time.time() < deadline:
        latest = memories(agent_id)
        if any(keyword in str(row.get("content", "")) for row in latest):
            return latest
        time.sleep(1.0)
    raise AssertionError(
        f"{agent_id} 未提取到包含「{keyword}」的长期记忆，当前记忆："
        + json.dumps(latest, ensure_ascii=False)
    )


def db_count(sql: str) -> int:
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return int(cur.fetchone()[0])


def main() -> None:
    report: dict = {}

    # 1. 同一对话：先告知姓名与偏好，再追问
    conversation_a = create_conversation(["alex"])
    first_task = ask(
        conversation_a,
        "请记住：我叫王明宇，我偏好用生活例子学习。请简短确认你记住了。",
    )
    wait_task(first_task)
    stored = wait_memory("alex", "王明宇")
    report["extracted_memories"] = [
        {"type": row.get("memory_type"), "content": row.get("content"), "status": row.get("status")}
        for row in stored
    ]

    follow_task = ask(conversation_a, "我的名字是什么？只用一句话回答。")
    follow = wait_task(follow_task)
    history = agent_messages(conversation_a)
    tail = history[-1]
    assert "王明宇" in tail["content"], tail["content"]
    assert tail["metadata"].get("memory_keys"), "本轮未注入任何记忆"
    report["same_conversation_recall"] = {
        "answer": tail["content"][:80],
        "memory_keys": tail["metadata"]["memory_keys"],
        "task_id": follow["id"],
    }

    # 2. 新对话仍能使用长期记忆（跨对话恢复）
    conversation_new = create_conversation(["alex"])
    recall_task = ask(conversation_new, "用户叫什么名字？")
    wait_task(recall_task)
    recall = agent_messages(conversation_new)[-1]
    assert "王明宇" in recall["content"], recall["content"]
    report["cross_conversation_recall"] = {
        "answer": recall["content"][:80],
        "memory_keys": recall["metadata"].get("memory_keys"),
    }

    # 3. 记忆隔离：Mia 不得看到 Alex 的用户记忆
    mia_memories = memories("mia")
    assert all("王明宇" not in str(row.get("content", "")) for row in mia_memories), mia_memories
    conversation_mia = create_conversation(["mia"])
    mia_task = ask(conversation_mia, "用户叫什么名字？如果不知道就明确说不知道。")
    wait_task(mia_task)
    mia_answer = agent_messages(conversation_mia)[-1]
    assert "王明宇" not in mia_answer["content"], mia_answer["content"]
    assert not mia_answer["metadata"].get("memory_keys"), "Mia 不应注入 Alex 的记忆"
    report["isolation"] = {
        "mia_memory_count": len(mia_memories),
        "mia_answer": mia_answer["content"][:80],
    }

    # 4. 无关记忆过滤
    irrelevant = client.post(
        "/agents/alex/memories",
        json={
            "content": "系统沙箱单次运行限制为 256MB 内存",
            "memory_type": "semantic_memory",
            "confidence": 0.9,
        },
    )
    if irrelevant.status_code != 409:
        irrelevant.raise_for_status()
    relevant_rows = client.get(
        "/agents/alex/memories/relevant", params={"query": "用户叫什么名字"}
    ).json()["memories"]
    assert all("沙箱" not in row["content"] for row in relevant_rows), relevant_rows
    sandbox_rows = client.get(
        "/agents/alex/memories/relevant", params={"query": "沙箱内存限制是多少"}
    ).json()["memories"]
    assert any("沙箱" in row["content"] for row in sandbox_rows), sandbox_rows
    report["relevance_filter"] = {
        "name_query_hits": len(relevant_rows),
        "sandbox_query_hits": len(sandbox_rows),
    }

    # 5. 删除与失效
    created = client.post(
        "/agents/alex/memories",
        json={"content": "临时记忆：用户明天考试", "confidence": 0.6},
    ).json()
    key = created["key"]
    client.patch(
        f"/agents/alex/memories/{key}",
        json={"status": "invalid", "content": "用户明天考试（已过期）"},
    ).raise_for_status()
    invalid_row = next(row for row in memories("alex") if row["key"] == key)
    assert invalid_row["status"] == "invalid"
    client.delete(f"/agents/alex/memories/{key}").raise_for_status()
    assert all(row["key"] != key for row in memories("alex"))
    report["invalidation"] = {"key": key, "deleted": True}

    # 6. Checkpointer 短期状态与数据库落库
    checkpoint = client.get(f"/tasks/{first_task}/checkpoint").json()
    assert checkpoint["enabled"] is True, checkpoint
    assert checkpoint["checkpoint_id"], checkpoint
    assert checkpoint["model_calls"] and checkpoint["model_calls"] >= 1, checkpoint
    report["checkpoint"] = checkpoint
    report["database"] = {
        "checkpoints": db_count("SELECT count(*) FROM checkpoints"),
        "checkpoint_blobs": db_count("SELECT count(*) FROM checkpoint_blobs"),
        "store_items": db_count("SELECT count(*) FROM store"),
    }
    assert report["database"]["checkpoints"] > 0
    assert report["database"]["store_items"] > 0

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("\nALL MEMORY TESTS PASSED")


if __name__ == "__main__":
    main()
