from __future__ import annotations

import ast
import math
import operator
from typing import Any

from app.tools.base import ToolDefinition, ToolResult

MAX_EXPRESSION_LENGTH = 300
MAX_POWER = 12

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "abs": abs,
    "round": round,
    "floor": math.floor,
    "ceil": math.ceil,
    "factorial": math.factorial,
}
_CONSTS = {"pi": math.pi, "e": math.e}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("仅支持数字常量")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_POWER:
            raise ValueError(f"指数绝对值不能超过 {MAX_POWER}")
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ValueError("不支持的函数")
        if node.keywords:
            raise ValueError("函数不支持关键字参数")
        args = [_eval_node(arg) for arg in node.args]
        return _FUNCS[node.func.id](*args)
    raise ValueError("表达式包含不支持的语法")


async def calculate(arguments: dict[str, Any]) -> Any:
    expression = str(arguments.get("expression", "")).strip()
    if not expression:
        raise ValueError("expression 不能为空")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError("表达式过长")
    tree = ast.parse(expression, mode="eval")
    value = _eval_node(tree)
    if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
        raise ValueError("计算结果不是有限数值")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return {"expression": expression, "value": value}


def build_tool() -> ToolDefinition:
    return ToolDefinition(
        name="calculator",
        description="执行精确的数学表达式计算，支持四则运算、幂、取模与常用数学函数。",
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "数学表达式，例如 (12*7+5)/3 或 sqrt(2)",
                }
            },
            "required": ["expression"],
            "additionalProperties": False,
        },
        handler=calculate,
        timeout_seconds=3.0,
    )


def error_result(message: str) -> ToolResult:
    return ToolResult(ok=False, error=message)
