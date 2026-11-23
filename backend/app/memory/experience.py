from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.memory.manager import _recency_score, _similarity, _tokens
from app.model.base import ModelError
from app.model.registry import model_registry
from app.models import (
    AgentExperience,
    Message,
    TaskEvent,
    TaskExecution,
    ToolCall,
    UserFeedback,
)

logger = get_logger(__name__)

EXPERIENCE_TYPES = {
    "task_result",
    "tool_usage",
    "user_feedback",
    "collaboration",
    "knowledge_correction",
}
VALIDATION_STATUSES = {"candidate", "validated", "rejected"}
MAX_CONTENT_CHARS = 300
DUPLICATE_THRESHOLD = 0.85

# 明确要求修改系统提示、权限、安全规则或他人配置的内容一律拒绝
RISK_PATTERNS = (
    "系统提示词",
    "system prompt",
    "工具权限",
    "安全规则",
    "其他agent",
    "其他 agent",
    "别的agent",
    "别的 agent",
    "忽略以上",
    "忽略之前",
    "绕过",
    "越权",
    "泄露密钥",
    "api key",
)
UNCERTAIN_PATTERNS = ("我猜", "猜测", "据说", "道听途说", "也许可能")
REUSABLE_HINTS = (
    "应",
    "先",
    "适合",
    "推荐",
    "避免",
    "需要",
    "可以",
    "优先",
    "步骤",
    "方法",
    "策略",
    "保持",
    "下次",
    "后续",
    "直接",
    "不要",
    "无需",
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:MAX_CONTENT_CHARS]


def evaluate_experience(
    content: str, experience_type: str, confidence: float
) -> tuple[str, str]:
    """经验验证：真实性、可复用、错误、风险。

    返回 (validation_status, validation_note)。只有 validated 才会进入长期检索。
    """
    text = _clean(content)
    lowered = text.lower()
    if experience_type not in EXPERIENCE_TYPES:
        return "rejected", "未知的经验类型"
    if len(text) < 8:
        return "rejected", "内容过短，缺少可复用信息"
    for pattern in RISK_PATTERNS:
        if pattern in lowered:
            return "rejected", f"包含越权或高风险表述：{pattern}"
    for pattern in UNCERTAIN_PATTERNS:
        if pattern in text:
            return "rejected", f"包含猜测性表述：{pattern}"
    if experience_type == "tool_usage" and "工具" not in text:
        return "rejected", "工具经验缺少工具名或执行结果"
    if experience_type in {"task_result", "collaboration"} and not any(
        hint in text for hint in REUSABLE_HINTS
    ):
        return "rejected", "缺少可复用的做法或判断"
    if experience_type == "knowledge_correction" and len(text) < 12:
        return "rejected", "知识修正内容不足，无法指导后续行为"
    if confidence < 0.55:
        return "candidate", "置信度偏低，等待人工复核"
    return "validated", "规则校验通过：来源真实、可复用、无风险"


