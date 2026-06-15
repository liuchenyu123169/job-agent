"""面试题生成工具 — 针对特定岗位生成面试题（支持 RAG 知识库增强）。"""

import logging

from app.agent.workflow import run_interview_questions_workflow
from app.tools.base import ToolDefinition, ToolResult
from app.tools.registry import tool_registry

logger = logging.getLogger(__name__)

# ── 输入参数 JSON Schema ──
INTERVIEW_QUESTIONS_PARAMETERS: dict = {
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
        "enable_rag": {
            "type": "boolean",
            "description": "是否启用 RAG 知识库增强，默认为 true。当用户需要更精准的面试题时开启。",
            "default": True,
        },
    },
    "required": ["resume_id", "job_id"],
}


async def interview_questions_execute(
    resume_id: int,
    job_id: int,
    user_id: int,
    enable_rag: bool = True,
    **kwargs,
) -> ToolResult:
    """生成面试题（技术题、项目题、行为题、风险题）。"""
    logger.info(
        "[generate_interview_questions] resume_id=%s job_id=%s enable_rag=%s user_id=%s",
        resume_id, job_id, enable_rag, user_id,
    )
    try:
        result = run_interview_questions_workflow(
            resume_id=int(resume_id),
            job_id=int(job_id),
            user_id=int(user_id),
            enable_rag=bool(enable_rag),
        )
        if result.get("error_msg"):
            return ToolResult.fail(str(result["error_msg"]))
        return ToolResult.ok({
            "task_id": result.get("task_id"),
            "questions": result.get("interview_questions") or {},
        })
    except Exception as exc:
        logger.error("[generate_interview_questions] failed: %s", exc)
        return ToolResult.fail(str(exc))


# ── 构建 Tool 并注册 ──
interview_questions_tool = ToolDefinition(
    name="generate_interview_questions",
    description=(
        "针对特定岗位生成面试题，涵盖技术题、项目题、行为题和风险题四类。"
        "支持 RAG 知识库增强（enable_rag=true 时自动从知识库检索相关知识作为出题依据）。"
        "在匹配分析或简历优化之后，用户需要准备面试时调用。"
    ),
    parameters=INTERVIEW_QUESTIONS_PARAMETERS,
    execute=interview_questions_execute,
)

tool_registry.register(interview_questions_tool)
