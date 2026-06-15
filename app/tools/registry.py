"""工具注册中心 — 全局单例，管理所有 Copilot Tool 的注册与查找。"""

from app.tools.base import ToolDefinition


class ToolRegistry:
    """工具注册中心，支持按名称查找和生成 OpenAI function-calling 格式的工具列表。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """注册一个工具，同名工具会被覆盖。"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        """按名称查找工具，未找到返回 None。"""
        return self._tools.get(name)

    def list_all(self) -> list[ToolDefinition]:
        """返回所有已注册的工具列表。"""
        return list(self._tools.values())

    def get_function_definitions(self) -> list[dict]:
        """生成 OpenAI function-calling 格式的工具定义列表，供 LLM 使用。"""
        return [tool.to_openai_function() for tool in self._tools.values()]


# 全局单例
tool_registry = ToolRegistry()
