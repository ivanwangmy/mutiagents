r"""真实探测 DeepSeek 模型能力：模型列表、文本、流式、原生 Tool Calling、JSON 输出。

用法：backend\.venv\Scripts\python.exe scripts\probe_model.py
只输出能力结果，不输出 API Key；同时写入 data\model_capabilities.json 供 /api/system/config-status 使用。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()

if not api_key:
    print(json.dumps({"ok": False, "error": "缺少 DEEPSEEK_API_KEY"}, ensure_ascii=False))
    sys.exit(1)

client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0, max_retries=0)
thinking_on = os.getenv("DEEPSEEK_THINKING_ENABLED", "false").lower() in {"1", "true", "yes"}
extra_body = None if thinking_on else {"thinking": {"type": "disabled"}}
result: dict = {"base_url": base_url, "configured_model": model, "thinking_enabled": thinking_on}

try:
    models = client.models.list()
    result["models"] = [m.id for m in models.data]
except Exception as exc:  # noqa: BLE001
    result["models_error"] = f"{type(exc).__name__}: {exc}"

# 1. 普通文本
try:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "只回复两个字：正常"}],
        max_tokens=20, extra_body=extra_body,
        temperature=0,
    )
    result["text"] = {
        "ok": True,
        "content": resp.choices[0].message.content,
        "usage": resp.usage.model_dump() if resp.usage else None,
    }
except Exception as exc:  # noqa: BLE001
    result["text"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

# 2. 流式（允许一次重试，避免偶发空响应误判）
stream_info: dict = {}
for attempt in range(2):
    try:
        chunks = []
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "请输出：流式测试通过"}],
            max_tokens=50, extra_body=extra_body,
            temperature=0,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)
        stream_info = {
            "ok": bool(chunks),
            "chunks": len(chunks),
            "preview": "".join(chunks)[:80],
            "attempts": attempt + 1,
        }
        if chunks:
            break
    except Exception as exc:  # noqa: BLE001
        stream_info = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "attempts": attempt + 1,
        }
result["stream"] = stream_info

# 3. 原生 Tool Calling
tools = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "计算数学表达式",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        },
    }
]
try:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "请调用 calculator 计算 12*7+5"}],
        tools=tools,
        tool_choice="auto",
        max_tokens=120, extra_body=extra_body,
        temperature=0,
    )
    msg = resp.choices[0].message
    calls = [tc.function.name for tc in (msg.tool_calls or [])]
    result["tool_calling"] = {
        "ok": bool(calls),
        "calls": calls,
        "arguments": [tc.function.arguments for tc in (msg.tool_calls or [])],
        "finish_reason": resp.choices[0].finish_reason,
    }
except Exception as exc:  # noqa: BLE001
    result["tool_calling"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

# 4. 结构化 JSON
try:
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "只输出 JSON，不要其他文字。"},
            {"role": "user", "content": '输出 {"status":"ok","number":42}'},
        ],
        response_format={"type": "json_object"},
        max_tokens=200, extra_body=extra_body,
        temperature=0,
    )
    content = resp.choices[0].message.content or ""
    parsed = json.loads(content)
    result["structured_output"] = {"ok": True, "parsed": parsed}
except Exception as exc:  # noqa: BLE001
    result["structured_output"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

out_dir = ROOT / "data"
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / "model_capabilities.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(result, ensure_ascii=False, indent=2))

