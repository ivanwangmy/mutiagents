"""Agent 能力真实性审计：Skills / Tools 真实执行测试。

只读审计，不修改业务代码；全部通过真实后端与真实模型执行。
用法（cwd=backend）：
    .\\.venv\\Scripts\\python.exe scripts/capability_audit.py
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000/api"
OUT = Path(__file__).resolve().parent / "capability_audit_results.json"
PREFIX = "【AUDIT】"
client = httpx.Client(base_url=BASE, timeout=httpx.Timeout(30.0, read=150.0))
results: list[dict] = []


def run(label: str, agents: list[str], question: str, timeout: float = 150.0) -> dict:
    started = time.perf_counter()
    conv = client.post(
        "/conversations", json={"title": PREFIX + label, "selected_agent_ids": agents}
    ).json()
    sent = client.post(
        f"/conversations/{conv['id']}/messages", json={"content": question}
    ).json()
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/tasks/{sent['task_id']}").json()
        if task["status"] in {"completed", "failed", "stopped"}:
            break
        time.sleep(1.2)
    detail = client.get(f"/conversations/{conv['id']}").json()
    calls = client.get(f"/tasks/{sent['task_id']}/tool-calls").json()
    messages = [m for m in detail["messages"] if m["sender_type"] == "agent"]
    item = {
        "label": label,
        "conversation_id": conv["id"],
        "task_id": sent["task_id"],
        "agents": agents,
        "question": question,
        "status": task["status"],
        "stop_reason": task["stop_reason"],
        "elapsed_s": round(time.perf_counter() - started, 2),
        "model_calls": task["model_calls"],
        "tokens": task["prompt_tokens"] + task["completion_tokens"],
        "tool_calls": [
            {
                "agent_id": c["agent_id"],
                "tool_name": c["tool_name"],
                "status": c["status"],
                "arguments": c["arguments"],
                "result": c["result"],
                "error": c["error"],
                "duration_ms": c["duration_ms"],
            }
            for c in calls
        ],
        "messages": [
            {
                "sender_agent_id": m["sender_agent_id"],
                "receiver_agent_id": m["receiver_agent_id"],
                "message_type": m["message_type"],
                "content": m["content"],
                "metadata": m.get("metadata") or {},
            }
            for m in messages
        ],
    }
    results.append(item)
    tools = [(c["agent_id"], c["tool_name"], c["status"]) for c in item["tool_calls"]]
    print(
        f"== {label} | {task['status']}/{task['stop_reason']} | {item['elapsed_s']}s "
        f"| calls={task['model_calls']} tokens={item['tokens']} | tools={tools}",
        flush=True,
    )
    return item


def main() -> None:
    health = client.get("/health").json()
    caps = client.get("/system/config-status").json()
    print("health:", health, flush=True)
    print("capabilities:", json.dumps(caps, ensure_ascii=False), flush=True)

    run("A-单步计算", ["alex"], "请计算 1876 × 2947，并说明计算过程中的关键步骤。")
    run(
        "B-多步计算",
        ["alex"],
        "先计算 1250 × 36，再将结果除以 15，最后判断结果是否大于 2500。",
    )
    run(
        "C-概念讲解Skill",
        ["alex"],
        "请解释什么是边际成本，并使用一个生活中的例子说明边际成本递增规律。",
    )
    run(
        "D-Skill与Tool协同",
        ["alex"],
        "假设一家企业生产 100 件产品时总成本为 5000 元，生产 120 件时总成本为 5600 元。"
        "请计算这 20 件新增产品的平均增量成本，并解释其经济学含义。",
    )
    run(
        "E1-工具执行错误",
        ["alex"],
        "请用计算器计算 12 ÷ 0，并如实说明发生了什么。",
    )
    run(
        "E2-Python运行错误",
        ["alex"],
        "请用 python_sandbox 执行 print(未定义变量)，把真实错误信息告诉我，不要编造结果。",
    )
    same_question = "请解释什么是边际成本，并用一个生活例子说明边际成本递增规律。"
    for agent_id in ("alex", "mia", "ethan"):
        run(f"F1-差异化-{agent_id}", [agent_id], same_question)
    python_question = "请用 python_sandbox 计算 2 的 20 次方，并只输出真实结果。"
    for agent_id in ("alex", "mia", "ethan"):
        run(f"F2-Python能力-{agent_id}", [agent_id], python_question)
    run(
        "M-多Agent工具协作",
        ["alex", "mia"],
        "请 alex 必须先用计算器计算 1876 × 2947，然后把真实结果交给 mia；"
        "mia 用一句话解释这个数字在课堂统计中的含义。",
    )

    # 若自然提问未触发 use_skill，再补一次显式调用，区分“模型未选择”与“系统不可执行”
    skill_runs = [r for r in results if r["label"].startswith(("C-", "D-"))]
    if not any(c["tool_name"] == "use_skill" for r in skill_runs for c in r["tool_calls"]):
        run(
            "C2-显式Skill调用",
            ["alex"],
            "请先调用 use_skill 工具，加载 concept_explanation 技能，然后严格按照它返回的步骤"
            "解释什么是边际成本，并给出生活例子。",
        )
        run(
            "D2-显式Skill与Tool协同",
            ["alex"],
            "请先调用 use_skill 加载 theory_analysis 技能，再用计算器计算 (5600-5000)/20，"
            "最后按技能步骤解释增量成本的经济学含义。",
        )

    OUT.write_text(
        json.dumps(
            {"finished_at": datetime.now(timezone.utc).isoformat(), "results": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"结果写入 {OUT}", flush=True)


if __name__ == "__main__":
    main()
