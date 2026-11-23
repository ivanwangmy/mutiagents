from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from typing import Any

from jsonschema import ValidationError, validate

from app.agents.config import AgentProfile, SkillSpec
from app.agents.registry import registry
from app.core.logging import get_logger
from app.skills.base import SkillExecution, SkillHandler
from app.skills.catalog import SKILL_METADATA

logger = get_logger(__name__)

_WORD = re.compile(r"[a-zA-Z0-9]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")


class SkillNotFoundError(KeyError):
    pass


class SkillPermissionError(PermissionError):
    pass


class SkillInputError(ValueError):
    """输入不满足 Skill 契约；属于可重试错误，不消耗调用配额。"""


class SkillDisabledError(RuntimeError):
    pass


def _tokens(text: str) -> set[str]:
    tokens = {item.lower() for item in _WORD.findall(text)}
    for run in _CJK_RUN.findall(text):
        if len(run) == 1:
            tokens.add(run)
        tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


@dataclass(slots=True)
class SkillMatch:
    skill: SkillSpec
    score: float
    matched_terms: list[str]

    def to_payload(self) -> dict[str, Any]:
        return {
            "skill": self.skill.name,
            "score": round(self.score, 3),
            "description": self.skill.description,
            "when_to_use": self.skill.when_to_use,
            "category": self.skill.category,
            "required_inputs": self.skill.required_inputs,
            "matched_terms": self.matched_terms,
        }


def _resolve_handler(logic: str) -> SkillHandler:
    module_name, separator, attr = logic.partition(":")
    if not separator or not module_name or not attr:
        raise RuntimeError(f"Skill execution_logic 格式必须是 module:function，收到：{logic}")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise RuntimeError(f"Skill 执行模块无法导入：{module_name}") from exc
    handler = getattr(module, attr, None)
    if not callable(handler):
        raise RuntimeError(f"Skill 执行函数不存在：{logic}")
    return handler


_INTENTS: list[tuple[tuple[str, ...], set[str]]] = [
    (
        ("什么是", "是什么", "含义", "定义", "解释", "辨析", "区别", "概念", "怎么理解"),
        {"concept", "adaptation", "scaffolding"},
    ),
    (
        ("为什么", "论证", "逻辑", "推理", "成立", "因果"),
        {"logic", "theory", "assumption"},
    ),
    (
        ("质疑", "反例", "反驳", "假设", "替代", "不同看法"),
        {"critique", "hypothesis", "exploration"},
    ),
    (
        ("总结", "归纳", "整理", "概括", "串起来"),
        {"summarization", "organization", "perspective"},
    ),
    (
        ("怎么教", "教学", "练习", "例子", "通俗", "拆解"),
        {"pedagogy", "decomposition", "analogy"},
    ),
]


def _intent_categories(query: str) -> set[str]:
    categories: set[str] = set()
    for keywords, names in _INTENTS:
        if any(keyword in query for keyword in keywords):
            categories.update(names)
    return categories


def _with_catalog(skill: SkillSpec) -> SkillSpec:
    """合并集中式元数据；已显式声明的字段优先。"""
    meta = SKILL_METADATA.get(skill.name)
    if meta is None:
        raise RuntimeError(f"Skill 未在 catalog 登记：{skill.name}")
    patch: dict[str, Any] = {}
    if skill.category == "method" and meta.get("category"):
        patch["category"] = meta["category"]
    if not skill.limitations and meta.get("limitations"):
        patch["limitations"] = list(meta["limitations"])
    if skill.version == "1.0.0" and meta.get("version"):
        patch["version"] = str(meta["version"])
    return skill.model_copy(update=patch) if patch else skill


