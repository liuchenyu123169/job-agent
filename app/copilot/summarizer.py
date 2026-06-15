"""结果汇总器 — 将 Pipeline 执行结果整理为结构化报告。"""

from typing import Any

from app.copilot.state import PipelineContext


def summarize_result(
    context: PipelineContext,
    final_message: str = "",
) -> dict[str, Any]:
    """根据 Pipeline 执行上下文生成最终报告。

    Args:
        context: 累积的 Pipeline 上下文
        final_message: LLM 最终给出的文字总结

    Returns:
        结构化报告字典，包含执行摘要、各步骤结果和任务 ID 列表
    """
    steps: list[dict[str, Any]] = []
    for tool_name in context.executed_tools:
        step_result = context.tool_results.get(tool_name, {})
        step_summary = _summarize_step(tool_name, step_result)
        steps.append(step_summary)

    return {
        "summary": final_message or "任务执行完毕",
        "steps": steps,
        "executed_tools": context.executed_tools,
        "task_ids": context.task_ids,
        "resume_id": context.resume_id,
        "job_id": context.job_id,
    }


def _summarize_step(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """对单个工具的执行结果生成精简摘要。"""
    base = {"tool": tool_name, "task_id": result.get("task_id")}

    if tool_name == "match_analyze":
        analysis = result.get("analysis") or {}
        base["match_score"] = analysis.get("match_score")
        base["advantages_count"] = len(analysis.get("advantages") or [])
        base["weaknesses_count"] = len(analysis.get("weaknesses") or [])
    elif tool_name == "optimize_resume":
        optimization = result.get("optimization") or {}
        base["has_skill_keywords"] = bool(optimization.get("skill_keywords"))
        base["has_rewrite_suggestions"] = bool(optimization.get("resume_rewrite_suggestions"))
    elif tool_name == "generate_interview_questions":
        questions = result.get("questions") or {}
        base["tech_count"] = len(questions.get("technical_questions") or [])
        base["project_count"] = len(questions.get("project_questions") or [])
        base["behavior_count"] = len(questions.get("behavior_questions") or [])
        base["risk_count"] = len(questions.get("risk_questions") or [])
    elif tool_name == "recommend_jobs":
        items = result.get("items") or []
        base["candidate_count"] = result.get("candidate_job_count", len(items))
        base["top_match_score"] = items[0]["match_score"] if items else None
    elif tool_name == "search_knowledge":
        base["hit_count"] = result.get("count", 0)
    elif tool_name in ("list_resumes", "list_jobs"):
        base["item_count"] = result.get("count", 0)

    return base
