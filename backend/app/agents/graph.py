from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.config import AgentProfile
from app.agents.state import AgentState
from app.core.config import settings
from app.core.logging import get_logger
from app.events import event_broker
from app.memory.runtime import memory_runtime
from app.model.base import ModelError
from app.model.registry import model_registry
from app.tools.base import ToolContext
from app.tools.executor import tool_executor
from app.tools.permissions import tool_permission_manager

logger = get_logger(__name__)

MAX_TOOL_ROUNDS = 4
MAX_TOOL_MESSAGE_CHARS = 2000


class AgentGraphFactory:
    """把单个 Agent 的一次执行构建为 LangGraph 状态图。

    第 4 轮：单次生成。
    第 5 轮：generate ↔ tools 真实 Tool Calling 循环，最多 MAX_TOOL_ROUNDS 轮。
    """

    def __init__(self) -> None:
        self._cache: dict[str, CompiledStateGraph] = {}

    def create(self, profile: AgentProfile) -> CompiledStateGraph:
        cached = self._cache.get(profile.id)
        if cached is not None:
            return cached

        max_tokens = min(profile.runtime.max_output_tokens, settings.max_output_tokens)
        tools = tool_permission_manager.tools_for(profile)
        tool_schemas = [tool.to_openai_tool() for tool in tools.values()]
        max_calls = tool_permission_manager.max_calls_for(profile)

        async def generate(state: AgentState) -> dict[str, Any]:
            provider = model_registry.get(
                model=profile.runtime.model,
                temperature=profile.runtime.temperature,
                max_tokens=max_tokens,
            )
            usage_before = state.get("usage") or {}
            spent = usage_before.get("prompt_tokens", 0) + usage_before.get(
                "completion_tokens", 0
            )
            allow_tools = (
                bool(tool_schemas)
                and state.get("tool_rounds", 0) < MAX_TOOL_ROUNDS
                and spent < settings.task_token_budget
            )
            response = await provider.complete(
                state["chat_messages"],
                tools=tool_schemas if allow_tools else None,
                tool_choice="auto" if allow_tools else None,
                max_tokens=max_tokens,
                temperature=profile.runtime.temperature,
            )
            calls = [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in response.tool_calls
            ]
            messages = list(state["chat_messages"])
            if calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {
                                "id": call["id"],
                                "type": "function",
                                "function": {
                                    "name": call["name"],
                                    "arguments": json.dumps(
                                        call["arguments"], ensure_ascii=False
                                    ),
                                },
                            }
                            for call in calls
                        ],
                    }
                )
            return {
                "content": response.content,
                "finish_reason": response.finish_reason,
                "tool_calls": calls,
                "usage": {
                    "prompt_tokens": usage_before.get("prompt_tokens", 0)
                    + response.usage.prompt_tokens,
                    "completion_tokens": usage_before.get("completion_tokens", 0)
                    + response.usage.completion_tokens,
                    "reasoning_tokens": usage_before.get("reasoning_tokens", 0)
                    + response.usage.reasoning_tokens,
                },
                "model": response.model,
                "iterations": state.get("iterations", 0) + 1,
                "chat_messages": messages,
            }

        async def run_tools(state: AgentState) -> dict[str, Any]:
            context = ToolContext(
                agent_id=profile.id,
                task_id=state.get("task_id", ""),
                conversation_id=state.get("conversation_id", ""),
                call_counts=dict(state.get("tool_call_counts") or {}),
                max_calls=max_calls,
            )
            messages = list(state["chat_messages"])
            logs = list(state.get("tool_log") or [])
            for call in state.get("tool_calls") or []:
                conversation_id = state.get("conversation_id") or ""
                task_id = state.get("task_id") or None
                if conversation_id:
                    await event_broker.emit(
                        "agent_tool_call",
                        conversation_id=conversation_id,
                        task_id=task_id,
                        agent_id=profile.id,
                        payload={
                            "call_id": call["id"],
                            "tool": call["name"],
                            "arguments": call.get("arguments") or {},
                        },
                    )
                    await event_broker.emit(
                        "tool_started",
                        conversation_id=conversation_id,
                        task_id=task_id,
                        agent_id=profile.id,
                        payload={
                            "call_id": call["id"],
                            "tool": call["name"],
                            "arguments": call.get("arguments") or {},
                        },
                    )
                if call["name"] == "use_skill" and conversation_id:
                    await event_broker.emit(
                        "skill_selected",
                        conversation_id=conversation_id,
                        task_id=task_id,
                        agent_id=profile.id,
                        payload={
                            "call_id": call["id"],
                            "skill": (call.get("arguments") or {}).get("skill"),
                            "inputs": (call.get("arguments") or {}).get("input"),
                        },
                    )
                result = await tool_executor.execute(
                    name=call["name"],
                    arguments=call.get("arguments") or {},
                    tool=tools.get(call["name"]),
                    context=context,
                    task_id=state.get("task_id") or None,
                    conversation_id=state.get("conversation_id") or None,
                    call_id=call["id"],
                )
                if call["name"] == "use_skill" and conversation_id:
                    skill_payload = result.result if isinstance(result.result, dict) else {}
                    await event_broker.emit(
                        "skill_loaded" if result.ok else "skill_failed",
                        conversation_id=conversation_id,
                        task_id=task_id,
                        agent_id=profile.id,
                        payload={
                            "call_id": call["id"],
                            "skill": skill_payload.get("skill")
                            or (call.get("arguments") or {}).get("skill"),
                            "steps": skill_payload.get("steps") or [],
                            "required_inputs": skill_payload.get("required_inputs") or [],
                            "error": result.error,
                        },
                    )
                    if result.ok:
                        await event_broker.emit(
                            "skill_completed",
                            conversation_id=conversation_id,
                            task_id=task_id,
                            agent_id=profile.id,
                            payload={
                                "call_id": call["id"],
                                "skill": skill_payload.get("skill"),
                            },
                        )
                if conversation_id:
                    await event_broker.emit(
                        "tool_completed" if result.ok else "tool_failed",
                        conversation_id=conversation_id,
                        task_id=task_id,
                        agent_id=profile.id,
                        payload={
                            "call_id": call["id"],
                            "tool": call["name"],
                            "ok": result.ok,
                            "duration_ms": result.duration_ms,
                            "error": result.error,
                            "result": json.dumps(
                                result.to_payload(), ensure_ascii=False
                            )[:500],
                        },
                    )
                logs.append(
                    {
                        "tool": call["name"],
                        "ok": result.ok,
                        "error": result.error,
                        "duration_ms": result.duration_ms,
                    }
                )
                content = json.dumps(result.to_payload(), ensure_ascii=False)
                if len(content) > MAX_TOOL_MESSAGE_CHARS:
                    content = content[:MAX_TOOL_MESSAGE_CHARS] + "…(结果已截断)"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": content,
                    }
                )
            return {
                "chat_messages": messages,
                "tool_calls": [],
                "tool_call_counts": context.call_counts,
                "tool_rounds": state.get("tool_rounds", 0) + 1,
                "tool_log": logs,
            }

        def route_after_generate(state: AgentState) -> str:
            if state.get("tool_calls") and state.get("tool_rounds", 0) < MAX_TOOL_ROUNDS:
                return "tools"
            return "end"

        graph = StateGraph(AgentState)
        graph.add_node("generate", generate)
        graph.add_node("tools", run_tools)
        graph.add_edge(START, "generate")
        graph.add_conditional_edges(
            "generate", route_after_generate, {"tools": "tools", "end": END}
        )
        graph.add_edge("tools", "generate")
        compiled = graph.compile(checkpointer=memory_runtime.checkpointer)
        self._cache[profile.id] = compiled
        return compiled


agent_graph_factory = AgentGraphFactory()


def ensure_content(state: AgentState) -> str:
    content = (state.get("content") or "").strip()
    if not content:
        if state.get("finish_reason") == "length":
            raise ModelError("模型输出达到长度上限但内容为空，请重试", kind="empty_response")
        raise ModelError("模型返回空内容", kind="empty_response")
    return content
