from langgraph.graph import END, START, StateGraph

from app.application.workflows.common import (
    _trace_node,
    build_optimize_prompt_node,
    llm_optimize_node_async,
    load_job_node,
    load_resume_node,
    parse_optimization_node,
    route_after_job_for_optimize,
    route_on_error,
    save_optimize_task_node,
)
from app.application.workflows.state import AgentAnalyzeState

_optimize_async = StateGraph(AgentAnalyzeState)
_optimize_async.add_node("load_resume", _trace_node("load_resume", load_resume_node))
_optimize_async.add_node("load_job", _trace_node("load_job", load_job_node))
_optimize_async.add_node("build_optimize_prompt", _trace_node("build_optimize_prompt", build_optimize_prompt_node))
_optimize_async.add_node("llm_optimize", llm_optimize_node_async)
_optimize_async.add_node("parse_optimization", _trace_node("parse_optimization", parse_optimization_node))
_optimize_async.add_node("save_optimize_task", _trace_node("save_optimize_task", save_optimize_task_node))
_optimize_async.add_edge(START, "load_resume")
_optimize_async.add_conditional_edges("load_resume", route_on_error, {"load_job": "load_job", END: END})
_optimize_async.add_conditional_edges("load_job", route_after_job_for_optimize, {"build_optimize_prompt": "build_optimize_prompt", END: END})
_optimize_async.add_edge("build_optimize_prompt", "llm_optimize")
_optimize_async.add_edge("llm_optimize", "parse_optimization")
_optimize_async.add_edge("parse_optimization", "save_optimize_task")
_optimize_async.add_edge("save_optimize_task", END)
optimize_resume_graph = _optimize_async.compile()

__all__ = ["optimize_resume_graph"]
