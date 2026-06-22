"""简历优化工具 — 针对特定岗位生成简历优化建议。"""

import logging

from app.workflows.optimize import optimize_resume_graph
from app.workflows.state import make_initial_state
from app.tools.base import ToolDefinition, ToolResult
from app.tools.registry import tool_registry

logger = logging.getLogger(__name__)

# ── 输入参数 JSON Schema ──
OPTIMIZE_RESUME_PARAMETERS: dict = {
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


async def optimize_resume_execute(
    resume_id: int,
    job_id: int,
    user_id: int,
    **kwargs,
) -> ToolResult:
    """执行简历优化分析。"""
    logger.info("[optimize_resume] resume_id=%s job_id=%s user_id=%s", resume_id, job_id, user_id)
    try:
        initial = make_initial_state(int(user_id), int(resume_id), int(job_id))
        final_state = await optimize_resume_graph.ainvoke(initial)
        if final_state.get("error_msg"):
            return ToolResult.fail(str(final_state["error_msg"]))
        return ToolResult.ok({
            "task_id": final_state.get("task_id"),
            "optimization": final_state.get("optimization_text") or {},
        })
    except Exception as exc:
        logger.error("[optimize_resume] failed: %s", exc)
        return ToolResult.fail(str(exc))


# ── 构建 Tool 并注册 ──
optimize_resume_tool = ToolDefinition(
    name="optimize_resume",
    description="针对特定岗位生成简历优化建议，包括技能关键词、项目建议、简历改写建议和潜在风险点。在匹配分析之后，用户想要改进简历时调用。",
    parameters=OPTIMIZE_RESUME_PARAMETERS,
    execute=optimize_resume_execute,
    keywords=["优化", "改进", "修改简历", "润色", "完善简历"],
    render_type="match_analysis",
)

tool_registry.register(optimize_resume_tool)
