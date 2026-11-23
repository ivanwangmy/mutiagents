from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.model.base import ModelError
from app.model.registry import model_registry
from app.models import Message

logger = get_logger(__name__)

MEMORY_TYPES = {
    "episodic_memory",
    "semantic_memory",
    "preference_memory",
    "relationship_memory",
    "candidate_memory",
}
ACTIVE_CONFIDENCE = 0.7
DEDUPE_THRESHOLD = 0.85
MAX_CONTENT_CHARS = 300
MAX_EXTRACTED_PER_AGENT = 3

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[a-zA-Z0-9]+")


def memory_namespace(agent_id: str) -> tuple[str, str, str]:
    """每个 Agent 的私有记忆命名空间：agents/{id}/memories。"""
    return ("agents", agent_id, "memories")


def _tokens(text: str) -> set[str]:
    tokens = set(_WORD.findall(text.lower()))
    for run in _CJK_RUN.findall(text):
        if len(run) == 1:
            tokens.add(run)
        tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def _normalize(text: str) -> str:
    return re.sub(r"[\s，。！？、；：“”‘’（）()\[\]{}.,!?;:]+", "", text.lower())


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalize(left), _normalize(right)).ratio()


def _recency_score(created_at: datetime | None) -> float:
    if created_at is None:
        return 0.5
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_days = max((datetime.now(timezone.utc) - created_at).total_seconds() / 86400, 0)
    return 1.0 / (1.0 + age_days / 30.0)


