"""Agent API — 独立端点（已迁移到 Copilot SSE 流式 API 为主）。

保留端点：
  - POST /api/agent/recommend-jobs  → 岗位推荐（RecommendPanel.vue 使用）

已废弃端点（由 Copilot API 覆盖）：
  - POST /api/agent/analyze → 请使用 POST /api/copilot/run
  - POST /api/agent/optimize-resume → 请使用 POST /api/copilot/run
  - POST /api/agent/generate-interview-questions → 请使用 POST /api/copilot/run
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.domains.job.matcher import recommend_jobs_for_resume
from app.api.deps import get_current_user
from app.db.crud import resolve_resume_for_user
from app.schemas.agent_schema import (
    RecommendJobsRequest,
    RecommendJobsResponse,
)

router = APIRouter(prefix="/api/agent", tags=["Agent"])


def _resolve_resume_id(
    user_id: int,
    resume_id: int | None,
    local_resume_id: int | None,
) -> int | None:
    resume = resolve_resume_for_user(user_id=user_id, resume_id=resume_id, local_resume_id=local_resume_id)
    if resume is None:
        return None
    return int(resume["id"])


@router.post("/recommend-jobs", response_model=RecommendJobsResponse)
async def recommend_jobs(
    payload: RecommendJobsRequest,
    current_user: dict = Depends(get_current_user),
) -> RecommendJobsResponse:
    """岗位推荐：基于简历对所有岗位打分，返回 Top K。"""
    user_id = int(current_user["id"])
    resolved_resume_id = _resolve_resume_id(user_id, payload.resume_id, payload.local_resume_id)
    if resolved_resume_id is None:
        raise HTTPException(status_code=404, detail="简历未找到")
    result = await asyncio.to_thread(
        recommend_jobs_for_resume,
        resume_id=resolved_resume_id,
        top_k=payload.top_k,
        max_jobs=payload.max_jobs,
        user_id=user_id,
    )
    if result["error_msg"] == "简历未找到":
        raise HTTPException(status_code=404, detail="简历未找到")
    return RecommendJobsResponse(
        resume_id=result["resume_id"],
        top_k=result["top_k"],
        candidate_job_count=result["candidate_job_count"],
        items=result["items"],
    )