class ExperienceManager:
    """Agent 经验：候选提取 → 验证 → 相关检索 → 有限注入。

    经验只以只读方式进入提示词，不能修改 System Prompt、工具权限、安全规则
    或其他 Agent 的配置；未通过验证的经验永不参与检索。
    """

    # ---------- 序列化 ----------
    @staticmethod
    def serialize(row: AgentExperience) -> dict[str, Any]:
        return {
            "id": row.id,
            "agent_id": row.agent_id,
            "experience_type": row.experience_type,
            "content": row.content,
            "source_conversation_id": row.source_conversation_id,
            "source_task_id": row.source_task_id,
            "confidence": round(float(row.confidence), 3),
            "validation_status": row.validation_status,
            "validation_note": row.validation_note,
            "keywords": list(row.keywords or []),
            "use_count": row.use_count,
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    # ---------- 写入 ----------
    async def _find_duplicate(
        self, agent_id: str, content: str
    ) -> AgentExperience | None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(AgentExperience)
                .where(AgentExperience.agent_id == agent_id)
                .order_by(AgentExperience.created_at.desc())
                .limit(200)
            )
            for row in result.scalars().all():
                if _similarity(row.content, content) >= DUPLICATE_THRESHOLD:
                    return row
        return None

    async def create_candidate(
        self,
        *,
        agent_id: str,
        experience_type: str,
        content: str,
        confidence: float = 0.6,
        keywords: list[str] | None = None,
        source_conversation_id: str | None = None,
        source_task_id: str | None = None,
    ) -> dict[str, Any] | None:
        text = _clean(content)
        if not text or experience_type not in EXPERIENCE_TYPES:
            return None
        duplicate = await self._find_duplicate(agent_id, text)
        if duplicate is not None:
            logger.info(
                "经验去重命中：agent=%s duplicate=%s content=%s",
                agent_id,
                duplicate.id,
                text[:40],
            )
            return None
        confidence = min(max(float(confidence), 0.0), 1.0)
        status, note = evaluate_experience(text, experience_type, confidence)
        row = AgentExperience(
            agent_id=agent_id,
            experience_type=experience_type,
            content=text,
            confidence=confidence,
            validation_status=status,
            validation_note=note,
            keywords=(keywords or sorted(_tokens(text))[:8])[:8],
            source_conversation_id=source_conversation_id,
            source_task_id=source_task_id,
        )
        async with SessionLocal() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        logger.info(
            "写入经验：agent=%s type=%s status=%s content=%s",
            agent_id,
            experience_type,
            status,
            text[:40],
        )
        return self.serialize(row)

    # ---------- 读取 ----------
    async def list(
        self, agent_id: str, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        async with SessionLocal() as session:
            stmt = select(AgentExperience).where(AgentExperience.agent_id == agent_id)
            if status in VALIDATION_STATUSES:
                stmt = stmt.where(AgentExperience.validation_status == status)
            result = await session.execute(
                stmt.order_by(AgentExperience.updated_at.desc()).limit(limit)
            )
            return [self.serialize(row) for row in result.scalars().all()]

    async def counts(self, agent_id: str) -> dict[str, int]:
        rows = await self.list(agent_id, limit=500)
        summary = {status: 0 for status in VALIDATION_STATUSES}
        for row in rows:
            summary[row["validation_status"]] = summary.get(row["validation_status"], 0) + 1
        summary["total"] = len(rows)
        return summary

    async def retrieve(
        self,
        agent_id: str,
        query: str,
        limit: int | None = None,
        *,
        mark_used: bool = True,
    ) -> list[dict[str, Any]]:
        """按相关度检索已验证经验；无关经验不会注入。"""
        if not query.strip():
            return []
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        async with SessionLocal() as session:
            result = await session.execute(
                select(AgentExperience)
                .where(
                    AgentExperience.agent_id == agent_id,
                    AgentExperience.validation_status == "validated",
                )
                .order_by(AgentExperience.updated_at.desc())
                .limit(200)
            )
            rows = list(result.scalars().all())
            scored: list[tuple[float, AgentExperience]] = []
            for row in rows:
                content_tokens = _tokens(row.content)
                shared = query_tokens & content_tokens
                # 至少两个词面重合才视为相关，避免个别通用词把无关经验带出
                if len(shared) < 2:
                    continue
                overlap = len(shared) / max(len(query_tokens), 1)
                score = (
                    0.6 * overlap
                    + 0.25 * float(row.confidence)
                    + 0.15 * _recency_score(row.updated_at)
                )
                if score < settings.experience_retrieval_min_score:
                    continue
                scored.append((score, row))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            selected = scored[: (limit or settings.experience_retrieval_limit)]
            now = datetime.now(timezone.utc)
            output: list[dict[str, Any]] = []
            for score, row in selected:
                if mark_used:
                    row.use_count = (row.use_count or 0) + 1
                    row.last_used_at = now
                output.append(
                    {
                        "id": row.id,
                        "agent_id": row.agent_id,
                        "experience_type": row.experience_type,
                        "content": row.content,
                        "confidence": round(float(row.confidence), 3),
                        "score": round(score, 3),
                    }
                )
            if mark_used and selected:
                await session.commit()
        return output

    async def update_review(
        self,
        agent_id: str,
        experience_id: str,
        *,
        validation_status: str,
        note: str | None = None,
    ) -> dict[str, Any] | None:
        """人工复核入口：只允许修改验证状态，不触碰 Agent 配置。"""
        if validation_status not in VALIDATION_STATUSES:
            raise ValueError(f"不支持的验证状态：{validation_status}")
        async with SessionLocal() as session:
            row = await session.get(AgentExperience, experience_id)
            if row is None or row.agent_id != agent_id:
                return None
            row.validation_status = validation_status
            row.validation_note = _clean(note) if note else f"人工复核为 {validation_status}"
            await session.commit()
            await session.refresh(row)
            return self.serialize(row)

    async def delete(self, agent_id: str, experience_id: str) -> bool:
        async with SessionLocal() as session:
            row = await session.get(AgentExperience, experience_id)
            if row is None or row.agent_id != agent_id:
                return False
            await session.delete(row)
            await session.commit()
            return True

    # ---------- 反馈提取 ----------
    async def create_from_feedback(self, feedback: UserFeedback) -> dict[str, Any] | None:
        """用户明确反馈是最高优先级经验来源，但仍需通过验证。"""
        if not feedback.agent_id:
            return None
        message = None
        if feedback.message_id:
            async with SessionLocal() as session:
                message = await session.get(Message, feedback.message_id)
        excerpt = _clean(message.content if message else "")[:60]
        comment = _clean(feedback.comment).rstrip("。！？!?；;，,")
        if feedback.rating < 0:
            experience_type = "knowledge_correction"
            target = f"关于「{excerpt}」的回答" if excerpt else "之前的回答"
            if comment:
                content = (
                    f"用户指出{target}有问题：{comment}。后续遇到相似问题应先避免该错误。"
                )
            else:
                content = (
                    "用户对本次回答明确表示不满意，后续回答应更谨慎核对结论与用户真实需求。"
                )
            confidence = 0.85 if comment else 0.6
        elif feedback.rating > 0:
            experience_type = "user_feedback"
            target = f"围绕「{excerpt}」的回答" if excerpt else "本次回答"
            if comment:
                content = f"用户肯定了{target}的处理方式：{comment}。后续相似场景可以保持。"
            else:
                content = f"用户肯定了{target}，后续相似场景可以保持该讲解方式。"
            confidence = 0.8 if comment else 0.6
        else:
            return None
        return await self.create_candidate(
            agent_id=feedback.agent_id,
            experience_type=experience_type,
            content=content,
            confidence=confidence,
            source_conversation_id=feedback.conversation_id,
        )

    # ---------- 任务结束提取 ----------
    async def extract_after_task(
        self,
        *,
        task_id: str,
        conversation_id: str,
        participants: list[str],
        question: str,
    ) -> None:
        """任务结束后从真实执行记录提取候选经验，不把每次发言都写成经验。"""
        if not settings.experience_extraction_enabled:
            return
        try:
            async with SessionLocal() as session:
                task = await session.get(TaskExecution, task_id)
                message_rows = list(
                    (
                        await session.execute(
                            select(Message)
                            .where(
                                Message.task_id == task_id,
                                Message.sender_type == "agent",
                            )
                            .order_by(Message.created_at.asc())
                        )
                    )
                    .scalars()
                    .all()
                )
                tool_rows = list(
                    (
                        await session.execute(
                            select(ToolCall)
                            .where(ToolCall.task_id == task_id)
                            .order_by(ToolCall.created_at.asc())
                        )
                    )
                    .scalars()
                    .all()
                )
                event_rows = list(
                    (
                        await session.execute(
                            select(TaskEvent)
                            .where(
                                TaskEvent.task_id == task_id,
                                TaskEvent.event_type == "agent.decision",
                            )
                            .order_by(TaskEvent.id.asc())
                        )
                    )
                    .scalars()
                    .all()
                )
        except Exception as exc:  # noqa: BLE001 - 提取失败不影响任务结果
            logger.warning("经验提取读取任务失败：task=%s error=%s", task_id, exc)
            return

        stop_reason = task.stop_reason if task else None
        for agent_id in participants:
            own_messages = [
                row for row in message_rows if row.sender_agent_id == agent_id
            ]
            if not own_messages:
                continue
            own_tools = [row for row in tool_rows if row.agent_id == agent_id]
            own_events = [row for row in event_rows if row.agent_id == agent_id]

            await self._extract_tool_experience(
                agent_id, own_tools, conversation_id, task_id
            )
            await self._extract_collaboration_experience(
                agent_id, own_events, conversation_id, task_id
            )
            await self._extract_result_experience(
                agent_id,
                question=question,
                messages=own_messages,
                tools=own_tools,
                stop_reason=stop_reason,
                conversation_id=conversation_id,
                task_id=task_id,
            )

    async def _extract_tool_experience(
        self,
        agent_id: str,
        tools: list[ToolCall],
        conversation_id: str,
        task_id: str,
    ) -> None:
        failed = [row for row in tools if row.status != "success"]
        for row in failed[:1]:
            error = _clean(row.error or "未知错误")[:120]
            await self.create_candidate(
                agent_id=agent_id,
                experience_type="tool_usage",
                content=(
                    f"调用工具 {row.tool_name} 会失败：{error}。"
                    "后续使用前应先校验参数，失败时如实说明并换用可用方式。"
                ),
                confidence=0.85,
                source_conversation_id=conversation_id,
                source_task_id=task_id,
            )
        succeeded = [row for row in tools if row.status == "success"]
        if len({row.tool_name for row in succeeded}) >= 2:
            names = "、".join(sorted({row.tool_name for row in succeeded}))
            await self.create_candidate(
                agent_id=agent_id,
                experience_type="tool_usage",
                content=(
                    f"在需要真实数据时，优先调用 {names} 获取结果，"
                    "可以避免凭印象估算。"
                ),
                confidence=0.7,
                source_conversation_id=conversation_id,
                source_task_id=task_id,
            )

    async def _extract_collaboration_experience(
        self,
        agent_id: str,
        events: list[TaskEvent],
        conversation_id: str,
        task_id: str,
    ) -> None:
        from app.agents.registry import registry

        challenge = None
        request_help = None
        for row in events:
            action = str((row.payload or {}).get("action") or "")
            if action == "CHALLENGE" and challenge is None:
                challenge = row
            elif action == "REQUEST_HELP" and request_help is None:
                request_help = row
        if challenge is not None:
            receiver = str((challenge.payload or {}).get("receiver") or "")
            try:
                peer = registry.get(receiver).name
            except KeyError:
                peer = receiver or "另一位参与者"
            await self.create_candidate(
                agent_id=agent_id,
                experience_type="collaboration",
                content=(
                    f"与 {peer} 观点不一致时，应先指出具体分歧并给出理由，"
                    "再请对方补充证据，这样讨论更容易收敛。"
                ),
                confidence=0.75,
                source_conversation_id=conversation_id,
                source_task_id=task_id,
            )
        if request_help is not None:
            receiver = str((request_help.payload or {}).get("receiver") or "")
            try:
                peer = registry.get(receiver).name
            except KeyError:
                peer = receiver or "另一位参与者"
            await self.create_candidate(
                agent_id=agent_id,
                experience_type="collaboration",
                content=(
                    f"遇到不确定的内容时，可以请 {peer} 补充具体信息，"
                    "比自行推测更可靠。"
                ),
                confidence=0.7,
                source_conversation_id=conversation_id,
                source_task_id=task_id,
            )

    async def _extract_result_experience(
        self,
        agent_id: str,
        *,
        question: str,
        messages: list[Message],
        tools: list[ToolCall],
        stop_reason: str | None,
        conversation_id: str,
        task_id: str,
    ) -> None:
        """用真实交互让 Agent 总结可复用方法；模型失败时静默跳过。"""
        if not settings.model_configured:
            return
        from app.agents.registry import registry

        try:
            profile = registry.get(agent_id)
        except KeyError:
            return
        transcript = "\n".join(
            f"- {row.message_type}: {_clean(row.content)[:160]}"
            for row in messages[-4:]
        )[: settings.experience_extraction_transcript_chars]
        tool_summary = "\n".join(
            f"- {row.tool_name}: {'成功' if row.status == 'success' else '失败'}"
            for row in tools[:4]
        ) or "- 无工具调用"
        prompt = (
            "你是教学 Agent 的经验整理器。阅读该 Agent 在本次任务中的真实发言与工具结果，"
            "只提取 0-2 条对后续相似任务有复用价值、且有本次交互证据支持的经验。\n"
            "禁止：把寒暄、客套、一次性事实或无证据的推断写成经验；"
            "禁止建议修改系统提示词、工具权限、安全规则或其他 Agent 配置。\n"
            "只输出 JSON："
            '{"experiences":[{"type":"task_result","content":"不超过100字，写成可复用的做法或判断",'
            '"keywords":["关键词"],"confidence":0.8}]}。'
            "type 只能是 task_result 或 knowledge_correction。没有就返回 "
            '{"experiences":[]}。'
        )
        user = (
            f"用户问题：{_clean(question)[:300]}\n"
            f"该 Agent 本轮真实发言：\n{transcript}\n"
            f"工具执行结果：\n{tool_summary}\n"
            f"任务结束原因：{stop_reason or 'finish'}"
        )
        provider = model_registry.get(
            model=profile.runtime.model, temperature=0.2, max_tokens=400
        )
        try:
            response = await provider.complete(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                max_tokens=400,
                temperature=0.2,
            )
            data = json.loads(response.content.strip())
        except (ModelError, json.JSONDecodeError) as exc:
            logger.info("经验总结跳过：agent=%s error=%s", agent_id, exc)
            return
        items = data.get("experiences") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return
        for item in items[: settings.experience_extraction_max_per_agent]:
            if not isinstance(item, dict):
                continue
            experience_type = str(item.get("type") or "task_result")
            if experience_type not in {"task_result", "knowledge_correction"}:
                continue
            content = str(item.get("content") or "").strip()
            if len(content) < 8:
                continue
            keywords = item.get("keywords")
            await self.create_candidate(
                agent_id=agent_id,
                experience_type=experience_type,
                content=content,
                confidence=float(item.get("confidence", 0.7) or 0.7),
                keywords=[str(word) for word in keywords][:8]
                if isinstance(keywords, list)
                else None,
                source_conversation_id=conversation_id,
                source_task_id=task_id,
            )


experience_manager = ExperienceManager()