class MemoryManager:
    """长期记忆读写：写入前识别价值与去重，读取时按相关度过滤。

    Agent 只能访问自己的 namespace；检索不到高相关记忆时不注入上下文。
    """

    def __init__(self, store: Any | None = None) -> None:
        self._store = store

    @property
    def store(self) -> Any | None:
        if self._store is not None:
            return self._store
        from app.memory.runtime import memory_runtime

        return memory_runtime.store

    async def _all_items(self, agent_id: str, limit: int = 200) -> list[Any]:
        store = self.store
        if store is None:
            return []
        try:
            return list(await store.asearch(memory_namespace(agent_id), limit=limit))
        except Exception as exc:  # noqa: BLE001
            logger.warning("记忆检索失败：agent=%s error=%s", agent_id, exc)
            return []

    async def add(
        self,
        agent_id: str,
        content: str,
        memory_type: str = "candidate_memory",
        *,
        confidence: float = 0.5,
        keywords: list[str] | None = None,
        source_conversation_id: str | None = None,
    ) -> dict[str, Any] | None:
        store = self.store
        if store is None or not content.strip():
            return None
        if memory_type not in MEMORY_TYPES:
            raise ValueError(f"不支持的记忆类型：{memory_type}")
        text = content.strip()[:MAX_CONTENT_CHARS]
        confidence = min(max(float(confidence), 0.0), 1.0)

        for item in await self._all_items(agent_id):
            existing = str((item.value or {}).get("content") or "")
            if existing and _similarity(existing, text) >= DEDUPE_THRESHOLD:
                logger.info("记忆去重命中：agent=%s content=%s", agent_id, text[:40])
                return None

        status = "active" if confidence >= ACTIVE_CONFIDENCE else "candidate"
        if memory_type == "candidate_memory":
            status = "candidate"
        now = datetime.now(timezone.utc).isoformat()
        value = {
            "content": text,
            "memory_type": memory_type,
            "confidence": round(confidence, 3),
            "status": status,
            "keywords": (keywords or sorted(_tokens(text))[:8])[:8],
            "source_conversation_id": source_conversation_id,
            "created_at": now,
            "updated_at": now,
        }
        key = str(uuid.uuid4())
        await store.aput(memory_namespace(agent_id), key, value)
        logger.info(
            "写入长期记忆：agent=%s type=%s status=%s content=%s",
            agent_id,
            memory_type,
            status,
            text[:40],
        )
        return {"key": key, "agent_id": agent_id, **value}

    async def retrieve(
        self, agent_id: str, query: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """按关键词重叠 + 置信度 + 时效性打分，只返回超过阈值的记忆。"""
        if not query.strip():
            return []
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in await self._all_items(agent_id):
            value = item.value or {}
            # 只有已验证的 active 记忆进入上下文；候选记忆需人工/复核后提升
            if value.get("status") != "active":
                continue
            content = str(value.get("content") or "")
            if not content:
                continue
            overlap = len(query_tokens & _tokens(content)) / max(len(query_tokens), 1)
            confidence = float(value.get("confidence", 0.5))
            created_raw = value.get("created_at")
            created_at = None
            if isinstance(created_raw, str):
                try:
                    created_at = datetime.fromisoformat(created_raw)
                except ValueError:
                    created_at = None
            score = (
                0.65 * overlap
                + 0.2 * confidence
                + 0.15 * _recency_score(created_at)
            )
            if score < settings.memory_retrieval_min_score:
                continue
            scored.append(
                (
                    score,
                    {
                        "key": item.key,
                        "content": content,
                        "memory_type": value.get("memory_type"),
                        "confidence": confidence,
                        "status": value.get("status"),
                        "score": round(score, 3),
                    },
                )
            )
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[: (limit or settings.memory_retrieval_limit)]]

    async def list(self, agent_id: str, limit: int = 100) -> list[dict[str, Any]]:
        items = await self._all_items(agent_id)
        rows = [
            {
                "key": item.key,
                **(item.value or {}),
            }
            for item in items
        ]
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return rows[:limit]

    async def update(
        self, agent_id: str, key: str, patch: dict[str, Any]
    ) -> dict[str, Any] | None:
        store = self.store
        if store is None:
            return None
        item = await store.aget(memory_namespace(agent_id), key)
        if item is None:
            return None
        value = dict(item.value or {})
        if "content" in patch and str(patch["content"]).strip():
            value["content"] = str(patch["content"]).strip()[:MAX_CONTENT_CHARS]
        if "memory_type" in patch:
            if patch["memory_type"] not in MEMORY_TYPES:
                raise ValueError(f"不支持的记忆类型：{patch['memory_type']}")
            value["memory_type"] = patch["memory_type"]
        if "confidence" in patch:
            value["confidence"] = min(max(float(patch["confidence"]), 0.0), 1.0)
        if "status" in patch:
            if patch["status"] not in {"active", "candidate", "invalid"}:
                raise ValueError(f"不支持的记忆状态：{patch['status']}")
            value["status"] = patch["status"]
        if "keywords" in patch and isinstance(patch["keywords"], list):
            value["keywords"] = [str(word) for word in patch["keywords"]][:8]
        value["updated_at"] = datetime.now(timezone.utc).isoformat()
        await store.aput(memory_namespace(agent_id), key, value)
        return {"key": key, "agent_id": agent_id, **value}

    async def promote(
        self, agent_id: str, key: str, *, confidence: float = 0.8
    ) -> dict[str, Any] | None:
        """把候选记忆提升为 active；只允许在用户确认或多次复现后调用。"""
        return await self.update(
            agent_id,
            key,
            {"status": "active", "confidence": max(float(confidence), ACTIVE_CONFIDENCE)},
        )

    async def delete(self, agent_id: str, key: str) -> bool:
        store = self.store
        if store is None:
            return False
        if await store.aget(memory_namespace(agent_id), key) is None:
            return False
        await store.adelete(memory_namespace(agent_id), key)
        return True

    # ---------- 提取 ----------
    async def extract_after_task(
        self,
        *,
        task_id: str,
        conversation_id: str,
        participants: list[str],
        question: str,
    ) -> None:
        """任务结束后提取有长期价值的候选记忆，绝不把全部聊天直接写入。"""
        if not settings.memory_extraction_enabled or self.store is None:
            return
        try:
            async with SessionLocal() as session:
                result = await session.execute(
                    select(Message)
                    .where(Message.task_id == task_id, Message.sender_type == "agent")
                    .order_by(Message.created_at.asc())
                )
                messages = list(result.scalars().all())
        except Exception as exc:  # noqa: BLE001
            logger.warning("记忆提取读取消息失败：task=%s error=%s", task_id, exc)
            return
        for agent_id in participants:
            own = [message for message in messages if message.sender_agent_id == agent_id]
            if not own:
                continue
            await self._extract_for_agent(
                agent_id=agent_id,
                question=question,
                own=own,
                conversation_id=conversation_id,
            )

    async def _extract_for_agent(
        self,
        *,
        agent_id: str,
        question: str,
        own: list[Message],
        conversation_id: str,
    ) -> None:
        from app.agents.registry import registry

        try:
            profile = registry.get(agent_id)
        except KeyError:
            return
        transcript = "\n".join(
            f"- {message.message_type}: {message.content[:200]}" for message in own[-3:]
        )[: settings.memory_extraction_transcript_chars]
        messages = [
            {
                "role": "system",
                "content": (
                    "你是长期记忆整理器。只提取对后续多轮互动有长期价值的信息，"
                    "忽略寒暄、一次性事实和重复内容。只输出 JSON："
                    '{"memories":[{"type":"preference_memory","content":"不超过80字",'
                    '"keywords":["关键词"],"confidence":0.9}]}。'
                    "type 只能是 episodic_memory / semantic_memory / preference_memory / "
                    "relationship_memory / candidate_memory。没有值得记住的内容就返回 "
                    '{"memories":[]}。'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户问题：{question[:400]}\n"
                    f"该 Agent 本轮发言：\n{transcript}\n"
                    "请判断其中是否有需要长期记住的用户偏好、稳定事实或互动经验。"
                ),
            },
        ]
        provider = model_registry.get(
            model=profile.runtime.model, temperature=0.2, max_tokens=300
        )
        try:
            response = await provider.complete(
                messages,
                response_format={"type": "json_object"},
                max_tokens=300,
                temperature=0.2,
            )
            data = json.loads(response.content.strip())
        except (ModelError, json.JSONDecodeError) as exc:
            logger.info("记忆提取跳过：agent=%s error=%s", agent_id, exc)
            return
        items = data.get("memories") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return
        for item in items[:MAX_EXTRACTED_PER_AGENT]:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            memory_type = str(item.get("type") or "candidate_memory")
            if len(content) < 4 or memory_type not in MEMORY_TYPES:
                continue
            keywords = item.get("keywords")
            if not isinstance(keywords, list):
                keywords = None
            try:
                await self.add(
                    agent_id,
                    content,
                    memory_type,
                    confidence=float(item.get("confidence", 0.6)),
                    keywords=[str(word) for word in keywords][:8] if keywords else None,
                    source_conversation_id=conversation_id,
                )
            except (TypeError, ValueError) as exc:
                logger.info("记忆写入跳过：agent=%s error=%s", agent_id, exc)


memory_manager = MemoryManager()
