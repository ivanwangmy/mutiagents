from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from app.agents.config import AgentProfile
from app.agents.graph import MAX_TOOL_ROUNDS, agent_graph_factory, ensure_content
from app.agents.registry import registry
from app.core.config import settings
from app.core.logging import get_logger
from app.events.broker import event_broker
from app.memory.experience import experience_manager
from app.memory.manager import memory_manager
from app.memory.runtime import memory_runtime
from app.model.base import ModelError, ModelResponse, ModelStreamChunk, ModelUsage, ToolCallRequest
from app.model.registry import model_registry
from app.models import Message
from app.skills.registry import skills_registry
from app.tools.base import ToolContext
from app.tools.executor import tool_executor
from app.tools.permissions import tool_permission_manager
from app.utils.tokens import estimate_tokens

logger = get_logger(__name__)


def _memory_block(memories: list[dict] | None) -> str:
    if not memories:
        return ""
    lines = "\n".join(
        f"- （{item.get('memory_type')}）{item.get('content')}" for item in memories[:5]
    )
    return (
        "\n\n## 你记得的相关长期记忆（仅你私有）\n"
        f"{lines}\n"
        "只在与当前问题相关时自然使用；无关或不确定时忽略，不要编造。"
    )


def _experience_block(experiences: list[dict] | None) -> str:
    if not experiences:
        return ""
    lines = "\n".join(
        f"- （{item.get('experience_type')}）{item.get('content')}" for item in experiences[:3]
    )
    return (
        "\n\n## 可参考的已验证经验（仅你私有）\n"
        f"{lines}\n"
        "仅在相关时借鉴，用于改善问题理解、表达方式、工具使用或协作策略；"
        "经验不改变你的核心 System Prompt、工具权限与安全规则，"
        "也不得据此修改其他 Agent 的配置。"
    )


def build_chat_messages(
    profile: AgentProfile,
    question: str,
    history: list[Message],
    max_context_tokens: int | None = None,
    memories: list[dict] | None = None,
    experiences: list[dict] | None = None,
) -> list[dict]:
    """组装模型消息：系统人格 + 候选 Skill + 记忆/经验 + 近期讨论 + 当前问题。"""
    skill_block = skills_registry.render_candidates(profile, question)
    system_prompt = (
        profile.system_prompt
        + skill_block
        + _memory_block(memories)
        + _experience_block(experiences)
    )
    budget = (max_context_tokens or profile.runtime.max_context_tokens) - estimate_tokens(
        system_prompt
    ) - estimate_tokens(question) - 64
    budget = max(budget, 200)

    selected: list[dict] = []
    used = 0
    for message in reversed(history):
        if not message.content.strip():
            continue
        if message.sender_type == "user":
            role = "user"
            content = message.content
        elif message.sender_agent_id == profile.id:
            role = "assistant"
            content = message.content
        else:
            role = "user"
            try:
                sender_name = registry.get(message.sender_agent_id or "").name
            except KeyError:
                sender_name = "其他参与者"
            content = f"【{sender_name}】{message.content}"
        cost = estimate_tokens(content) + 4
        if used + cost > budget:
            break
        selected.append({"role": role, "content": content})
        used += cost

    selected.reverse()
    return [
        {"role": "system", "content": system_prompt},
        *selected,
        {"role": "user", "content": question},
    ]


