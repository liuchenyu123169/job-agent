from typing import Any, TypedDict


class AgentAnalyzeState(TypedDict):
    user_id: int
    resume_id: int
    job_id: int
    enable_rag: bool | None
    personal_info: str | None
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
    analysis_text: str | None
    optimization: dict[str, Any] | None
    optimization_text: str | None
    interview_questions: dict[str, Any] | None
    questions_text: str | None
    generated_resume: str | None
    task_id: int | None
    error_msg: str | None
    trace_spans: list[dict] | None


def make_initial_state(user_id: int, resume_id: int, job_id: int, **overrides) -> AgentAnalyzeState:
    """工厂函数：构建 AgentAnalyzeState 初始值，所有可选字段默认为 None。"""
    state: AgentAnalyzeState = {
        "user_id": user_id,
        "resume_id": resume_id,
        "job_id": job_id,
        "enable_rag": None,
        "personal_info": None,
        "resume": None,
        "job": None,
        "knowledge_context": None,
        "knowledge_used": None,
        "knowledge_count": None,
        "rag_queries": None,
        "rag_hit_titles": None,
        "rag_hit_sources": None,
        "prompt": None,
        "raw_output": None,
        "analysis": None,
        "analysis_text": None,
        "optimization": None,
        "optimization_text": None,
        "interview_questions": None,
        "questions_text": None,
        "generated_resume": None,
        "task_id": None,
        "error_msg": None,
        "trace_spans": [],
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state
