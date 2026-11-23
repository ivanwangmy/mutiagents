r"""第 5 轮真实工具验收：计算器 / 日期时间 / Python 沙箱 / Skill 模块 / 失败回传。

用法：先启动后端，再执行
  backend\.venv\Scripts\python.exe scripts\test_tools.py
"""
from __future__ import annotations

import json
import time

import httpx

BASE = "http://127.0.0.1:8000/api"
client = httpx.Client(base_url=BASE, timeout=180.0)


def create(agent_id: str) -> str:
    resp = client.post("/conversations", json={"selected_agent_ids": [agent_id]})
    resp.raise_for_status()
    return resp.json()["id"]


def ask_and_wait(conversation_id: str, content: str, timeout: float = 180.0) -> dict:
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


def run_case(agent_id: str, prompt: str, tool_name: str) -> dict:
    conversation_id = create(agent_id)
    task = ask_and_wait(conversation_id, prompt)
    calls = client.get(f"/tasks/{task['id']}/tool-calls").json()
    matched = [call for call in calls if call["tool_name"] == tool_name]
    messages = client.get(f"/conversations/{conversation_id}/messages").json()
    answer = messages[-1]["content"] if messages else ""
    return {
        "agent": agent_id,
        "task_status": task["status"],
        "model_calls": task["model_calls"],
        "tool_calls": calls,
        "expected_tool": tool_name,
        "matched": matched,
        "answer": answer,
        "usage": {
            "prompt_tokens": task["prompt_tokens"],
            "completion_tokens": task["completion_tokens"],
        },
    }


def main() -> None:
    report: dict = {}

    calc = run_case(
        "alex",
        "请调用 calculator 工具计算 (123*45+678)/3，然后告诉我结果。必须真实调用工具，不要心算。",
        "calculator",
    )
    calc_ok = [call for call in calc["matched"] if call["status"] == "success"]
    assert calc["task_status"] == "completed", calc
    assert calc_ok, calc["matched"]
    assert calc_ok[-1]["result"]["result"]["value"] == 2071, calc_ok[-1]
    report["calculator"] = calc

    clock = run_case(
        "mia",
        "请调用 datetime 工具查询 Asia/Shanghai 的当前日期和时间，然后用一句话告诉我今天星期几。必须真实调用工具。",
        "datetime",
    )
    clock_ok = [call for call in clock["matched"] if call["status"] == "success"]
    assert clock["task_status"] == "completed", clock
    assert clock_ok, clock["matched"]
    assert clock_ok[-1]["result"]["result"]["date"], clock_ok[-1]
    report["datetime"] = clock

    sandbox = run_case(
        "ethan",
        "请调用 python_sandbox 工具执行 Python 代码，用 print 输出前 10 个斐波那契数。必须真实调用工具，不要直接给我结果。",
        "python_sandbox",
    )
    sandbox_ok = [call for call in sandbox["matched"] if call["status"] == "success"]
    assert sandbox["task_status"] == "completed", sandbox
    assert sandbox_ok, sandbox["matched"]
    assert "34" in sandbox_ok[-1]["result"]["result"]["output"], sandbox_ok[-1]
    report["python_sandbox"] = sandbox

    denied = run_case(
        "ethan",
        "请调用 python_sandbox 执行这段代码：import os\nprint(os.getcwd())\n如果失败，请解释原因。",
        "python_sandbox",
    )
    assert denied["task_status"] == "completed", denied
    assert denied["matched"], denied
    assert denied["matched"][-1]["status"] == "error", denied["matched"][-1]
    assert "os" in (denied["matched"][-1]["error"] or ""), denied["matched"][-1]
    report["sandbox_denied"] = denied

    skill = run_case(
        "alex",
        "请调用 use_skill 加载你的 concept_explanation 能力，input 为 {\"concept\": \"机会成本\"}，"
        "然后严格按照返回的步骤，用三句话解释机会成本。",
        "use_skill",
    )
    skill_ok = [call for call in skill["matched"] if call["status"] == "success"]
    assert skill["task_status"] == "completed", skill
    assert skill_ok, skill["matched"]
    assert skill_ok[-1]["result"]["result"]["skill"] == "concept_explanation", skill_ok[-1]
    assert "definition" in skill_ok[-1]["result"]["result"]["output_fields"], skill_ok[-1]
    report["use_skill"] = skill

    tools = client.get("/tools").json()
    report["registered_tools"] = [
        {"name": item["name"], "allowed_agents": item["allowed_agents"]} for item in tools
    ]
    assert {item["name"] for item in tools} >= {
        "calculator",
        "datetime",
        "python_sandbox",
        "use_skill",
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
