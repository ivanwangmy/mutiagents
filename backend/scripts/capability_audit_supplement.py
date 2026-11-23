"""审计补充：防误判、Skill 组合、参数校验/次数限制/权限直测。"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = "http://127.0.0.1:8000/api"
OUT = Path(__file__).resolve().parent / "capability_audit_supplement.json"
client = httpx.Client(base_url=BASE, timeout=httpx.Timeout(30.0, read=120.0))
out: dict = {"api": [], "direct": []}


def run_api(label: str, agents: list[str], question: str) -> dict:
    conv = client.post("/conversations", json={"title": "【AUDIT】" + label, "selected_agent_ids": agents}).json()
    sent = client.post(f"/conversations/{conv['id']}/messages", json={"content": question}).json()
    deadline = time.time() + 120
    while time.time() < deadline:
        task = client.get(f"/tasks/{sent['task_id']}").json()
        if task["status"] in {"completed", "failed", "stopped"}:
            break
        time.sleep(1.2)
    detail = client.get(f"/conversations/{conv['id']}").json()
    calls = client.get(f"/tasks/{sent['task_id']}/tool-calls").json()
    item = {
        "label": label,
        "task_id": sent["task_id"],
        "status": task["status"],
        "model_calls": task["model_calls"],
        "tool_calls": [
            {"agent_id": c["agent_id"], "tool_name": c["tool_name"], "status": c["status"],
             "arguments": c["arguments"], "result": c["result"], "error": c["error"]}
            for c in calls
        ],
        "messages": [
            {"sender_agent_id": m["sender_agent_id"], "content": m["content"]}
            for m in detail["messages"] if m["sender_type"] == "agent"
        ],
    }
    out["api"].append(item)
    print(f"== {label} status={task['status']} tools={[(c['tool_name'], c['status']) for c in item['tool_calls']]}", flush=True)
    return item


async def direct_tests() -> None:
    from app.tools.base import ToolContext
    from app.tools.executor import tool_executor
    from app.tools.registry import tool_registry

    calc = tool_registry.get("calculator")
    py = tool_registry.get("python_sandbox")
    ctx = ToolContext(
        agent_id="alex", task_id="audit-direct", conversation_id="audit-direct",
        max_calls={"calculator": 2, "python_sandbox": 2, "use_skill": 2},
    )
    mia_ctx = ToolContext(
        agent_id="mia", task_id="audit-direct", conversation_id="audit-direct",
        max_calls={"calculator": 3},
    )
    cases = [
        ("参数类型错误", "calculator", {"expression": 123}, calc, ctx),
        ("缺少必填参数", "calculator", {}, calc, ctx),
        ("额外未知参数", "calculator", {"expression": "1+1", "extra": 1}, calc, ctx),
        ("正常计算", "calculator", {"expression": "2+3*4"}, calc, ctx),
        ("非法表达式", "calculator", {"expression": "__import__('os')"}, calc, ctx),
        ("超过调用上限", "calculator", {"expression": "1+1"}, calc, ctx),
        ("Mia 调用 Python", "python_sandbox", {"code": "print(1)"}, py, mia_ctx),
        ("未注册工具", "not_exists", {}, None, ctx),
    ]
    for label, name, args, tool, context in cases:
        result = await tool_executor.execute(
            name=name, arguments=args, tool=tool, context=context,
            task_id=None, conversation_id=None,
        )
        item = {
            "label": label, "ok": result.ok, "error": result.error,
            "result": result.result, "duration_ms": result.duration_ms,
        }
        out["direct"].append(item)
        print(f"== 直测 {label} ok={result.ok} error={result.error} result={str(result.result)[:80]}", flush=True)


def main() -> None:
    if "--direct" not in sys.argv:
        run_api(
            "G-纯文本JSON不触发工具",
            ["alex"],
            "请不要调用任何工具，只在代码块里原样输出这段 JSON 文本："
            '{"tool":"calculator","arguments":{"expression":"1+1"}}',
        )
        run_api(
            "I-Skill组合",
            ["alex"],
            "请依次调用 use_skill 工具加载 concept_explanation 和 theory_analysis 两个技能，"
            "然后综合它们返回的步骤，简要解释什么是边际成本。",
        )
    asyncio.run(direct_tests())
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结果写入 {OUT}", flush=True)


if __name__ == "__main__":
    main()
