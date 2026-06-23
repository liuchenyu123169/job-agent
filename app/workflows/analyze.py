from langgraph.graph import END, START, StateGraph

from app.workflows.common import (
    _trace_node,
    build_prompt_node,
    llm_analyze_node_async,
    load_job_node,
    load_resume_node,
    parse_result_node,
    route_after_job,
    route_on_error,
    save_task_node,
)
from app.workflows.state import AgentAnalyzeState

_analyze_async = StateGraph(AgentAnalyzeState)
_analyze_async.add_node("load_resume", _trace_node("load_resume", load_resume_node))
_analyze_async.add_node("load_job", _trace_node("load_job", load_job_node))
_analyze_async.add_node("build_prompt", _trace_node("build_prompt", build_prompt_node))
_analyze_async.add_node("llm_analyze", llm_analyze_node_async)
_analyze_async.add_node("parse_result", _trace_node("parse_result", parse_result_node))
_analyze_async.add_node("save_task", _trace_node("save_task", save_task_node))
_analyze_async.add_edge(START, "load_resume")
_analyze_async.add_conditional_edges("load_resume", route_on_error, {"load_job": "load_job", END: END})
_analyze_async.add_conditional_edges("load_job", route_after_job, {"build_prompt": "build_prompt", END: END})
_analyze_async.add_edge("build_prompt", "llm_analyze")
_analyze_async.add_edge("llm_analyze", "parse_result")
_analyze_async.add_edge("parse_result", "save_task")
_analyze_async.add_edge("save_task", END)
analyze_graph = _analyze_async.compile()

__all__ = ["analyze_graph"]
