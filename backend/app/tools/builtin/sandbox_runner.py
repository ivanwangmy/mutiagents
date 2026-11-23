"""独立沙箱子进程入口：在受限 builtins 下执行用户代码。

由 python_sandbox 工具以 `python -I sandbox_runner.py code.py` 启动，
不导入应用代码，不读取环境变量中的密钥。
"""
from __future__ import annotations

import builtins
import contextlib
import importlib
import io
import json
import sys

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

SAFE_BUILTIN_NAMES = [
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "int",
    "isinstance",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "pow",
    "print",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "slice",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
    "Exception",
    "ValueError",
    "TypeError",
    "ZeroDivisionError",
    "KeyError",
    "IndexError",
    "StopIteration",
    "ArithmeticError",
    "RuntimeError",
]


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    root = name.split(".")[0]
    if root not in ALLOWED_MODULES or level != 0:
        raise ImportError(f"沙箱不允许导入模块：{name}")
    return importlib.import_module(name)


def main() -> None:
    code_path = sys.argv[1]
    with open(code_path, encoding="utf-8") as handle:
        source = handle.read()

    safe_builtins = {name: getattr(builtins, name) for name in SAFE_BUILTIN_NAMES}
    safe_builtins["__import__"] = _safe_import

    namespace = {
        "__builtins__": safe_builtins,
        "__name__": "__sandbox__",
    }
    output = io.StringIO()
    payload: dict
    try:
        compiled = compile(source, "<sandbox>", "exec")
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            exec(compiled, namespace)  # noqa: S102 - 已由父进程 AST 校验 + 子进程隔离
        payload = {"ok": True, "output": output.getvalue()}
    except BaseException as exc:  # noqa: BLE001
        payload = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "output": output.getvalue(),
        }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
