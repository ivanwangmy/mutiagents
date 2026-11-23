from __future__ import annotations

from app.skills.base import SkillExecution, build_execution

_COMMON_CHECKS = [
    "是否先确认学习者当前的理解水平",
    "是否用具体例子替代抽象术语",
    "是否给学习者留下可回答的小问题",
]

_SKILLS: dict[str, dict[str, list[str]]] = {
    "knowledge_organization": {
        "steps": [
            "把零散信息按主题分组，并说明分组依据",
            "建立层级：核心概念 → 支撑要点 → 例子",
            "为每组提炼一句话要点",
            "给出推荐的复习顺序与理由",
        ],
        "checks": [
            "分组是否互斥且覆盖主要信息",
            "层级是否体现依赖关系",
            "是否保留了原讨论中的条件与限定",
        ],
    },
    "problem_decomposition": {
        "steps": [
            "明确问题最终要回答什么",
            "把大问题拆成若干可独立回答的子问题",
            "标注子问题之间的依赖顺序",
            "指出先回答哪一个，以及为什么",
        ],
        "checks": [
            "子问题是否具体到可以动手回答",
            "是否遗漏关键前置问题",
            "拆分后是否仍指向原问题",
        ],
    },
    "learning_assistance": {
        "steps": [
            "定位学习者卡住的具体环节",
            "用一个生活化类比建立直觉",
            "分步解释，每步只引入一个新概念",
            "给出一道即时练习与判断标准",
        ],
        "checks": [
            "类比是否与目标概念结构一致",
            "是否避免一次引入多个新术语",
            "练习是否能检验是否真正理解",
        ],
    },
    "information_summarization": {
        "steps": [
            "列出已经达成一致的要点",
            "单独保留仍存在分歧的观点及双方理由",
            "列出尚未回答的问题",
            "给出一句话的阶段性结论",
        ],
        "checks": [
            "是否保留分歧而不是强行统一",
            "是否标明每条要点的提出者",
            "是否遗漏了关键限定条件",
        ],
    },
    "knowledge_gap_detection": {
        "steps": [
            "找出讲解默认听众已具备的前置知识",
            "标出未解释就使用的术语",
            "指出隐藏的适用条件或假设",
            "给出最小补充方案",
        ],
        "checks": [
            "缺口是否具体到某句话",
            "补充是否必要而非扩展过多",
            "是否说明缺口会导致什么误解",
        ],
    },
    "explanation_adaptation": {
        "steps": [
            "从学习者表达中判断其背景与困惑类型",
            "调整解释深度与术语密度",
            "替换为更贴近其经验的例子",
            "确认调整后仍保持概念准确性",
        ],
        "checks": [
            "是否回应了学习者的具体信号",
            "简化是否造成概念失真",
            "是否给出可继续追问的入口",
        ],
    },
}


def run(skill, inputs: dict) -> SkillExecution:
    spec = _SKILLS.get(skill.name)
    if spec is None:
        raise ValueError(f"教学支持模块不支持 Skill：{skill.name}")
    return build_execution(
        skill,
        inputs,
        list(spec["steps"]),
        list(spec["checks"]) + _COMMON_CHECKS,
    )
