from typing import Any, TypedDict


class AgentAnalyzeState(TypedDict):
    resume_id: int
    job_id: int
    enable_rag: bool | None
    resume: dict[str, Any] | None
    job: dict[str, Any] | None
    knowledge_context: str | None
    knowledge_used: bool | None
    knowledge_count: int | None
    rag_queries: list[str] | None
    rag_hit_titles: list[str] | None
    rag_hit_sources: list[str] | None
    prompt: str | None
    raw_output: str | None
    analysis: dict[str, Any] | None
    optimization: dict[str, Any] | None
    interview_questions: dict[str, Any] | None
    task_id: int | None
    error_msg: str | None
