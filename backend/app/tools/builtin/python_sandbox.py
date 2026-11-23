from __future__ import annotations

import ast
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import psutil

from app.tools.base import ToolDefinition, ToolResult

ALLOWED_MODULES = {
    "math",
    "statistics",
    "json",
    "itertools",
    "functools",
    "collections",
    "random",
    "re",
    "datetime",
    "decimal",
    "fractions",
    "string",
    "heapq",
    "bisect",
}
BLOCKED_NAMES = {
    "open",
    "exec",
    "eval",
    "compile",
    "__import__",
    "input",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "breakpoint",
    "memoryview",
}
BLOCKED_MODULES = {
    "os",
    "sys",
    "subprocess",
    "socket",
    "pathlib",
    "shutil",
    "ctypes",
    "multiprocessing",
    "threading",
    "importlib",
    "builtins",
    "requests",
    "urllib",
    "http",
    "ftplib",
    "pickle",
    "marshal",
}
MAX_CODE_LENGTH = 6000
MAX_OUTPUT_CHARS = 4000
MAX_MEMORY_MB = 256
MAX_SECONDS = 5.0
MAX_CONCURRENCY = 2

_semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
_RUNNER = Path(__file__).resolve().parent / "sandbox_runner.py"


class SandboxValidationError(ValueError):
    pass


def validate_code(source: str) -> None:
    if len(source) > MAX_CODE_LENGTH:
        raise SandboxValidationError(f"代码长度不能超过 {MAX_CODE_LENGTH} 字符")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise SandboxValidationError(f"语法错误：{exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_MODULES:
                    raise SandboxValidationError(f"不允许导入模块：{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or (node.module or "").split(".")[0] not in ALLOWED_MODULES:
                raise SandboxValidationError(f"不允许导入模块：{node.module}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise SandboxValidationError("不允许访问双下划线属性")
        elif isinstance(node, ast.Name):
            if node.id in BLOCKED_NAMES:
                raise SandboxValidationError(f"不允许使用：{node.id}")
            if node.id in BLOCKED_MODULES:
                raise SandboxValidationError(f"不允许使用模块：{node.id}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in BLOCKED_NAMES:
                raise SandboxValidationError(f"不允许调用：{node.func.id}")


def _execute_in_subprocess(code_path: Path, tmp: str) -> tuple[str, str]:
    """在独立进程中执行代码，并限制耗时、内存与并发。

    使用线程 + 子进程而非 asyncio 子进程，以兼容 Windows SelectorEventLoop
    （PostgreSQL 异步驱动要求）。
    """
    out_path = Path(tmp) / "stdout.txt"
    err_path = Path(tmp) / "stderr.txt"
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": "",
        "PYTHONNOUSERSITE": "1",
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": tmp,
        "TMP": tmp,
    }
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with open(out_path, "wb") as out_file, open(err_path, "wb") as err_file:
        process = subprocess.Popen(
            [sys.executable, "-I", str(_RUNNER), str(code_path)],
            cwd=tmp,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out_file,
            stderr=err_file,
            creationflags=creationflags,
        )
        tracked = psutil.Process(process.pid)
        deadline = time.monotonic() + MAX_SECONDS
        try:
            while process.poll() is None:
                if time.monotonic() > deadline:
                    process.kill()
                    process.wait()
                    raise SandboxValidationError(f"执行超时（>{MAX_SECONDS} 秒）")
                try:
                    rss_mb = tracked.memory_info().rss / (1024 * 1024)
                    if rss_mb > MAX_MEMORY_MB:
                        process.kill()
                        process.wait()
                        raise SandboxValidationError(f"内存超过 {MAX_MEMORY_MB} MB")
                except psutil.NoSuchProcess:
                    break
                time.sleep(0.05)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    return (
        out_path.read_text(encoding="utf-8", errors="replace"),
        err_path.read_text(encoding="utf-8", errors="replace"),
    )


async def run_python(arguments: dict[str, Any]) -> Any:
    code = str(arguments.get("code", ""))
    validate_code(code)

    async with _semaphore:
        with tempfile.TemporaryDirectory(prefix="ai_classroom_sandbox_") as tmp:
            code_path = Path(tmp) / "code.py"
            code_path.write_text(code, encoding="utf-8")
            stdout_text, stderr_text = await asyncio.to_thread(
                _execute_in_subprocess, code_path, tmp
            )

            text = stdout_text.strip()
            if not text:
                detail = stderr_text[:300]
                raise RuntimeError(f"沙箱未返回结果：{detail}")
            payload = json.loads(text)
            output = (payload.get("output") or "")[:MAX_OUTPUT_CHARS]
            if not payload.get("ok"):
                raise RuntimeError(payload.get("error") or "执行失败")
            return {
                "output": output,
                "truncated": len(payload.get("output") or "") > MAX_OUTPUT_CHARS,
                "timeout_seconds": MAX_SECONDS,
                "memory_limit_mb": MAX_MEMORY_MB,
            }


def build_tool() -> ToolDefinition:
    return ToolDefinition(
        name="python_sandbox",
        description=(
            "在独立隔离进程中执行 Python 代码并返回标准输出。"
            "仅允许数学/统计/JSON 等白名单模块，禁止文件、网络与系统调用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "要执行的 Python 代码，用 print 输出结果",
                }
            },
            "required": ["code"],
            "additionalProperties": False,
        },
        handler=run_python,
        timeout_seconds=MAX_SECONDS + 2,
        risk_level="medium",
        requires_isolation=True,
    )


def error_result(message: str) -> ToolResult:
    return ToolResult(ok=False, error=message)
