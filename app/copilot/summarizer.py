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

        # 同时拼装可读文本摘要（单次遍历）
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


# ── 各工具的摘要提取（结构化 + 文本） ──
# 注意：这里按数据结构检测而非按 tool_name 匹配。
# 因为在 direct agent 路径中，tool_name 是 agent 名（如 "resume_agent"）而非工具名（如 "match_analyze"）。

def _summarize_step(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """对单个工具/Agent 的执行结果生成结构化摘要。

    除计算元数据外，还保留原始数据字段（供前端重建 step card）。
    """
    base: dict[str, Any] = {"tool": tool_name, "task_id": result.get("task_id")}

    # ── 按数据结构检测结果类型 ──
    analysis = result.get("analysis") or {}
    optimization = result.get("optimization") or {}
    questions = result.get("questions") or {}
    generated_resume = result.get("generated_resume") or ""
    items = result.get("items") or []
    knowledge_count = result.get("count") or result.get("knowledge_count")

    if analysis:
        base["match_score"] = analysis.get("match_score")
        base["advantages_count"] = len(analysis.get("advantages") or [])
        base["weaknesses_count"] = len(analysis.get("weaknesses") or [])
        base["analysis"] = analysis  # 保留原始数据供前端重建

    if optimization:
        base["has_skill_keywords"] = bool(optimization.get("skill_keywords"))
        base["has_rewrite_suggestions"] = bool(optimization.get("resume_rewrite_suggestions"))
        base["optimization"] = optimization

    if questions:
        base["tech_count"] = len(questions.get("technical_questions") or [])
        base["project_count"] = len(questions.get("project_questions") or [])
        base["behavior_count"] = len(questions.get("behavior_questions") or [])
        base["risk_count"] = len(questions.get("risk_questions") or [])
        base["questions"] = questions

    if generated_resume:
        base["resume_length"] = len(generated_resume)
        base["resume_preview"] = generated_resume[:200]
        base["generated_resume"] = generated_resume

    if items:
        base["candidate_count"] = result.get("candidate_job_count", len(items))
        base["top_match_score"] = items[0]["match_score"] if items else None
        base["items"] = items

    if knowledge_count:
        base["hit_count"] = knowledge_count

    return base


def _step_text(tool_name: str, data: dict[str, Any]) -> str | None:
    """从单个工具/Agent 结果提取一行可读文本摘要（供 SSE final 事件使用）。

    按数据内容检测，不按工具名称匹配。
    """
    # ── 匹配分析 ──
    analysis = data.get("analysis") or {}
    if analysis.get("match_score") is not None:
        return f"匹配度 {analysis['match_score']} 分"

    # ── 简历优化 ──
    optimization = data.get("optimization") or {}
    if optimization.get("summary"):
        return f"简历优化：{str(optimization['summary'])[:80]}"

    # ── 面试题 ──
    questions = data.get("questions") or {}
    if questions:
        tech = len(questions.get("technical_questions") or [])
        proj = len(questions.get("project_questions") or [])
        behav = len(questions.get("behavior_questions") or [])
        risk = len(questions.get("risk_questions") or [])
        total = tech + proj + behav + risk
        if total:
            return f"面试题 {total} 道（技术{tech}/项目{proj}）"

    # ── 岗位推荐 ──
    items = data.get("items") or []
    if items:
        return f"推荐 {len(items)} 个岗位"

    # ── 简历生成 ──
    generated_resume = data.get("generated_resume") or ""
    if generated_resume:
        lines = generated_resume.strip().split("\n")
        title_line = next((l.strip("# ").strip() for l in lines if l.strip()), "")
        return f"简历已生成：{title_line[:80]}" if title_line else f"简历已生成（{len(generated_resume)} 字符）"

    # ── 知识检索 ──
    count = data.get("count") or data.get("knowledge_count")
    if count:
        return f"检索到 {count} 条知识"

    # ── 列表查询 ──
    if data.get("count") is not None and data.get("items") is not None:
        return f"查询到 {data['count']} 条记录"

    return None
