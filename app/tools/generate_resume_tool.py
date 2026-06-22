"""简历生成工具 — 根据候选人背景和目标岗位 JD 生成完整优化简历。

支持两种输入方式：
- 有简历 → 传 resume_id，系统使用已有简历内容
- 没简历 → 传 personal_info 自由文本（技能/经历/项目/学历等）
"""

import logging

from app.workflows.generate import generate_resume_graph
from app.workflows.state import make_initial_state
from app.tools.base import ToolDefinition, ToolResult
from app.tools.registry import tool_registry

logger = logging.getLogger(__name__)

# ── 输入参数 JSON Schema ──
GENERATE_RESUME_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "resume_id": {
            "type": "integer",
            "description": "已有简历 ID（全局 ID）。如果不传则必须传 personal_info。",
        },
        "personal_info": {
            "type": "string",
            "description": "自由文本输入的个人信息，包括技能、工作/实习经历、项目经历、教育背景等。如果不传 resume_id 则必填。",
        },
        "job_id": {
            "type": "integer",
            "description": "目标岗位 ID（全局 ID）",
        },
    },
    "required": ["job_id"],
}


async def generate_resume_execute(
    job_id: int,
    user_id: int,
    resume_id: int = 0,
    personal_info: str = "",
    **kwargs,
) -> ToolResult:
    """执行简历生成。"""
    logger.info(
        "[generate_resume] resume_id=%s personal_info_len=%s job_id=%s user_id=%s",
        resume_id, len(personal_info), job_id, user_id,
    )

    if (not resume_id or resume_id <= 0) and not personal_info.strip():
        return ToolResult.fail("请提供简历 ID（resume_id）或输入您的个人信息（personal_info）")

    try:
        initial = make_initial_state(int(user_id), int(resume_id or 0), int(job_id), personal_info=str(personal_info or ""))
        final_state = await generate_resume_graph.ainvoke(initial)
        if final_state.get("error_msg"):
            return ToolResult.fail(str(final_state["error_msg"]))
        return ToolResult.ok({
            "task_id": final_state.get("task_id"),
            "generated_resume": final_state.get("generated_resume") or "",
        })
    except Exception as exc:
        logger.error("[generate_resume] failed: %s", exc)
        return ToolResult.fail(str(exc))


# ── 构建 Tool 并注册 ──
generate_resume_tool = ToolDefinition(
    name="generate_resume",
    description="根据候选人背景（已有简历或自由文本输入）和目标岗位 JD，生成一份完整、专业、针对性优化的简历。适用于用户想要定制简历时调用。",
    parameters=GENERATE_RESUME_PARAMETERS,
    execute=generate_resume_execute,
    keywords=["生成简历", "定制简历", "写简历", "简历生成", "做简历", "制作简历"],
    render_type="full_text",
)

tool_registry.register(generate_resume_tool)
