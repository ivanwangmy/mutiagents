"""三 Agent 全员发言补充验证（禁止 WAIT，按顺序各发言一次）。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000/api"
client = httpx.Client(base_url=BASE, timeout=httpx.Timeout(30.0, read=120.0))

conv = client.post("/conversations", json={
    "title": "【R11-补充】三Agent-全员发言",
    "selected_agent_ids": ["alex", "mia", "ethan"],
}).json()
question = (
    "三位必须都发言，禁止使用 WAIT。顺序：alex 用一句话解释潮汐的主要成因；"
    "mia 用一句话补充一个常见误解；ethan 用一句话提出一个质疑。"
    "每人只发言一次，发言后选择 FINISH。"
)
sent = client.post(f"/conversations/{conv['id']}/messages", json={"content": question}).json()
deadline = time.time() + 150
while time.time() < deadline:
    task = client.get(f"/tasks/{sent['task_id']}").json()
    if task["status"] in {"completed", "failed", "stopped"}:
        break
    time.sleep(1.2)
detail = client.get(f"/conversations/{conv['id']}").json()
msgs = [m for m in detail["messages"] if m["sender_type"] == "agent"]
out = {
    "conversation_id": conv["id"],
    "task_id": sent["task_id"],
    "status": task["status"],
    "stop_reason": task["stop_reason"],
    "model_calls": task["model_calls"],
    "tokens": task["prompt_tokens"] + task["completion_tokens"],
    "senders": sorted({m["sender_agent_id"] for m in msgs if m["sender_agent_id"]}),
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
Path(__file__).resolve().parent.joinpath("round11_triple.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps({k: out[k] for k in ("status", "stop_reason", "model_calls", "tokens", "senders")}, ensure_ascii=False))
