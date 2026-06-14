from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.common import parse_llm_json_output, read_prompt_template, save_success_task
from app.agent.state import AgentAnalyzeState
from app.core.llm import invoke_llm
from app.db.crud import get_job_by_id, get_resume_by_id


def load_resume_node(state: AgentAnalyzeState) -> dict[str, Any]:
    resume = get_resume_by_id(state["resume_id"])
    if resume is None:
        return {"error_msg": "Resume not found"}
    return {"resume": resume}


def load_job_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    job = get_job_by_id(state["job_id"])
    if job is None:
        return {"error_msg": "Job not found"}
    return {"job": job}


def build_prompt_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    prompt_template = read_prompt_template("match_analyze.txt")
    prompt = prompt_template.format(
        resume_content=state["resume"]["content"],
        job_jd=state["job"]["jd_text"],
    )
    return {"prompt": prompt}


def llm_analyze_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    raw_output = invoke_llm(state["prompt"])
    return {"raw_output": raw_output}


def parse_result_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    raw_output = state["raw_output"] or ""
    analysis = parse_llm_json_output(raw_output)
    return {"analysis": analysis}


def save_task_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    task_id = save_success_task(
        task_type="MATCH_ANALYZE",
        resume_id=state["resume_id"],
        job_id=state["job_id"],
        output_data=state["analysis"],
    )
    return {"task_id": task_id}


def build_optimize_prompt_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    prompt_template = read_prompt_template("resume_optimize.txt")
    prompt = prompt_template.format(
        resume_content=state["resume"]["content"],
        job_jd=state["job"]["jd_text"],
    )
    return {"prompt": prompt}


def llm_optimize_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    raw_output = invoke_llm(state["prompt"])
    return {"raw_output": raw_output}


def parse_optimization_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    raw_output = state["raw_output"] or ""
    optimization = parse_llm_json_output(raw_output)
    return {"optimization": optimization}


def save_optimize_task_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    task_id = save_success_task(
        task_type="RESUME_OPTIMIZE",
        resume_id=state["resume_id"],
        job_id=state["job_id"],
        output_data=state["optimization"],
    )
    return {"task_id": task_id}

def build_interview_questions_prompt_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    prompt_template = read_prompt_template("interview_questions.txt")
    prompt = prompt_template.format(
        resume_content=state["resume"]["content"],
        job_jd=state["job"]["jd_text"],
    )
    return {"prompt": prompt}

def llm_generate_questions_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    raw_output = invoke_llm(state["prompt"])
    return {"raw_output": raw_output}

def parse_questions_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    raw_output = state["raw_output"] or ""
    interview_questions = parse_llm_json_output(raw_output)
    return {"interview_questions": interview_questions}

def save_questions_task_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    task_id = save_success_task(
        task_type="INTERVIEW_QUESTIONS",
        resume_id=state["resume_id"],
        job_id=state["job_id"],
        output_data=state["interview_questions"],
    )
    return {"task_id": task_id}


def _route_on_error(state: AgentAnalyzeState) -> str:
    if state.get("error_msg"):
        return END
    return "load_job"


def _route_after_job(state: AgentAnalyzeState) -> str:
    if state.get("error_msg"):
        return END
    return "build_prompt"


def _route_after_job_for_optimize(state: AgentAnalyzeState) -> str:
    if state.get("error_msg"):
        return END
    return "build_optimize_prompt"

def _route_after_job_for_interview(state: AgentAnalyzeState) -> str:
    if state.get("error_msg"):
        return END
    return "build_interview_questions_prompt"


workflow = StateGraph(AgentAnalyzeState)
workflow.add_node("load_resume", load_resume_node)
workflow.add_node("load_job", load_job_node)
workflow.add_node("build_prompt", build_prompt_node)
workflow.add_node("llm_analyze", llm_analyze_node)
workflow.add_node("parse_result", parse_result_node)
workflow.add_node("save_task", save_task_node)
workflow.add_edge(START, "load_resume")
workflow.add_conditional_edges("load_resume", _route_on_error, ["load_job", END])
workflow.add_conditional_edges("load_job", _route_after_job, ["build_prompt", END])
workflow.add_edge("build_prompt", "llm_analyze")
workflow.add_edge("llm_analyze", "parse_result")
workflow.add_edge("parse_result", "save_task")
workflow.add_edge("save_task", END)

