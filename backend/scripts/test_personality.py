r"""人格差异测试：用相同问题分别询问 Alex / Mia / Ethan，输出真实模型结果与差异指标。

用法：backend\.venv\Scripts\python.exe scripts\test_personality.py
结果写入 docs\PERSONALITY_TEST_REPORT.md
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
load_dotenv(BACKEND / ".env")
sys.path.insert(0, str(BACKEND))

from app.agents.registry import registry  # noqa: E402

TOPICS = [
    "人工智能是否会替代人类劳动？",
    "经济增长是否必然提高社会福利？",
    "大学生是否应该使用 AI 完成学习任务？",
]

MARKERS = {
    "alex": ["定义", "前提", "条件", "推理", "结论", "边界", "成立"],
    "mia": ["步骤", "例子", "拆解", "检查", "理解", "小结", "比如"],
    "ethan": ["我觉得", "如果", "有没有可能", "反例", "质疑", "我理解", "为什么"],
}
ROLE_WORDS = {"alex": "Alex", "mia": "Mia", "ethan": "Ethan"}


def bigrams(text: str) -> set[str]:
    cleaned = re.sub(r"\s+", "", text)
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def similarity(a: str, b: str) -> float:
    sa, sb = bigrams(a), bigrams(b)
    if not sa or not sb:
        return 0.0
    return round(len(sa & sb) / len(sa | sb), 3)


def main() -> None:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("缺少 DEEPSEEK_API_KEY，无法进行真实人格测试")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
    client = OpenAI(api_key=api_key, base_url=os.getenv("DEEPSEEK_BASE_URL"), timeout=90.0, max_retries=1)
    thinking_on = os.getenv("DEEPSEEK_THINKING_ENABLED", "false").lower() in {"1", "true", "yes"}
    extra_body = None if thinking_on else {"thinking": {"type": "disabled"}}
    registry.load()

    results: dict[str, dict[str, str]] = {}
    usage_total = 0
    for topic in TOPICS:
        for profile in registry.all():
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": profile.system_prompt},
                    {"role": "user", "content": topic},
                ],
                temperature=profile.runtime.temperature,
                max_tokens=350, extra_body=extra_body,
            )
            content = (resp.choices[0].message.content or "").strip()
            results.setdefault(profile.id, {})[topic] = content
            if resp.usage:
                usage_total += resp.usage.total_tokens
            print(f"[{profile.id}] {topic} -> {len(content)} 字")

    lines: list[str] = [
        "# Agent 人格差异测试报告",
        "",
        f"- 执行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 模型：`{model}`（真实 API 调用，未使用模拟数据）",
        f"- 测试问题：{len(TOPICS)} 个；每个问题分别由 3 个 Agent 独立回答（单轮）",
        f"- 总 Token 消耗：{usage_total}",
        "",
        "## 一、差异指标",
        "",
        "| 问题 | 指标 | Alex | Mia | Ethan |",
        "|---|---|---|---|---|",
    ]

    for topic in TOPICS:
        texts = {agent_id: results[agent_id][topic] for agent_id in results}
        lengths = {k: len(v) for k, v in texts.items()}
        questions = {k: v.count("？") + v.count("?") for k, v in texts.items()}
        markers = {
            agent_id: sum(1 for m in MARKERS[agent_id] if m in texts[agent_id])
            for agent_id in texts
        }
        lines.append(
            f"| {topic} | 字数 | {lengths['alex']} | {lengths['mia']} | {lengths['ethan']} |"
        )
        lines.append(
            f"| | 问句数 | {questions['alex']} | {questions['mia']} | {questions['ethan']} |"
        )
        lines.append(
            f"| | 人格标记命中 | {markers['alex']}/7 | {markers['mia']}/7 | {markers['ethan']}/7 |"
        )

    lines += ["", "## 二、两两文本相似度（字符 bigram Jaccard，越低越独立）", "", "| 问题 | Alex-Mia | Alex-Ethan | Mia-Ethan |", "|---|---|---|---|"]
    sims: list[float] = []
    for topic in TOPICS:
        am = similarity(results["alex"][topic], results["mia"][topic])
        ae = similarity(results["alex"][topic], results["ethan"][topic])
        me = similarity(results["mia"][topic], results["ethan"][topic])
        sims.extend([am, ae, me])
        lines.append(f"| {topic} | {am} | {ae} | {me} |")

    max_sim = max(sims)
    role_confusion = []
    for agent_id, topic_map in results.items():
        for topic, text in topic_map.items():
            for other_id, other_name in ROLE_WORDS.items():
                if other_id == agent_id:
                    continue
                if f"我是{other_name}" in text:
                    role_confusion.append(f"{agent_id} 在「{topic}」中自称 {other_name}")

    lines += ["", "## 三、自动检查结论", ""]
    lines.append(f"- 9 次回答均非空：{'通过' if all(t.strip() for m in results.values() for t in m.values()) else '未通过'}")
    lines.append(f"- 最高两两相似度 {max_sim}（阈值 < 0.55）：{'通过' if max_sim < 0.55 else '未通过'}")
    lines.append(f"- 角色混淆：{'未发现' if not role_confusion else '；'.join(role_confusion)}")
    for agent_id in ("alex", "mia", "ethan"):
        hits = sum(1 for t in TOPICS if sum(1 for m in MARKERS[agent_id] if m in results[agent_id][t]) >= 2)
        lines.append(f"- {agent_id} 人格标记命中（≥2 个/题）：{hits}/3 题")

    lines += ["", "## 四、原始回答", ""]
    for topic in TOPICS:
        lines.append(f"### {topic}")
        for agent_id, name in (("alex", "Alex（教师）"), ("mia", "Mia（助教）"), ("ethan", "Ethan（学生）")):
            lines.append(f"**{name}**：")
            lines.append("")
            lines.append(results[agent_id][topic])
            lines.append("")

    report = ROOT / "docs" / "PERSONALITY_TEST_REPORT.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"report": str(report), "max_similarity": max_sim, "tokens": usage_total}, ensure_ascii=False))


if __name__ == "__main__":
    main()

