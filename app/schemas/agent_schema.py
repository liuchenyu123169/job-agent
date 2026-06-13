from typing import Any

from pydantic import BaseModel


class AgentAnalyzeRequest(BaseModel):
    resume_id: int
    job_id: int


class AgentAnalyzeResponse(BaseModel):
    task_id: int
    analysis: dict[str, Any]


class AgentOptimizeResumeRequest(BaseModel):
    resume_id: int
    job_id: int


class AgentOptimizeResumeResponse(BaseModel):
    task_id: int
    optimization: dict[str, Any]
