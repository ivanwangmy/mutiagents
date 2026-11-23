from __future__ import annotations

from app.core.logging import get_logger
from app.tools.base import ToolDefinition
from app.tools.builtin import calculator, datetime_tool, python_sandbox

logger = get_logger(__name__)


class ToolRegistry:
    """工具注册表：只保存可被后端真实执行的工具定义。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重复注册：{tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(name)
        return tool

    def has(self, name: str) -> bool:
        return name in self._tools

    def all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools)

    def to_openai_tools(self, names: list[str] | None = None) -> list[dict]:
        selected = self._tools.values() if names is None else (
            self._tools[name] for name in names if name in self._tools
        )
        return [tool.to_openai_tool() for tool in selected]


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for module in (calculator, datetime_tool, python_sandbox):
        registry.register(module.build_tool())
    logger.info("ToolRegistry 初始化：%s", ", ".join(registry.names()))
    return registry


tool_registry = build_default_registry()
