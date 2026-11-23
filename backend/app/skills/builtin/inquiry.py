from __future__ import annotations

from app.skills.base import SkillExecution, build_execution

_COMMON_CHECKS = [
    "是否引用了对方的具体观点而不是泛泛质疑",
    "是否说明了质疑依据",
    "是否在被说服时明确修正自己的立场",
]

_SKILLS: dict[str, dict[str, list[str]]] = {
    "curiosity_exploration": {
        "steps": [
            "从当前结论出发提出一个尚未讨论的问题",
            "说明这个问题为什么值得讨论",
            "给出可能的讨论方向或初步猜想",
        ],
        "checks": [
            "问题是否与原主题相关",
            "是否避免为了提问而提问",
            "是否给出可继续讨论的抓手",
        ],
    },
    "critical_questioning": {
        "steps": [
            "明确指出要质疑的具体论断",
            "给出反例、证据缺口或推理跳步",
            "说明需要什么证据才能支持原论断",
        ],
        "checks": [
            "质疑是否针对观点而非个人",
            "是否给出可检验的反例或证据要求",
            "是否承认原观点可能成立的条件",
        ],
    },
    "assumption_detection": {
        "steps": [
            "列出论证成立所依赖的隐含假设",
            "指出其中最脆弱的一条",
            "设计一个能检验该假设的思想实验",
        ],
        "checks": [
            "假设是否真的未被明说",
            "检验方案是否可操作",
            "是否说明假设不成立时结论会怎样",
        ],
    },
    "interdisciplinary_association": {
        "steps": [
            "在另一学科或生活场景中寻找相似结构",
            "说明类比对应的关键要素",
            "指出类比的边界与失效之处",
            "回到原问题给出新视角",
        ],
        "checks": [
            "类比是否结构相似而非表面相似",
            "是否说明类比不能推广的部分",
            "是否真的帮助理解了原问题",
        ],
    },
    "alternative_hypothesis": {
        "steps": [
            "提出至少一个能解释同一现象的其他原因",
            "说明两个解释在预测上的差异",
            "指出能区分它们的关键证据",
        ],
        "checks": [
            "替代解释是否与原现象兼容",
            "是否给出可区分的证据",
            "是否避免把相关误当因果",
        ],
    },
    "student_perspective_evaluation": {
        "steps": [
            "用自己的话复述刚听到的解释",
            "指出仍然模糊或需要补充的地方",
            "给出一道检验自己是否掌握的题",
        ],
        "checks": [
            "复述是否忠实于原意",
            "模糊点是否具体",
            "自测题是否能暴露理解缺口",
        ],
    },
}


def run(skill, inputs: dict) -> SkillExecution:
    spec = _SKILLS.get(skill.name)
    if spec is None:
        raise ValueError(f"质疑探究模块不支持 Skill：{skill.name}")
    return build_execution(
        skill,
        inputs,
        list(spec["steps"]),
        list(spec["checks"]) + _COMMON_CHECKS,
    )
