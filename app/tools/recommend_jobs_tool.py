"""岗位推荐工具 — 基于简历内容对所有岗位做匹配打分并推荐最佳岗位。"""

import asyncio
import logging

from app.domains.job.matcher import recommend_jobs_for_resume
from app.tools.base import ToolDefinition, ToolResult
from app.tools.registry import tool_registry

logger = logging.getLogger(__name__)

# ── 输入参数 JSON Schema ──
RECOMMEND_JOBS_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "resume_id": {
            "type": "integer",
            "description": "简历 ID（全局 ID）",
        },
        "top_k": {
            "type": "integer",
            "description": "返回匹配度最高的前 K 个岗位，默认为 5",
            "default": 5,
        },
        "max_jobs": {
            "type": "integer",
            "description": "最多参与比对的岗位数量，默认为 10",
            "default": 10,
        },
    },
    "required": ["resume_id"],
}


async def recommend_jobs_execute(
    resume_id: int,
    user_id: int,
    top_k: int = 5,
    max_jobs: int = 10,
    **kwargs,
) -> ToolResult:
    """执行岗位推荐。"""
    logger.info(
        "[recommend_jobs] resume_id=%s top_k=%s max_jobs=%s user_id=%s",
        resume_id, top_k, max_jobs, user_id,
    )
    try:
        result = await asyncio.to_thread(
            recommend_jobs_for_resume,
            resume_id=int(resume_id),
            top_k=int(top_k),
            max_jobs=int(max_jobs),
            user_id=int(user_id),
        )
        if result.get("error_msg"):
            return ToolResult.fail(str(result["error_msg"]))
        return ToolResult.ok({
            "task_id": result.get("task_id"),
            "resume_id": result.get("resume_id"),
            "top_k": result.get("top_k"),
            "candidate_job_count": result.get("candidate_job_count"),
            "items": result.get("items") or [],
        })
    except Exception as exc:
        logger.error("[recommend_jobs] failed: %s", exc)
        return ToolResult.fail(str(exc))


# ── 构建 Tool 并注册 ──
recommend_jobs_tool = ToolDefinition(
    name="recommend_jobs",
    description=(
        "基于简历内容对所有已有岗位进行匹配打分，返回得分最高的前 K 个岗位。"
        "当用户还没有明确目标岗位、想看哪些岗位最适合自己时调用。"
    ),
    parameters=RECOMMEND_JOBS_PARAMETERS,
    execute=recommend_jobs_execute,
    keywords=["推荐", "岗位推荐", "适合", "哪些岗位"],
    render_type="scored_list",
)

tool_registry.register(recommend_jobs_tool)
