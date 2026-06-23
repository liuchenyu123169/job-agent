from langgraph.graph import END, START, StateGraph

from app.workflows.common import (
    _trace_node,
    build_generate_resume_prompt_node,
    llm_generate_resume_node_async,
    load_job_node,
    load_or_prepare_resume_node,
    parse_generated_resume_node,
    route_after_job_for_generate,
    route_after_resume_load,
    save_generate_resume_task_node,
)
from app.workflows.state import AgentAnalyzeState

_generate_async = StateGraph(AgentAnalyzeState)
_generate_async.add_node("load_or_prepare_resume", _trace_node("load_or_prepare_resume", load_or_prepare_resume_node))
_generate_async.add_node("load_job", _trace_node("load_job", load_job_node))
_generate_async.add_node("build_generate_resume_prompt", _trace_node("build_generate_resume_prompt", build_generate_resume_prompt_node))
_generate_async.add_node("llm_generate_resume", llm_generate_resume_node_async)
_generate_async.add_node("parse_generated_resume", _trace_node("parse_generated_resume", parse_generated_resume_node))
_generate_async.add_node("save_generate_resume_task", _trace_node("save_generate_resume_task", save_generate_resume_task_node))
_generate_async.add_edge(START, "load_or_prepare_resume")
_generate_async.add_conditional_edges("load_or_prepare_resume", route_after_resume_load, {"load_job": "load_job", END: END})
_generate_async.add_conditional_edges("load_job", route_after_job_for_generate, {"build_generate_resume_prompt": "build_generate_resume_prompt", END: END})
_generate_async.add_edge("build_generate_resume_prompt", "llm_generate_resume")
_generate_async.add_edge("llm_generate_resume", "parse_generated_resume")
_generate_async.add_edge("parse_generated_resume", "save_generate_resume_task")
_generate_async.add_edge("save_generate_resume_task", END)
generate_resume_graph = _generate_async.compile()

__all__ = ["generate_resume_graph"]
