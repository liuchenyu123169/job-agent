"""结果汇总器 — 将 Pipeline 执行结果整理为结构化报告，同时生成可读文本摘要。"""

from typing import Any

from app.copilot.state import PipelineContext


def summarize_result(
    context: PipelineContext,
    final_message: str = "",
) -> dict[str, Any]:
    """根据 Pipeline 执行上下文生成最终报告（单次遍历）。

    Args:
        context: 累积的 Pipeline 上下文
        final_message: LLM 最终给出的文字总结（为空时自动从工具结果拼装）

    Returns:
        结构化报告字典，包含执行摘要、各步骤结果和任务 ID 列表
    """
    steps: list[dict[str, Any]] = []
    text_parts: list[str] = []

    for tool_name in context.executed_tools:
        step_result = context.tool_results.get(tool_name, {})
        step_summary = _summarize_step(tool_name, step_result)
        steps.append(step_summary)

        # 同时拼装可读文本摘要
        part = _step_text(tool_name, step_result)
        if part:
            text_parts.append(part)

    return {
        "summary": final_message or (" | ".join(text_parts) if text_parts else "任务执行完毕"),
        "steps": steps,
        "executed_tools": context.executed_tools,
        "task_ids": context.task_ids,
        "resume_id": context.resume_id,
        "job_id": context.job_id,
    }


def _summarize_step(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """对单个工具/Agent 的执行结果生成结构化摘要。"""
    base: dict[str, Any] = {"tool": tool_name, "task_id": result.get("task_id")}

    # ── Markdown 文本字段（新格式） ──
    for key, label in [
        ("analysis_text", "analysis_text"),
        ("optimization_text", "optimization_text"),
        ("questions_text", "questions_text"),
        ("generated_resume", "generated_resume"),
    ]:
        val = result.get(key)
        if val and isinstance(val, str) and len(val) > 10:
            base[label] = val
            base[f"{label}_length"] = len(val)
            base[f"{label}_preview"] = val[:200]

    # ── 兼容旧 JSON 格式 ──
    analysis = result.get("analysis") or {}
    if analysis and isinstance(analysis, dict):
        base["match_score"] = analysis.get("match_score")
        base["analysis"] = analysis

    questions = result.get("questions") or {}
    if questions and isinstance(questions, dict):
        tech = len(questions.get("technical_questions") or [])
        proj = len(questions.get("project_questions") or [])
        base["tech_count"] = tech
        base["project_count"] = proj
        base["questions"] = questions

    items = result.get("items") or []
    if items:
        base["candidate_count"] = result.get("candidate_job_count", len(items))

    return base


def _step_text(tool_name: str, data: dict[str, Any]) -> str | None:
    """从单个工具/Agent 结果提取一行可读文本摘要。"""

    # ── Markdown 文本字段 ──
    for key, label in [
        ("analysis_text", "匹配分析"),
        ("optimization_text", "简历优化"),
        ("questions_text", "面试题"),
    ]:
        val = data.get(key)
        if val and isinstance(val, str) and len(val) > 10:
            # 取第一行有意义的内容
            first_line = val.strip().split("\n")[0].strip("# *-")
            return f"{label}：{first_line[:80]}"

    generated_resume = data.get("generated_resume") or ""
    if generated_resume:
        lines = generated_resume.strip().split("\n")
        title_line = next((l.strip("# ").strip() for l in lines if l.strip()), "")
        return f"简历已生成：{title_line[:80]}" if title_line else f"简历已生成（{len(generated_resume)} 字符）"

    # ── 兼容旧 JSON 格式 ──
    analysis = data.get("analysis") or {}
    if analysis.get("match_score") is not None:
        return f"匹配度 {analysis['match_score']} 分"

    questions = data.get("questions") or {}
    if questions:
        tech = len(questions.get("technical_questions") or [])
        proj = len(questions.get("project_questions") or [])
        total = tech + proj
        if total:
            return f"面试题 {total} 道（技术{tech}/项目{proj}）"

    items = data.get("items") or []
    if items:
        return f"推荐 {len(items)} 个岗位"

    count = data.get("count") or data.get("knowledge_count")
    if count:
        return f"检索到 {count} 条知识"

    return None
