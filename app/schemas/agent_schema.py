from typing import Any

from pydantic import BaseModel, Field


class AgentAnalyzeRequest(BaseModel):
    resume_id: int | None = None
    local_resume_id: int | None = None
    job_id: int | None = None
    local_job_id: int | None = None


class AgentAnalyzeResponse(BaseModel):
    task_id: int
    analysis: dict[str, Any]


class AgentOptimizeResumeRequest(BaseModel):
    resume_id: int | None = None
    local_resume_id: int | None = None
    job_id: int | None = None
    local_job_id: int | None = None


class AgentOptimizeResumeResponse(BaseModel):
    task_id: int
    optimization: dict[str, Any]

class AgentGenerateInterviewQuestionsRequest(BaseModel):
    resume_id: int | None = None
    local_resume_id: int | None = None
    job_id: int | None = None
    local_job_id: int | None = None
    enable_rag: bool = True

class AgentGenerateInterviewQuestionsResponse(BaseModel):
    task_id: int
    questions: dict


class RecommendJobsRequest(BaseModel):
    resume_id: int | None = None
    local_resume_id: int | None = None
    top_k: int = Field(default=5, ge=1, le=10)
    max_jobs: int = Field(default=10, ge=1, le=20)


class RecommendJobItem(BaseModel):
    job_id: int
    local_job_id: int | None = None
    company: str | None = None
    title: str | None = None
    match_score: int
    match_reason: str = ""
    advantages: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class RecommendJobsResponse(BaseModel):
    resume_id: int
    top_k: int
    candidate_job_count: int
    items: list[RecommendJobItem]
