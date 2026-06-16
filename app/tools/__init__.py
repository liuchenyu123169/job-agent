from app.tools.base import ToolDefinition, ToolResult
from app.tools.registry import ToolRegistry, tool_registry

# 注册所有工具（import 即执行注册）
import app.tools.match_analyze_tool  # noqa: F401
import app.tools.optimize_resume_tool  # noqa: F401
import app.tools.interview_questions_tool  # noqa: F401
import app.tools.recommend_jobs_tool  # noqa: F401
import app.tools.generate_resume_tool  # noqa: F401
import app.tools.utility_tools  # noqa: F401

__all__ = ["ToolDefinition", "ToolResult", "ToolRegistry", "tool_registry"]
