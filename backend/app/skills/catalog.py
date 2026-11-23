"""Skill 元数据目录。

persona 只声明「技能做什么」；版本、分类与能力边界集中在这里维护，
避免 18 个技能在 YAML 中重复堆放相同字段，同时保证运行时 SkillSpec
一定具备完整元数据。新增 Skill 时必须在此登记，否则加载失败。
"""

from __future__ import annotations

from typing import Any

_COMMON_LIMIT = "只提供方法论步骤与检查点，不访问外部知识库、数据库或网络"

SKILL_METADATA: dict[str, dict[str, Any]] = {
    # Alex · 教师
    "concept_explanation": {
        "category": "concept",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "不替代教材中的标准定义与术语表"],
    },
    "theory_analysis": {
        "category": "theory",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "不提供领域专属模型参数或实证数据"],
    },
    "logical_reasoning": {
        "category": "logic",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "只能检查形式结构，不能判断事实真伪"],
    },
    "knowledge_verification": {
        "category": "verification",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "无法联网核查，只给出核查路径与证据类型"],
    },
    "teaching_guidance": {
        "category": "pedagogy",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "不掌握学习者的真实测评数据"],
    },
    "answer_evaluation": {
        "category": "evaluation",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "评价基于公开论证，不评价发言者本人"],
    },
    # Mia · 助教
    "knowledge_organization": {
        "category": "organization",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "整理结果依赖输入信息的完整度"],
    },
    "problem_decomposition": {
        "category": "decomposition",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "拆解粒度需要结合具体课程目标调整"],
    },
    "learning_assistance": {
        "category": "scaffolding",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "不替代针对性的人工诊断"],
    },
    "information_summarization": {
        "category": "summarization",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "只总结公开讨论记录，不推断未发言的立场"],
    },
    "knowledge_gap_detection": {
        "category": "diagnosis",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "盲区判断是启发式的，需要学习者确认"],
    },
    "explanation_adaptation": {
        "category": "adaptation",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "缺少学习者长期画像时只能做保守调整"],
    },
    # Ethan · 学生
    "curiosity_exploration": {
        "category": "exploration",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "提出的是待验证问题，不是研究结论"],
    },
    "critical_questioning": {
        "category": "critique",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "质疑需要对方给出可回应的具体论点"],
    },
    "assumption_detection": {
        "category": "assumption",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "隐含假设的识别依赖论证文本的完整度"],
    },
    "interdisciplinary_association": {
        "category": "analogy",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "类比只用于启发，不能当作证据"],
    },
    "alternative_hypothesis": {
        "category": "hypothesis",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "不提供区分性证据的实际采集"],
    },
    "student_perspective_evaluation": {
        "category": "perspective",
        "version": "1.0.0",
        "limitations": [_COMMON_LIMIT, "代表的是模拟学习者视角，不是真实学情数据"],
    },
}
