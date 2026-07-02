from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class InputRequirements:
    """声明工具执行需要什么上下文输入。

    Precheck 阶段会遍历 plan_steps，收集所有步骤需要的输入，
    只在需要的输入缺失时才 block。纯查询类工具全部为 False。
    """
    resume_id: bool = False
    job_id: bool = False
    task_id: bool = False
    query: bool = False  # search_knowledge 需要


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
    keywords: list[str] = field(default_factory=list)  # 前端意图匹配用
    render_type: str = "generic"  # 前端渲染类型: "match_analysis" | "questions" | "scored_list" | "full_text" | "item_list" | "generic"
    input_requirements: InputRequirements = field(default_factory=InputRequirements)  # Precheck 用

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

    def to_api_dict(self) -> dict[str, Any]:
        """返回给前端的工具信息（不含 execute 回调）。"""
        return {
            "name": self.name,
            "description": self.description,
            "keywords": self.keywords,
            "render_type": self.render_type,
        }
