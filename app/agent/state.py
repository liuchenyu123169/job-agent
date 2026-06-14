from typing import Any, TypedDict


class AgentAnalyzeState(TypedDict):
    resume_id: int
    job_id: int
    resume: dict[str, Any] | None
    job: dict[str, Any] | None
    prompt: str | None
    raw_output: str | None
    analysis: dict[str, Any] | None
    optimization: dict[str, Any] | None
    interview_questions: dict[str, Any] | None
    task_id: int | None
    error_msg: str | None