class AgentExecutor:
    """单 Agent 回合执行器：真实模型调用，统一超时与错误映射。"""

    def __init__(self) -> None:
        self.timeout_seconds = 90.0

    def _provider(self, profile: AgentProfile):
        return model_registry.get(
            model=profile.runtime.model,
            temperature=profile.runtime.temperature,
            max_tokens=min(profile.runtime.max_output_tokens, settings.max_output_tokens),
        )

    async def run(
        self,
        profile: AgentProfile,
        question: str,
        history: list[Message],
        *,
        task_id: str = "",
        conversation_id: str = "",
        max_tokens: int | None = None,
        resume: bool = False,
    ) -> tuple[ModelResponse, list[dict], dict]:
        memories = await memory_manager.retrieve(profile.id, question)
        experiences = await experience_manager.retrieve(profile.id, question)
        messages = build_chat_messages(
            profile, question, history, memories=memories, experiences=experiences
        )
        graph = agent_graph_factory.create(profile)
        thread_id = f"task:{task_id or 'adhoc'}:{profile.id}"
        config = {"recursion_limit": 40, "configurable": {"thread_id": thread_id}}
        payload = {
            "agent_id": profile.id,
            "task_id": task_id,
            "conversation_id": conversation_id,
            "question": question,
            "chat_messages": messages,
            "tool_call_counts": {},
            "tool_rounds": 0,
            "iterations": 0,
            "content": "",
            "tool_calls": [],
            "tool_log": [],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0},
        }
        logger.info(
            "Agent 回合开始：agent=%s model=%s context_tokens≈%s memories=%s",
            profile.id,
            profile.runtime.model,
            sum(estimate_tokens(m["content"]) for m in messages),
            [item["key"] for item in memories],
        )
        try:
            if resume and memory_runtime.checkpointer is not None:
                snapshot = await graph.aget_state(config)
                payload = None if snapshot.values else payload
            state = await asyncio.wait_for(
                graph.ainvoke(payload, config),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ModelError("模型调用超时", kind="timeout") from exc

        content = ensure_content(state)
        usage = state.get("usage") or {}
        response = ModelResponse(
            content=content,
            finish_reason=state.get("finish_reason") or "stop",
            tool_calls=[
                ToolCallRequest(
                    id=call["id"], name=call["name"], arguments=call.get("arguments", {})
                )
                for call in state.get("tool_calls") or []
            ],
            usage=ModelUsage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                reasoning_tokens=usage.get("reasoning_tokens", 0),
            ),
            model=state.get("model", profile.runtime.model),
        )
        meta = {
            "model_calls": state.get("iterations", 1),
            "tool_rounds": state.get("tool_rounds", 0),
            "tool_call_counts": state.get("tool_call_counts") or {},
            "tool_log": state.get("tool_log") or [],
            "memory_keys": [item["key"] for item in memories],
            "experience_ids": [item["id"] for item in experiences],
        }
        return response, messages, meta

    async def stream(
        self,
        profile: AgentProfile,
        question: str,
        history: list[Message],
        *,
        max_tokens: int | None = None,
        task_id: str = "",
        conversation_id: str = "",
    ) -> AsyncIterator[ModelStreamChunk]:
        """流式生成，并在流式响应中完成真实原生 Tool Calling 闭环。

        模型以 stream 方式返回 tool_calls 增量，后端累积解析后真实执行工具，
        把 role=tool 结果回填，再次流式生成；最多 MAX_TOOL_ROUNDS 轮。
        """
        memories = await memory_manager.retrieve(profile.id, question)
        experiences = await experience_manager.retrieve(profile.id, question)
        messages = build_chat_messages(
            profile, question, history, memories=memories, experiences=experiences
        )
        provider = self._provider(profile)
        tools = tool_permission_manager.tools_for(profile)
        schemas = [tool.to_openai_tool() for tool in tools.values()] if tools else None
        context = ToolContext(
            agent_id=profile.id,
            task_id=task_id,
            conversation_id=conversation_id,
            max_calls=tool_permission_manager.max_calls_for(profile),
        )
        usage = ModelUsage()
        model_calls = 0
        tool_rounds = 0
        tool_log: list[dict] = []
        finish_reason: str | None = None
        max_model_calls = int(getattr(settings, "max_model_calls", 8) or 8)
        output_limit = max_tokens or profile.runtime.max_output_tokens

        while True:
            model_calls += 1
            text_parts: list[str] = []
            pending_calls: list[ToolCallRequest] = []
            round_error: str | None = None
            async for chunk in provider.stream(
                messages,
                tools=schemas if tool_rounds < MAX_TOOL_ROUNDS else None,
                max_tokens=output_limit,
            ):
                if chunk.type == "text" and chunk.text:
                    text_parts.append(chunk.text)
                    yield chunk
                elif chunk.type == "tool_calls":
                    pending_calls = chunk.tool_calls
                elif chunk.type == "done":
                    finish_reason = chunk.finish_reason or finish_reason
                    if chunk.usage:
                        usage.prompt_tokens += chunk.usage.prompt_tokens
                        usage.completion_tokens += chunk.usage.completion_tokens
                        usage.reasoning_tokens += chunk.usage.reasoning_tokens
                elif chunk.type == "error":
                    yield chunk
                    return

            if not pending_calls:
                break
            if tool_rounds >= MAX_TOOL_ROUNDS or model_calls >= max_model_calls:
                messages.append(
                    {
                        "role": "system",
                        "content": "工具调用预算已用完。请基于已有信息直接回答，不要再调用工具。",
                    }
                )
                tool_rounds = MAX_TOOL_ROUNDS
                schemas = None
                continue

            tool_rounds += 1
            messages.append(
                {
                    "role": "assistant",
                    "content": "".join(text_parts) or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments, ensure_ascii=False),
                            },
                        }
                        for call in pending_calls
                    ],
                }
            )
            for call in pending_calls:
                tool = tools.get(call.name)
                if call.name == "use_skill":
                    await self._emit(
                        "skill_selected",
                        profile,
                        conversation_id,
                        task_id,
                        {
                            "call_id": call.id,
                            "skill": call.arguments.get("skill"),
                            "inputs": call.arguments.get("input"),
                        },
                    )
                result = await tool_executor.execute(
                    name=call.name,
                    arguments=call.arguments,
                    tool=tool,
                    context=context,
                    task_id=task_id or None,
                    conversation_id=conversation_id or None,
                    call_id=call.id,
                )
                if call.name == "use_skill" and result.ok:
                    payload = result.result if isinstance(result.result, dict) else {}
                    await self._emit(
                        "skill_loaded",
                        profile,
                        conversation_id,
                        task_id,
                        {
                            "call_id": call.id,
                            "skill": payload.get("skill"),
                            "steps": payload.get("steps") or [],
                            "required_inputs": payload.get("required_inputs") or [],
                        },
                    )
                    await self._emit(
                        "skill_completed",
                        profile,
                        conversation_id,
                        task_id,
                        {
                            "call_id": call.id,
                            "skill": payload.get("skill"),
                        },
                    )
                elif call.name == "use_skill":
                    await self._emit(
                        "skill_failed",
                        profile,
                        conversation_id,
                        task_id,
                        {"call_id": call.id, "skill": call.arguments.get("skill"), "error": result.error},
                    )
                tool_log.append(
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                        "ok": result.ok,
                        "error": result.error,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": json.dumps(result.to_payload(), ensure_ascii=False),
                    }
                )

        yield ModelStreamChunk(
            type="done",
            finish_reason=finish_reason or "stop",
            usage=usage,
            meta={
                "model_calls": model_calls,
                "tool_rounds": tool_rounds,
                "tool_call_counts": dict(context.call_counts),
                "tool_log": tool_log,
                "memory_keys": [item["key"] for item in memories],
                "experience_ids": [item["id"] for item in experiences],
            },
        )

    async def _emit(
        self,
        event_type: str,
        profile: AgentProfile,
        conversation_id: str,
        task_id: str,
        payload: dict,
    ) -> None:
        if not conversation_id:
            return
        try:
            await event_broker.emit(
                event_type,
                conversation_id=conversation_id,
                task_id=task_id or None,
                agent_id=profile.id,
                payload=payload,
            )
        except Exception as exc:  # noqa: BLE001 - 事件失败不影响生成
            logger.warning("Agent 事件写入失败：type=%s error=%s", event_type, exc)