analyze_graph = workflow.compile()

optimize_workflow = StateGraph(AgentAnalyzeState)
optimize_workflow.add_node("load_resume", load_resume_node)
optimize_workflow.add_node("load_job", load_job_node)
optimize_workflow.add_node("build_optimize_prompt", build_optimize_prompt_node)
optimize_workflow.add_node("llm_optimize", llm_optimize_node)
optimize_workflow.add_node("parse_optimization", parse_optimization_node)
optimize_workflow.add_node("save_optimize_task", save_optimize_task_node)
optimize_workflow.add_edge(START, "load_resume")
optimize_workflow.add_conditional_edges("load_resume", _route_on_error, ["load_job", END])
optimize_workflow.add_conditional_edges( "load_job", _route_after_job_for_optimize,["build_optimize_prompt", END],)
optimize_workflow.add_edge("build_optimize_prompt", "llm_optimize")
optimize_workflow.add_edge("llm_optimize", "parse_optimization")
optimize_workflow.add_edge("parse_optimization", "save_optimize_task")
optimize_workflow.add_edge("save_optimize_task", END)

optimize_resume_graph = optimize_workflow.compile()

interview_workflow = StateGraph(AgentAnalyzeState)
interview_workflow.add_node("load_resume", load_resume_node)
interview_workflow.add_node("load_job", load_job_node)
interview_workflow.add_node("build_interview_questions_prompt", build_interview_questions_prompt_node)
interview_workflow.add_node("llm_interview", llm_generate_questions_node)
interview_workflow.add_node("parse_questions", parse_questions_node)
interview_workflow.add_node("save_questions_task", save_questions_task_node)
interview_workflow.add_edge(START, "load_resume")
interview_workflow.add_conditional_edges("load_resume", _route_on_error, ["load_job", END])
interview_workflow.add_conditional_edges("load_job", _route_after_job_for_interview, ["build_interview_questions_prompt", END])
interview_workflow.add_edge("build_interview_questions_prompt", "llm_interview")
interview_workflow.add_edge("llm_interview", "parse_questions")
interview_workflow.add_edge("parse_questions", "save_questions_task")
interview_workflow.add_edge("save_questions_task", END)

interview_graph = interview_workflow.compile()

def run_analyze_workflow(resume_id: int, job_id: int) -> dict[str, Any]:
    initial_state: AgentAnalyzeState = {
        "resume_id": resume_id,
        "job_id": job_id,
        "resume": None,
        "job": None,
        "prompt": None,
        "raw_output": None,
        "analysis": None,
        "optimization": None,
        "task_id": None,
        "error_msg": None,
    }
    final_state = analyze_graph.invoke(initial_state)
    return {
        "task_id": final_state.get("task_id"),
        "analysis": final_state.get("analysis"),
        "error_msg": final_state.get("error_msg"),
    }


def run_optimize_resume_workflow(resume_id: int, job_id: int) -> dict[str, Any]:
    initial_state: AgentAnalyzeState = {
        "resume_id": resume_id,
        "job_id": job_id,
        "resume": None,
        "job": None,
        "prompt": None,
        "raw_output": None,
        "analysis": None,
        "optimization": None,
        "task_id": None,
        "error_msg": None,
    }
    final_state = optimize_resume_graph.invoke(initial_state)
    return {
        "task_id": final_state.get("task_id"),
        "optimization": final_state.get("optimization"),
        "error_msg": final_state.get("error_msg"),
    }

def run_interview_questions_workflow(resume_id: int, job_id: int) -> dict[str, Any]:
    initial_state: AgentAnalyzeState = {
        "resume_id": resume_id,
        "job_id": job_id,
        "resume": None,
        "job": None,
        "prompt": None,
        "raw_output": None,
        "analysis": None,
        "optimization": None,
        "task_id": None,
        "error_msg": None,
    }
    final_state = interview_graph.invoke(initial_state)
    return {
        "task_id": final_state.get("task_id"),
        "interview_questions": final_state.get("interview_questions"),
        "error_msg": final_state.get("error_msg"),
    }
