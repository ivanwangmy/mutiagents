from __future__ import annotations

import math
import re
from typing import Any

_CJK = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")


def estimate_tokens(text: str) -> int:
    """保守的 Token 估算（中文按 1 字 ≈ 1 token，英文按 4 字符 ≈ 1 token）。

    用于上下文裁剪与预算预检；实际用量以模型返回的 usage 为准。
    """
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return math.ceil(cjk + other / 4)


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        total += 4  # 角色与分隔符开销
        content = message.get("content") or ""
        if isinstance(content, str):
            total += estimate_tokens(content)
        for call in message.get("tool_calls") or []:
            total += estimate_tokens(str(call.get("function", {}).get("arguments", "")))
    return total


def truncate_text(text: str, max_tokens: int) -> str:
    if estimate_tokens(text) <= max_tokens:
        return text
    # 按字符比例截断，留出省略标记
    ratio = max_tokens / max(estimate_tokens(text), 1)
    keep = max(1, int(len(text) * ratio) - 8)
    return text[:keep] + "…（已截断）"
