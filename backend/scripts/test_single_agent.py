r"""第 4 轮单 Agent 真实联调：Alex / Mia / Ethan 各跑真实对话，验证上下文、人格、流式与错误处理。

用法：先启动后端，再执行
  backend\.venv\Scripts\python.exe scripts\test_single_agent.py
"""
from __future__ import annotations

import json
import time

import httpx

BASE = "http://127.0.0.1:8000/api"
client = httpx.Client(base_url=BASE, timeout=120.0)


def create(agent_id: str) -> str:
    resp = client.post("/conversations", json={"selected_agent_ids": [agent_id]})
    resp.raise_for_status()
    return resp.json()["id"]


def ask_and_wait(conversation_id: str, content: str, timeout: float = 120.0) -> dict:
    resp = client.post(f"/conversations/{conversation_id}/messages", json={"content": content})
    resp.raise_for_status()
    task_id = resp.json()["task_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] not in {"pending", "running"}:
            return task
        time.sleep(0.8)
    raise TimeoutError(f"任务 {task_id} 超时未完成")


def messages(conversation_id: str) -> list[dict]:
    return client.get(f"/conversations/{conversation_id}/messages").json()


def main() -> None:
    report: dict = {}

    # 1. Alex 连续两轮
    conv = create("alex")
    t1 = ask_and_wait(conv, "请用三句话解释什么是机会成本，并给出一个校园生活里的例子。")
    msgs = messages(conv)
    assert t1["status"] == "completed", t1
    assert msgs[-1]["sender_agent_id"] == "alex"
    first_answer = msgs[-1]["content"]
    t2 = ask_and_wait(conv, "你刚才举的例子，如果时间是稀缺资源，结论会变吗？")
    msgs = messages(conv)
    assert t2["status"] == "completed"
    second_answer = msgs[-1]["content"]
    report["alex"] = {
        "status": t1["status"],
        "first_answer_preview": first_answer[:120],
        "second_answer_preview": second_answer[:120],
        "message_count": len(msgs),
        "task_usage": {
            "prompt_tokens": t2["prompt_tokens"],
            "completion_tokens": t2["completion_tokens"],
            "model_calls": t2["model_calls"],
        },
    }

    # 2. Mia
    conv_mia = create("mia")
    tm = ask_and_wait(conv_mia, "我不太理解复利，能不能拆成几步讲？")
    assert tm["status"] == "completed"
    mia_answer = messages(conv_mia)[-1]
    assert mia_answer["sender_agent_id"] == "mia"
    report["mia"] = {"status": tm["status"], "preview": mia_answer["content"][:120]}

    # 3. Ethan
    conv_ethan = create("ethan")
    te = ask_and_wait(conv_ethan, "AI 会让人变懒吗？我总觉得这个说法有问题。")
    assert te["status"] == "completed"
    ethan_answer = messages(conv_ethan)[-1]
    assert ethan_answer["sender_agent_id"] == "ethan"
    report["ethan"] = {"status": te["status"], "preview": ethan_answer["content"][:120]}

    # 4. 单 Agent 阶段拒绝多参与者
    multi = client.post("/conversations", json={"selected_agent_ids": ["alex", "mia"]})
    multi.raise_for_status()
    bad = client.post(
        f"/conversations/{multi.json()['id']}/messages", json={"content": "测试多 Agent"}
    )
    report["multi_agent_guard"] = {"status_code": bad.status_code, "detail": bad.json().get("detail")}
    assert bad.status_code == 400

    # 5. 参数校验
    empty = client.post("/conversations", json={"selected_agent_ids": []})
    unknown = client.post("/conversations", json={"selected_agent_ids": ["unknown"]})
    report["validation"] = {
        "empty": empty.status_code,
        "unknown": unknown.status_code,
    }
    assert empty.status_code in (400, 422) and unknown.status_code == 400

    # 6. 真实流式
    conv_stream = create("alex")
    token_count = 0
    done: dict = {}
    events: list[str] = []
    with client.stream(
        "POST",
        f"/conversations/{conv_stream}/messages/stream",
        json={"content": "用一句话说明什么是边际效用。"},
    ) as response:
        response.raise_for_status()
        current = ""
        for line in response.iter_lines():
            if line.startswith("event:"):
                current = line.split(":", 1)[1].strip()
                events.append(current)
            elif line.startswith("data:"):
                payload = json.loads(line.split(":", 1)[1].strip())
                if current == "token":
                    token_count += 1
                elif current in {"done", "error"}:
                    done = payload
    report["stream"] = {
        "events": sorted(set(events)),
        "token_chunks": token_count,
        "done": done.get("content", "")[:120],
        "message_id": done.get("message_id"),
    }
    assert "token" in events and done.get("message_id")

    # 7. 任务用量查询
    usage = client.get(f"/tasks/{t1['id']}/usage").json()
    report["usage"] = usage
    assert usage["total_tokens"] > 0

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
