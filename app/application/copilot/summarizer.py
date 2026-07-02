"""Result summarizer — unified report generation for all paths."""

from typing import Any

from app.shared.state import PipelineContext
from app.tools.output_schema import normalize_tool_output


def summarize_result(
    context: PipelineContext,
    final_message: str = "",
    task_type: str = "",
    expected_output_shape: str = "",
) -> dict[str, Any]:
    """Build a structured report using the unified ReportFormatter.

    Phase 2 Round A: 接受 task_type 和 expected_output_shape（优先级：
    显式参数 > context 字段）。Round B 将传给 format_report 做答案模板选择。
    """
    from app.application.copilot.report_formatter import format_report

    steps: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []

    for tool_name in context.executed_tools:
        raw = context.tool_results.get(tool_name, {})
        norm = normalize_tool_output(tool_name, raw)
        outputs.append(norm)
        step_summary = _summarize_step(tool_name, norm)
        steps.append(step_summary)

    goal = context.goal or "任务报告"
    effective_task_type = task_type or context.task_type
    effective_output_shape = expected_output_shape or context.expected_output_shape
    summary = final_message or format_report(
        goal, outputs,
        task_type=effective_task_type,
        expected_output_shape=effective_output_shape,
        context={
            "goal": goal,
            "task_type": effective_task_type,
            "expected_output_shape": effective_output_shape,
        },
    )

    result: dict[str, Any] = {
        "summary": summary,
        "steps": steps,
        "executed_tools": context.executed_tools,
        "task_ids": context.task_ids,
        "resume_id": context.resume_id,
        "job_id": context.job_id,
    }

    # Phase 2 Round A: 携带 task_type 和 output_shape（供 Round B 使用）
    effective_task_type = task_type or context.task_type
    effective_output_shape = expected_output_shape or context.expected_output_shape
    if effective_task_type:
        result["task_type"] = effective_task_type
    if effective_output_shape:
        result["expected_output_shape"] = effective_output_shape

    return result


def _summarize_step(tool_name: str, norm: dict[str, Any]) -> dict[str, Any]:
    """Build step summary from normalized tool output."""
    base: dict[str, Any] = {
        "tool": tool_name,
        "task_id": norm.get("task_id"),
        "artifact_type": norm.get("artifact_type"),
    }

    text = norm.get("text", "")
    if text and len(text) > 10:
        base["text"] = text
        base["text_preview"] = text[:200]
        base["text_length"] = len(text)

    meta = norm.get("meta", {})
    if meta:
        base["meta"] = meta
        if "match_score" in meta:
            base["match_score"] = meta["match_score"]
        if "count" in meta:
            base["candidate_count"] = meta["count"]

    content = norm.get("content", {})
    if content:
        questions = content.get("questions")
        if isinstance(questions, dict):
            tech = len(questions.get("technical_questions") or [])
            proj = len(questions.get("project_questions") or [])
            base["tech_count"] = tech
            base["project_count"] = proj
        items = content.get("items")
        if isinstance(items, list):
            base["candidate_count"] = len(items)

    return base