class SkillRegistry:
    """统一 Skill 注册、发现、匹配与执行。

    - 加载时校验 id 唯一、授权关系与执行函数；
    - 支持启用/停用；
    - 按任务描述做相关度匹配，供 Agent 自主选择；
    - 执行前校验权限与 input_schema，失败信息包含缺失字段。
    """

    def __init__(self) -> None:
        self._skills: dict[str, tuple[SkillSpec, SkillHandler]] = {}
        self._disabled: set[str] = set()
        self._call_counts: dict[str, int] = {}
        self._failure_counts: dict[str, int] = {}

    def load(self, profiles: list[AgentProfile] | None = None) -> None:
        self._skills.clear()
        for profile in profiles or registry.all():
            for raw_skill in profile.skills:
                if profile.id not in raw_skill.applicable_agents:
                    raise RuntimeError(
                        f"{profile.id} 加载了未授权 Skill：{raw_skill.name}"
                    )
                if not raw_skill.enabled:
                    self._disabled.add(raw_skill.name)
                    continue
                skill = _with_catalog(raw_skill)
                if skill.name in self._skills:
                    raise RuntimeError(f"Skill 名称重复：{skill.name}")
                self._skills[skill.name] = (skill, _resolve_handler(skill.execution_logic))
        # 把目录元数据回写到 AgentProfile，确保 Prompt 与接口展示一致
        for profile in profiles or registry.all():
            profile.skills = [self._skills[s.name][0] if s.name in self._skills else s for s in profile.skills]
        logger.info("SkillRegistry 加载完成：%s 个能力模块", len(self._skills))

    def ensure_loaded(self) -> None:
        if not self._skills:
            self.load()

    def reload(self) -> None:
        """重新读取 persona 并重建注册表（用于配置热更新）。"""
        registry.load()
        self.load()

    def get(self, name: str) -> tuple[SkillSpec, SkillHandler]:
        self.ensure_loaded()
        item = self._skills.get(name)
        if item is None:
            raise SkillNotFoundError(name)
        return item

    def set_enabled(self, name: str, enabled: bool) -> None:
        self.ensure_loaded()
        self.get(name)
        if enabled:
            self._disabled.discard(name)
        else:
            self._disabled.add(name)

    def is_enabled(self, name: str) -> bool:
        return name not in self._disabled

    def for_agent(self, agent_id: str) -> list[SkillSpec]:
        self.ensure_loaded()
        return [
            skill
            for skill, _handler in self._skills.values()
            if agent_id in skill.applicable_agents and self.is_enabled(skill.name)
        ]

    def match(
        self, profile: AgentProfile, query: str, limit: int = 3
    ) -> list[SkillMatch]:
        """按任务描述检索候选 Skill（token 重叠 + 触发条件 + 人格偏好）。"""
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        preferred = set(profile.behavior.preferred_skills)
        intent_categories = _intent_categories(query)
        matches: list[SkillMatch] = []
        for skill in self.for_agent(profile.id):
            text = " ".join(
                [
                    skill.name,
                    skill.description,
                    skill.when_to_use,
                    skill.category,
                    *skill.trigger_conditions,
                    *skill.examples,
                ]
            )
            skill_tokens = _tokens(text)
            shared = query_tokens & skill_tokens
            overlap = len(shared) / max(len(query_tokens), 1)
            trigger_hit = 1.0 if any(
                condition and condition in query for condition in skill.trigger_conditions
            ) else 0.0
            trigger_overlap = max(
                (
                    len(query_tokens & _tokens(condition))
                    / max(len(query_tokens), 1)
                    for condition in skill.trigger_conditions
                ),
                default=0.0,
            )
            name_hit = 1.0 if skill.name.replace("_", " ") in query.lower() else 0.0
            preference = 1.0 if skill.name in preferred else 0.0
            intent_boost = 1.0 if skill.category in intent_categories else 0.0
            score = (
                0.45 * overlap
                + 0.2 * max(trigger_hit, trigger_overlap)
                + 0.1 * name_hit
                + 0.15 * preference
                + 0.18 * intent_boost
            )
            if score <= 0.12:
                continue
            matches.append(
                SkillMatch(
                    skill=skill,
                    score=score,
                    matched_terms=sorted(shared)[:6],
                )
            )
        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[:limit]

    def render_candidates(
        self, profile: AgentProfile, query: str, limit: int = 3
    ) -> str:
        """生成给模型的「本轮候选 Skill」块（第一层：名称/描述/必填参数）。"""
        matches = self.match(profile, query, limit)
        if not matches:
            return ""
        lines = []
        for item in matches:
            skill = item.skill
            required = "、".join(skill.required_inputs) or "无必填参数"
            lines.append(
                f"- {skill.name}（{skill.category}，相关度 {item.score:.2f}）："
                f"{skill.description}；何时用：{skill.when_to_use or '按需'}；"
                f"必填参数：{required}"
            )
        return (
            "\n\n## 本轮候选 Skill（系统按当前问题检索，不是强制使用）\n"
            + "\n".join(lines)
            + "\n先判断任务是否真的需要；需要时调用 use_skill，并在 input 中给出必填参数。"
            "复杂任务可以组合多个 Skill，也可在拿到结果后改用其他 Skill。"
        )

    def execute(
        self, profile: AgentProfile, skill_name: str, inputs: dict | None = None
    ) -> SkillExecution:
        skill, handler = self.get(skill_name)
        if profile.id not in skill.applicable_agents:
            raise SkillPermissionError(f"{profile.id} 无权使用 Skill：{skill_name}")
        if not self.is_enabled(skill_name):
            raise SkillDisabledError(f"Skill 已停用：{skill_name}")
        payload = inputs or {}
        missing = [
            field
            for field in skill.required_inputs
            if field not in payload or payload[field] in (None, "", [], {})
        ]
        if missing:
            schema_hint = {
                key: value
                for key, value in (skill.input_schema.get("properties") or {}).items()
                if key in skill.required_inputs
            }
            raise SkillInputError(
                f"Skill {skill_name} 缺少必填参数：{'、'.join(missing)}；"
                f"请补齐后重试。参数要求：{schema_hint}"
            )
        try:
            validate(instance=payload, schema=skill.input_schema)
        except ValidationError as exc:
            raise SkillInputError(
                f"Skill 输入参数不符合要求：{exc.message}"
            ) from exc
        try:
            execution = handler(skill, payload)
        except Exception:
            self._failure_counts[skill_name] = self._failure_counts.get(skill_name, 0) + 1
            raise
        self._call_counts[skill_name] = self._call_counts.get(skill_name, 0) + 1
        return execution

    def stats(self) -> dict[str, Any]:
        self.ensure_loaded()
        return {
            "total": len(self._skills),
            "enabled": len([name for name in self._skills if self.is_enabled(name)]),
            "disabled": sorted(self._disabled & set(self._skills)),
            "calls": dict(self._call_counts),
            "failures": dict(self._failure_counts),
        }


skills_registry = SkillRegistry()
