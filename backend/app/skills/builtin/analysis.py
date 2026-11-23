from __future__ import annotations

from app.skills.base import SkillExecution, build_execution

_COMMON_CHECKS = [
    "是否先复述了用户问题，再给出结论",
    "是否区分了事实、推断与假设",
    "是否说明了结论成立的适用条件",
]

_SKILLS: dict[str, dict[str, list[str]]] = {
    "concept_explanation": {
        "steps": [
            "用一句可操作的话给出概念的严格定义",
            "划出适用边界：什么情况属于该概念，什么情况不属于",
            "对比至少一个容易混淆的邻近概念，说明差异",
            "给出一个正例和一个反例",
        ],
        "checks": [
            "定义是否可被检验，而不是同义反复",
            "是否说明了概念成立的前提条件",
            "是否区分了近邻概念",
        ],
    },
    "theory_analysis": {
        "steps": [
            "列出分析依赖的前提假设",
            "建立前提 → 机制 → 结论的推理链",
            "为每一步标注需要的证据或条件",
            "指出结论可能失效的反例情形",
        ],
        "checks": [
            "前提是否被明确写出而非默认",
            "推理链是否存在跳跃",
            "结论强度是否超过证据支持的范围",
        ],
    },
    "logical_reasoning": {
        "steps": [
            "把原论证重建成前提、推论、结论三段",
            "检查跳跃、循环论证、以偏概全与因果倒置",
            "指出最关键的逻辑缺口",
            "给出修复后的论证或补充条件",
        ],
        "checks": [
            "是否定位到具体句子而非泛泛评价",
            "是否说明了缺口为何影响结论",
            "修复方案是否可执行",
        ],
    },
    "knowledge_verification": {
        "steps": [
            "把事实性陈述拆成可独立核查的小命题",
            "判断每条命题属于已证实、待核实还是不可证实",
            "说明需要的证据类型与核实路径",
            "指出当前表述中过强或模糊的部分",
        ],
        "checks": [
            "是否区分了证据不足与证据相反",
            "是否给出可执行的核查路径",
            "是否避免把推测表述为事实",
        ],
    },
    "teaching_guidance": {
        "steps": [
            "把结论转化为学习者可执行的理解步骤",
            "每一步配一个自检问题",
            "给出一个最小练习与判断标准",
            "指出最常见的错误理解",
        ],
        "checks": [
            "步骤是否有先后依赖",
            "自检问题是否能暴露误解",
            "练习是否可在短时间内完成",
        ],
    },
    "answer_evaluation": {
        "steps": [
            "先准确复述被评价观点的核心主张",
            "列出成立的部分及其理由",
            "指出缺口：证据、条件或推理",
            "给出总体判断与改进方向",
        ],
        "checks": [
            "是否避免人身评价，只评价论证",
            "是否引用了对方的具体表述",
            "结论是否与所列证据一致",
        ],
    },
}


def run(skill, inputs: dict) -> SkillExecution:
    spec = _SKILLS.get(skill.name)
    if spec is None:
        raise ValueError(f"理论分析模块不支持 Skill：{skill.name}")
    return build_execution(
        skill,
        inputs,
        list(spec["steps"]),
        list(spec["checks"]) + _COMMON_CHECKS,
    )
