from typing import Any

from pydantic import BaseModel, Field


class _AgentBaseRequest(BaseModel):
    """Agent 工具请求基类：resume_id + job_id 通过全局ID或用户本地编号指定。"""
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


# ── Copilot Pipeline ──

class CopilotRunRequest(BaseModel):
    """Copilot Pipeline 执行请求。"""
    goal: str = Field(..., min_length=1, description="用户的目标描述，如'帮我全面备战字节跳动后端岗'")
    resume_id: int | None = Field(default=None, description="简历 ID（全局 ID），如果知道的话")
    job_id: int | None = Field(default=None, description="岗位 ID（全局 ID），如果知道的话")
    personal_info: str | None = Field(
        default=None,
        description="自由文本输入的个人信息（技能/经历/项目/学历等）。无简历时使用此字段代替 resume_id。",
    )
    tools: list[str] | None = Field(
        default=None,
        description="指定要执行的工具列表，如 ['match_analyze', 'optimize_resume']。不传默认全跑。",
    )
    mode: str | None = Field(
        default=None,
        description="执行模式: 'fast'(直通) / 'react'(单Agent) / 'coordinator'(多Agent协作)。不传自动选择。",
    )


class CopilotStepResult(BaseModel):
    """单个步骤的执行结果。"""
    tool: str
    task_id: int | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class CopilotRunResponse(BaseModel):
    """Copilot Pipeline 执行结果（非流式摘要）。"""
    summary: str
    steps: list[CopilotStepResult] = Field(default_factory=list)
    executed_tools: list[str] = Field(default_factory=list)
    task_ids: list[int] = Field(default_factory=list)
