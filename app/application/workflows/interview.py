from langgraph.graph import END, START, StateGraph

from app.application.workflows.common import (
    _trace_node,
    build_interview_questions_prompt_node,
    llm_generate_questions_node_async,
    load_job_node,
    load_resume_node,
    parse_questions_node,
    retrieve_knowledge_node,
    route_after_job_for_interview,
    route_on_error,
    save_questions_task_node,
)
from app.application.workflows.state import AgentAnalyzeState

_interview_async = StateGraph(AgentAnalyzeState)
_interview_async.add_node("load_resume", _trace_node("load_resume", load_resume_node))
_interview_async.add_node("load_job", _trace_node("load_job", load_job_node))
_interview_async.add_node("retrieve_knowledge", _trace_node("retrieve_knowledge", retrieve_knowledge_node))
_interview_async.add_node("build_interview_questions_prompt", _trace_node("build_interview_questions_prompt", build_interview_questions_prompt_node))
_interview_async.add_node("llm_interview", llm_generate_questions_node_async)
_interview_async.add_node("parse_questions", _trace_node("parse_questions", parse_questions_node))
_interview_async.add_node("save_questions_task", _trace_node("save_questions_task", save_questions_task_node))
_interview_async.add_edge(START, "load_resume")
_interview_async.add_conditional_edges("load_resume", route_on_error, {"load_job": "load_job", END: END})
_interview_async.add_conditional_edges("load_job", route_after_job_for_interview, {"retrieve_knowledge": "retrieve_knowledge", END: END})
_interview_async.add_edge("retrieve_knowledge", "build_interview_questions_prompt")
_interview_async.add_edge("build_interview_questions_prompt", "llm_interview")
_interview_async.add_edge("llm_interview", "parse_questions")
_interview_async.add_edge("parse_questions", "save_questions_task")
_interview_async.add_edge("save_questions_task", END)
interview_graph = _interview_async.compile()

__all__ = ["interview_graph"]
