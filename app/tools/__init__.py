from app.tools.base import InputRequirements, ToolDefinition, ToolResult
from app.tools.registry import ToolRegistry, tool_registry

# 注册所有工具（import 即执行注册）
import app.tools.match_analyze_tool  # noqa: F401
import app.tools.optimize_resume_tool  # noqa: F401
import app.tools.interview_questions_tool  # noqa: F401
import app.tools.recommend_jobs_tool  # noqa: F401
import app.tools.generate_resume_tool  # noqa: F401
import app.tools.utility_tools  # noqa: F401
import app.tools.public_search_tool  # noqa: F401
import app.tools.fetch_job_page_tool  # noqa: F401

__all__ = ["InputRequirements", "ToolDefinition", "ToolResult", "ToolRegistry", "tool_registry"]
