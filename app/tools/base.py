from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class ToolResult:
    """Unified result wrapper for all tool executions."""
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None

    @classmethod
    def ok(cls, data: dict[str, Any]) -> "ToolResult":
        return cls(success=True, data=data, error=None)

    @classmethod
    def fail(cls, error: str) -> "ToolResult":
        return cls(success=False, data=None, error=error)


@dataclass
class ToolDefinition:
    """Standard tool definition compatible with OpenAI function-calling format."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the tool's input parameters
    execute: Callable[..., Awaitable[ToolResult]] = field(repr=False)

    def to_openai_function(self) -> dict[str, Any]:
        """Return the tool definition in OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
