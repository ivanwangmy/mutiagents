"""本轮能力升级的真实验收脚本。

直接调用运行中的后端与真实 DeepSeek 模型，不使用任何模拟工具或硬编码答案。
运行：
    .\\.venv\\Scripts\\python.exe scripts/capability_upgrade_verify.py
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "http://127.0.0.1:8000"
OUT_PATH = Path(__file__).resolve().parent / "capability_upgrade_results.json"
TERMINAL = {"completed", "failed", "stopped"}


def create_conversation(client: httpx.Client, agents: list[str], title: str) -> str:
    response = client.post(
        "/api/conversations", json={"title": title, "selected_agent_ids": agents}
    )
    response.raise_for_status()
    return response.json()["id"]


def send_and_wait(
    client: httpx.Client,
    conversation_id: str,
    content: str,
    timeout_seconds: int = 240,
) -> dict[str, Any]:
    response = client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": content}
    )
    response.raise_for_status()
    task_id = response.json()["task_id"]
    started = time.time()
    task: dict[str, Any] = {}
    while time.time() - started < timeout_seconds:
        task = client.get(f"/api/tasks/{task_id}").json()
        if task.get("status") in TERMINAL:
            break
        time.sleep(1.2)
    messages = client.get(f"/api/conversations/{conversation_id}/messages").json()
    tool_calls = client.get(f"/api/tasks/{task_id}/tool-calls").json()
    usage = client.get(f"/api/tasks/{task_id}/usage").json()
    agent_messages = [m for m in messages if m.get("sender_type") == "agent"]
    return {
        "task_id": task_id,
        "task": task,
        "messages": agent_messages,
        "tool_calls": tool_calls,
        "usage": usage,
        "elapsed_seconds": round(time.time() - started, 2),
    }


def tool_names(result: dict[str, Any]) -> list[str]:
    return [item.get("tool_name") for item in result.get("tool_calls") or []]


def ok_tools(result: dict[str, Any]) -> list[str]:
    return [
        item.get("tool_name")
        for item in result.get("tool_calls") or []
        if item.get("status") == "success"
    ]


def failed_tools(result: dict[str, Any]) -> list[str]:
    return [
        item.get("tool_name")
        for item in result.get("tool_calls") or []
        if item.get("status") == "error"
    ]


def answer(result: dict[str, Any]) -> str:
    if not result["messages"]:
        return ""
    return result["messages"][-1]["content"]


def style_hits(text: str) -> dict[str, int]:
    markers = {
        "definition": len(re.findall(r"定义|边界|前提|成立条件", text)),
        "structure": len(re.findall(r"第一|第二|步骤|拆解|先.{0,6}再", text)),
        "challenge": len(re.findall(r"质疑|反例|假设|不一定|值得怀疑|我不同意", text)),
        "question": len(re.findall(r"[？?]", text)),
        "evidence": len(re.findall(r"因为|证据|数据|计算|根据", text)),
    }
    return markers


def stream_single_agent(
    client: httpx.Client, conversation_id: str, content: str
) -> dict[str, Any]:
    """真实流式请求：验证流式路径也能完成原生工具调用。"""
    tokens: list[str] = []
    done: dict[str, Any] = {}
    event_type = None
    data_lines: list[str] = []
    started = time.time()
    with client.stream(
        "POST",
        f"/api/conversations/{conversation_id}/messages/stream",
        json={"content": content},
        timeout=180,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
            elif line == "":
                if event_type and data_lines:
                    payload = json.loads("\n".join(data_lines))
                    if event_type == "token":
                        tokens.append(payload.get("text") or "")
                    elif event_type == "done":
                        done = payload
                event_type = None
                data_lines = []
    return {
        "content": "".join(tokens),
        "done": done,
        "elapsed_seconds": round(time.time() - started, 2),
    }


def read_events(client: httpx.Client, conversation_id: str, task_id: str) -> list[dict]:
    events: list[dict] = []
    try:
        with client.stream(
            "GET",
            f"/api/conversations/{conversation_id}/events",
            params={"task_id": task_id, "last_event_id": 0},
            timeout=20,
        ) as response:
            event_type = None
            data_lines: list[str] = []
            for line in response.iter_lines():
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].strip())
                elif line == "":
                    if event_type and data_lines:
                        try:
                            payload = json.loads("\n".join(data_lines))
                        except json.JSONDecodeError:
                            payload = {"raw": "\n".join(data_lines)}
                        events.append(
                            {
                                "event_type": payload.get("event_type") or event_type,
                                "agent_id": payload.get("agent_id"),
                                "payload": payload.get("payload") or {},
                            }
                        )
                    event_type = None
                    data_lines = []
    except Exception as exc:  # noqa: BLE001
        events.append({"event_type": "read_error", "error": str(exc)})
    return events


def main() -> None:
    client = httpx.Client(base_url=BASE_URL, timeout=300)
    health = client.get("/api/health").json()
    results: dict[str, Any] = {"health": health, "tests": {}}

    # 测试 1：独立使用 Skill
    conv = create_conversation(client, ["alex"], "T1 Skill 独立使用")
    r1 = send_and_wait(
        client,
        conv,
        "请解释什么是边际成本，并用一个生活中的例子说明边际成本递增规律。"
        "如果需要，请使用你拥有的 Skill 来组织回答。",
    )
    results["tests"]["1_skill_only"] = {
        "input": "解释边际成本与递增规律",
        "tool_calls": tool_names(r1),
        "ok_tools": ok_tools(r1),
        "answer": answer(r1),
        "usage": r1["usage"],
        "seconds": r1["elapsed_seconds"],
        "pass": "use_skill" in ok_tools(r1) and len(answer(r1)) > 120,
    }

    # 测试 2：自主调用 Tool + 事件同步
    conv = create_conversation(client, ["alex"], "T2 原生 Tool Calling")
    r2 = send_and_wait(
        client, conv, "请计算 1876 × 2947，并说明计算过程中的关键步骤。"
    )
    events2 = read_events(client, conv, r2["task_id"])
    event_types = [item["event_type"] for item in events2]
    results["tests"]["2_tool_only"] = {
        "input": "1876 × 2947",
        "tool_calls": tool_names(r2),
        "ok_tools": ok_tools(r2),
        "tool_results": r2["tool_calls"],
        "answer": answer(r2),
        "usage": r2["usage"],
        "events": event_types,
        "seconds": r2["elapsed_seconds"],
        "pass": "calculator" in ok_tools(r2)
        and "5528572" in answer(r2).replace(",", "").replace("，", ""),
    }

    # 测试 2b：流式路径的原生 Tool Calling
    conv = create_conversation(client, ["alex"], "T2b 流式 Tool Calling")
    streamed = stream_single_agent(
        client, conv, "请计算 987654 × 321，并给出结果。"
    )
    results["tests"]["2b_streaming_tool"] = {
        "input": "987654 × 321（流式）",
        "content": streamed["content"],
        "done": streamed["done"],
        "seconds": streamed["elapsed_seconds"],
        "pass": bool(streamed["done"].get("tool_calls"))
        and "987654" in (streamed["content"] or "")
        and "317" in (streamed["content"] or "").replace(",", ""),
    }

    # 测试 3：Skill 与 Tool 协同
    conv = create_conversation(client, ["alex"], "T3 Skill + Tool 协同")
    r3 = send_and_wait(
        client,
        conv,
        "请先使用 concept_explanation 这个 Skill（concept 填“增量成本”）组织分析，"
        "再使用计算器：100 件产品总成本 5000 元，120 件总成本 5600 元，"
        "计算新增 20 件的平均增量成本，并解释其经济学含义。",
    )
    results["tests"]["3_skill_and_tool"] = {
        "input": "增量成本计算 + 概念解释",
        "tool_calls": tool_names(r3),
        "ok_tools": ok_tools(r3),
        "tool_results": r3["tool_calls"],
        "answer": answer(r3),
        "usage": r3["usage"],
        "seconds": r3["elapsed_seconds"],
        "pass": {"use_skill", "calculator"}.issubset(set(ok_tools(r3)))
        and ("30" in answer(r3)),
    }

    # 测试 4：多工具连续调用（中间结果）
    conv = create_conversation(client, ["ethan"], "T4 多步工具调用")
    r4 = send_and_wait(
        client,
        conv,
        "请分两次调用计算器：第一次计算 1250 × 36；第二次把上一次结果除以 15；"
        "最后判断结果是否大于 2500，并说明中间结果。",
    )
    results["tests"]["4_multi_tool"] = {
        "input": "1250×36 → ÷15 → 是否 >2500",
        "tool_calls": tool_names(r4),
        "ok_tools": ok_tools(r4),
        "tool_results": r4["tool_calls"],
        "answer": answer(r4),
        "usage": r4["usage"],
        "seconds": r4["elapsed_seconds"],
        "pass": tool_names(r4).count("calculator") >= 2
        and "45000" in answer(r4).replace(",", "")
        and "3000" in answer(r4).replace(",", ""),
    }

    # 测试 5：工具失败恢复
    conv = create_conversation(client, ["alex"], "T5 工具失败")
    r5 = send_and_wait(
        client,
        conv,
        "请使用 Python 沙箱执行这段代码：print(undefined_variable_42)，"
        "然后把真实执行结果告诉我。如果失败，请说明错误信息，不要编造成功。",
    )
    answer5 = answer(r5)
    results["tests"]["5_tool_failure"] = {
        "input": "Python 沙箱执行未定义变量",
        "tool_calls": tool_names(r5),
        "failed_tools": failed_tools(r5),
        "tool_results": r5["tool_calls"],
        "answer": answer5,
        "usage": r5["usage"],
        "seconds": r5["elapsed_seconds"],
        "pass": "python_sandbox" in failed_tools(r5)
        and bool(re.search(r"NameError|未定义|not defined", answer5))
        and not re.search(r"执行成功|输出\s*42", answer5),
    }

    # 测试 6：三个 Agent 的个体差异
    question6 = "企业是否应该无条件追求规模扩张？请给出你的判断和理由。"
    differentiation: dict[str, Any] = {}
    for agent_id in ("alex", "mia", "ethan"):
        conv = create_conversation(client, [agent_id], f"T6 差异化 {agent_id}")
        result = send_and_wait(client, conv, question6)
        text = answer(result)
        differentiation[agent_id] = {
            "tool_calls": tool_names(result),
            "answer": text,
            "style": style_hits(text),
            "usage": result["usage"],
        }
    contents = [differentiation[a]["answer"] for a in differentiation]
    results["tests"]["6_differentiation"] = {
        "input": question6,
        "agents": differentiation,
        "pass": len(set(contents)) == 3
        and all(len(text) > 80 for text in contents)
        and len({json.dumps(item["style"], sort_keys=True) for item in differentiation.values()}) >= 2,
    }

    # 测试 7：多 Agent 自主协作
    conv = create_conversation(client, ["alex", "mia", "ethan"], "T7 多 Agent 协作")
    r7 = send_and_wait(
        client,
        conv,
        "有观点认为：只要产量增加，单位成本就一定会下降。请三位从各自角度讨论，"
        "可以补充、质疑或请求帮助，并说明最终判断。",
        timeout_seconds=300,
    )
    senders = [m.get("sender_agent_id") for m in r7["messages"] if m.get("sender_agent_id")]
    actions = [
        (m.get("metadata") or {}).get("action")
        for m in r7["messages"]
        if (m.get("metadata") or {}).get("action")
    ]
    results["tests"]["7_multi_agent"] = {
        "input": "规模扩张与单位成本讨论",
        "task_status": r7["task"].get("status"),
        "stop_reason": r7["task"].get("stop_reason"),
        "message_count": len(r7["messages"]),
        "senders": senders,
        "actions": actions,
        "messages": [
            {"agent": m.get("sender_agent_id"), "content": m.get("content")}
            for m in r7["messages"]
        ],
        "tool_calls": tool_names(r7),
        "usage": r7["usage"],
        "seconds": r7["elapsed_seconds"],
        "pass": r7["task"].get("status") == "completed"
        and len(set(senders)) >= 2
        and len(r7["messages"]) >= 2,
    }

    # 测试 8：运行事件与真实执行一致
    api_tools = [
        (item.get("tool_name"), item.get("status")) for item in r2["tool_calls"]
    ]
    completed_events = [
        item
        for item in events2
        if item["event_type"] in {"tool_call_completed", "tool_call_failed", "tool_completed", "tool_failed"}
    ]
    results["tests"]["8_observability"] = {
        "api_tool_calls": api_tools,
        "event_types": event_types,
        "completed_events": completed_events,
        "pass": any(t in event_types for t in ("tool_call_started", "tool_started"))
        and any(
            t in event_types
            for t in ("tool_call_completed", "tool_call_failed", "tool_completed", "tool_failed")
        )
        and len(completed_events) >= len(api_tools),
    }

    OUT_PATH.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for name, payload in results["tests"].items():
        print(f"{name}: {'PASS' if payload.get('pass') else 'FAIL'}")
    print(f"saved: {OUT_PATH}")


if __name__ == "__main__":
    main()
