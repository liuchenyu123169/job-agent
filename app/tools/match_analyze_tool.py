"""匹配分析工具 — 分析简历与岗位描述的匹配度。"""

import logging

from app.workflows.analyze import analyze_graph
from app.workflows.state import make_initial_state
from app.tools.base import ToolDefinition, ToolResult
from app.tools.registry import tool_registry

logger = logging.getLogger(__name__)

# ── 输入参数 JSON Schema（OpenAI function-calling 兼容） ──
MATCH_ANALYZE_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "resume_id": {
            "type": "integer",
            "description": "简历 ID（全局 ID）",
        },
        "job_id": {
            "type": "integer",
            "description": "岗位 ID（全局 ID）",
        },
    },
    "required": ["resume_id", "job_id"],
}


async def match_analyze_execute(
    resume_id: int,
    job_id: int,
    user_id: int,
    **kwargs,
) -> ToolResult:
    """执行简历-岗位匹配分析。"""
    logger.info("[match_analyze] resume_id=%s job_id=%s user_id=%s", resume_id, job_id, user_id)
    try:
        initial = make_initial_state(int(user_id), int(resume_id), int(job_id))
        final_state = await analyze_graph.ainvoke(initial)
        if final_state.get("error_msg"):
            return ToolResult.fail(str(final_state["error_msg"]))
        return ToolResult.ok({
            "task_id": final_state.get("task_id"),
            "analysis": final_state.get("analysis") or {},
        })
    except Exception as exc:
        logger.error("[match_analyze] failed: %s", exc)
        return ToolResult.fail(str(exc))


# ── 构建 Tool 并注册 ──
match_analyze_tool = ToolDefinition(
    name="match_analyze",
    description="分析简历与岗位描述的匹配度，返回匹配分数、优势、劣势和改进建议。适用于用户想了解自己与某个岗位的匹配程度时调用。",
    parameters=MATCH_ANALYZE_PARAMETERS,
    execute=match_analyze_execute,
    keywords=["匹配", "分析", "评分", "对比", "合适", "适合"],
    render_type="match_analysis",
)

tool_registry.register(match_analyze_tool)
