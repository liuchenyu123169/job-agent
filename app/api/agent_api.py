from fastapi import APIRouter, HTTPException
from fastapi import Depends

from app.api.deps import get_current_user
from app.agent.recommend import recommend_jobs_for_resume
from app.agent.workflow import run_interview_questions_workflow
from app.agent.workflow import run_analyze_workflow, run_optimize_resume_workflow
from app.db.crud import resolve_job_for_user, resolve_resume_for_user
from app.schemas.agent_schema import (
    AgentAnalyzeRequest,
    AgentAnalyzeResponse,
    AgentOptimizeResumeRequest,
    AgentOptimizeResumeResponse,
    RecommendJobsRequest,
    RecommendJobsResponse,
)
from app.schemas.agent_schema import AgentGenerateInterviewQuestionsResponse,AgentGenerateInterviewQuestionsRequest

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


def _resolve_job_id(
    user_id: int,
    job_id: int | None,
    local_job_id: int | None,
) -> int | None:
    job = resolve_job_for_user(user_id=user_id, job_id=job_id, local_job_id=local_job_id)
    if job is None:
        return None
    return int(job["id"])


@router.post("/analyze", response_model=AgentAnalyzeResponse)
def analyze_match(
    payload: AgentAnalyzeRequest,
    current_user: dict = Depends(get_current_user),
) -> AgentAnalyzeResponse:
    user_id = int(current_user["id"])
    resolved_resume_id = _resolve_resume_id(user_id, payload.resume_id, payload.local_resume_id)
    if resolved_resume_id is None:
        raise HTTPException(status_code=404, detail="简历未找到")
    resolved_job_id = _resolve_job_id(user_id, payload.job_id, payload.local_job_id)
    if resolved_job_id is None:
        raise HTTPException(status_code=404, detail="岗位未找到")
    result = run_analyze_workflow(resolved_resume_id, resolved_job_id, user_id=user_id)

    if result["error_msg"] == "简历未找到":
        raise HTTPException(status_code=404, detail="简历未找到")
    if result["error_msg"] == "岗位未找到":
        raise HTTPException(status_code=404, detail="岗位未找到")
    return AgentAnalyzeResponse(task_id=result["task_id"], analysis=result["analysis"])


@router.post("/optimize-resume", response_model=AgentOptimizeResumeResponse)
def optimize_resume(
    payload: AgentOptimizeResumeRequest,
    current_user: dict = Depends(get_current_user),
) -> AgentOptimizeResumeResponse:
    user_id = int(current_user["id"])
    resolved_resume_id = _resolve_resume_id(user_id, payload.resume_id, payload.local_resume_id)
    if resolved_resume_id is None:
        raise HTTPException(status_code=404, detail="简历未找到")
    resolved_job_id = _resolve_job_id(user_id, payload.job_id, payload.local_job_id)
    if resolved_job_id is None:
        raise HTTPException(status_code=404, detail="岗位未找到")
    result = run_optimize_resume_workflow(
        resolved_resume_id,
        resolved_job_id,
        user_id=user_id,
    )

    if result["error_msg"] == "简历未找到":
        raise HTTPException(status_code=404, detail="简历未找到")
    if result["error_msg"] == "岗位未找到":
        raise HTTPException(status_code=404, detail="岗位未找到")
    return AgentOptimizeResumeResponse(
        task_id=result["task_id"],
        optimization=result["optimization"],
    )

@router.post("/generate-interview-questions", response_model=AgentGenerateInterviewQuestionsResponse)
def generate_interview_questions(
    payload: AgentGenerateInterviewQuestionsRequest,
    current_user: dict = Depends(get_current_user),
) -> AgentGenerateInterviewQuestionsResponse:
    user_id = int(current_user["id"])
    resolved_resume_id = _resolve_resume_id(user_id, payload.resume_id, payload.local_resume_id)
    if resolved_resume_id is None:
        raise HTTPException(status_code=404, detail="简历未找到")
    resolved_job_id = _resolve_job_id(user_id, payload.job_id, payload.local_job_id)
    if resolved_job_id is None:
        raise HTTPException(status_code=404, detail="岗位未找到")
    result = run_interview_questions_workflow(
        resolved_resume_id,
        resolved_job_id,
        user_id=user_id,
        enable_rag=payload.enable_rag,
    )

    if result["error_msg"] == "简历未找到":
        raise HTTPException(status_code=404, detail="简历未找到")
    if result["error_msg"] == "岗位未找到":
        raise HTTPException(status_code=404, detail="岗位未找到")
    return AgentGenerateInterviewQuestionsResponse(
        task_id=result["task_id"],
        questions=result["interview_questions"]
    )


@router.post("/recommend-jobs", response_model=RecommendJobsResponse)
def recommend_jobs(
    payload: RecommendJobsRequest,
    current_user: dict = Depends(get_current_user),
) -> RecommendJobsResponse:
    user_id = int(current_user["id"])
    resolved_resume_id = _resolve_resume_id(user_id, payload.resume_id, payload.local_resume_id)
    if resolved_resume_id is None:
        raise HTTPException(status_code=404, detail="简历未找到")
    result = recommend_jobs_for_resume(
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
