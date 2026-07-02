from typing import Any

from pydantic import BaseModel, Field


class _AgentBaseRequest(BaseModel):
    """Base request for agent tools."""

    resume_id: int | None = None
    local_resume_id: int | None = None
    job_id: int | None = None
    local_job_id: int | None = None


class AgentAnalyzeRequest(_AgentBaseRequest):
    pass


class AgentOptimizeResumeRequest(_AgentBaseRequest):
    pass


class AgentGenerateInterviewQuestionsRequest(_AgentBaseRequest):
    enable_rag: bool = True


class AgentAnalyzeResponse(BaseModel):
    task_id: int
    analysis: dict[str, Any]


class AgentOptimizeResumeResponse(BaseModel):
    task_id: int
    optimization: dict[str, Any]


class AgentGenerateInterviewQuestionsResponse(BaseModel):
    task_id: int
    questions: dict[str, Any]


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


class CopilotRunRequest(BaseModel):
    """Streaming copilot request."""

    goal: str = Field(..., min_length=1, description="用户的任务目标描述")
    resume_id: int | None = Field(default=None, description="全局简历 ID")
    job_id: int | None = Field(default=None, description="全局岗位 ID")
    personal_info: str | None = Field(
        default=None,
        description="无简历时可直接传入的个人信息文本",
    )
    extra_context: str | None = Field(
        default=None,
        description="补充上下文，如面试复盘、外部备注、多段 JD 文本等",
    )
    tools: list[str] | None = Field(
        default=None,
        description="可选，指定要执行的工具列表",
    )
    session_id: int | None = Field(
        default=None,
        description="可选，延续已有会话",
    )
    mode: str | None = Field(
        default=None,
        description="可选，兼容历史调用的执行模式字段",
    )


class CopilotStepResult(BaseModel):
    """Single step result."""

    tool: str
    task_id: int | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class CopilotRunResponse(BaseModel):
    """Non-streaming response summary."""

    summary: str
    steps: list[CopilotStepResult] = Field(default_factory=list)
    executed_tools: list[str] = Field(default_factory=list)
    task_ids: list[int] = Field(default_factory=list)
