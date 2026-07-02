"""统一报告格式化器 — 按任务类型选择答案模板生成最终报告。

职责边界：
  - 只负责：选模板（get_template）、调用模板渲染、汇总结果
  - 不负责：渲染逻辑（answer_templates）、结构验收（TaskCompletionVerifier）

Phase 2 Round B: 入口从 artifact_type 路由改为 task_type 路由。
旧的 _format_* 方法保留为内部 helper，供兼容场景使用。
"""

from typing import Any


def format_report(
    goal: str,
    tool_outputs: list[dict[str, Any]],
    task_type: str = "",
    expected_output_shape: str = "",
    context: dict[str, Any] | None = None,
) -> str:
    """生成最终报告 — 按 task_type 选择答案模板。

    Args:
        goal: 用户原始目标
        tool_outputs: 标准化后的工具输出列表（normalize_tool_output 产物）
        task_type: Phase 2 任务类型（fact_lookup / comparison / ...），为空时回退到 artifact_type 逻辑
        expected_output_shape: 期望输出结构描述（传入模板供 render 参考）
        context: 额外上下文（verifier_scores、plan_steps、session_id 等）

    Returns:
        格式化的 Markdown 报告
    """
    # ── Phase 2: 按 task_type 路由到 AnswerTemplate ──
    if task_type:
        from app.application.copilot.answer_templates import get_template

        template = get_template(task_type)
        ctx = context or {}
        ctx.setdefault("task_type", task_type)
        ctx.setdefault("goal", goal)
        ctx.setdefault("expected_output_shape", expected_output_shape)

        # 1. 质量门
        gate = template.quality_gate(tool_outputs, ctx)
        if not gate.passed:
            # 质量门不通过 → 返回 fallback（结构化失败说明，非原始链接堆砌）
            return gate.fallback_message or template.fallback_reason(tool_outputs, ctx)

        # 2. 渲染
        return template.render(goal, tool_outputs, ctx)

    # ── 兼容路径：无 task_type 时回退到旧 artifact_type 逻辑 ──
    return _format_by_artifact_type(goal, tool_outputs)


# ═══════════════════════════════════════════════════════════════
# 兼容路径：无 task_type 时按 artifact_type 渲染
# ═══════════════════════════════════════════════════════════════

def _format_by_artifact_type(goal: str, tool_outputs: list[dict[str, Any]]) -> str:
    """旧逻辑：按 artifact_type 分组渲染。Phase 2 兼容兜底。"""
    from app.tools.output_schema import (
        ARTIFACT_GENERATED_RESUME, ARTIFACT_INTERVIEW_QUESTIONS,
        ARTIFACT_ITEM_LIST, ARTIFACT_JOB_RECOMMENDATIONS,
        ARTIFACT_KNOWLEDGE_SEARCH, ARTIFACT_MATCH_ANALYSIS,
        ARTIFACT_RESUME_OPTIMIZATION,
    )

    lines = [f"# {goal}", ""]

    match_outputs = [o for o in tool_outputs if o.get("artifact_type") == ARTIFACT_MATCH_ANALYSIS]
    optimize_outputs = [o for o in tool_outputs if o.get("artifact_type") == ARTIFACT_RESUME_OPTIMIZATION]
    interview_outputs = [o for o in tool_outputs if o.get("artifact_type") == ARTIFACT_INTERVIEW_QUESTIONS]
    search_outputs = [o for o in tool_outputs if o.get("artifact_type") == ARTIFACT_KNOWLEDGE_SEARCH]
    list_outputs = [o for o in tool_outputs if o.get("artifact_type") == ARTIFACT_ITEM_LIST]
    recommend_outputs = [o for o in tool_outputs if o.get("artifact_type") == ARTIFACT_JOB_RECOMMENDATIONS]
    resume_outputs = [o for o in tool_outputs if o.get("artifact_type") == ARTIFACT_GENERATED_RESUME]

    if len(match_outputs) >= 2:
        lines.extend(_format_comparison(match_outputs))
    elif len(match_outputs) == 1:
        lines.extend(_format_match(match_outputs[0]))
    if optimize_outputs:
        lines.extend(_format_optimize(optimize_outputs[0]))
    if interview_outputs:
        lines.extend(_format_interview(interview_outputs[0]))
    if search_outputs:
        lines.extend(_format_search(search_outputs[0]))
    if recommend_outputs:
        lines.extend(_format_recommend(recommend_outputs[0]))
    if resume_outputs:
        lines.extend(_format_resume(resume_outputs[0]))
    if list_outputs:
        lines.extend(_format_list(list_outputs[0]))

    if len(lines) <= 2:
        for out in tool_outputs:
            text = out.get("text", "")
            if text and len(text) > 10:
                lines.append("")
                lines.append(text)

    report = "\n".join(lines)
    if len(report.strip()) < 60:
        return f"# {goal}\n\n未能生成有效报告。建议补充更多信息（如指定具体公司、岗位或技术方向）后重试。"

    return report


# ═══════════════════════════════════════════════════════════════
# 各类型格式化方法（内部 helper，供兼容和模板内部使用）
# ═══════════════════════════════════════════════════════════════

def _format_match(output: dict) -> list[str]:
    """匹配分析 → 结构化的分数 + 优劣势 + 建议。"""
    lines = ["## 匹配分析", ""]
    text = output.get("text", "")

    # 尝试提取分数
    meta = output.get("meta", {})
    score = meta.get("match_score")
    if score is not None:
        lines.append(f"**总体匹配度: {score} 分**")
        lines.append("")

    # 如果 text 已经是格式化的 Markdown，直接使用
    if text:
        # 按段落拆分，保留结构
        sections = _split_markdown_sections(text)
        for title, body in sections:
            if title:
                lines.append(f"### {title}")
            if body:
                lines.append(body.strip())
            lines.append("")

    return lines


def _format_comparison(outputs: list[dict]) -> list[str]:
    """对比模式 → 横向比较表。"""
    lines = ["## 岗位对比", ""]

    # 分数对比表
    scores = []
    for i, out in enumerate(outputs, 1):
        meta = out.get("meta", {})
        s = meta.get("match_score", "N/A")
        scores.append((i, s))

    if scores:
        lines.append("| 岗位 | 匹配度 |")
        lines.append("|------|--------|")
        for idx, s in scores:
            lines.append(f"| 岗位 {idx} | {s} 分 |")
        lines.append("")

    # 各岗位详细分析
    for i, out in enumerate(outputs, 1):
        lines.append(f"### 岗位 {i}")
        text = out.get("text", "")
        if text:
            # 只取关键部分：优势、差距、建议
            sections = _split_markdown_sections(text)
            for title, body in sections:
                if title in ("匹配优势", "存在的差距", "提升建议", "优势", "差距", "建议"):
                    lines.append(f"**{title}**")
                    lines.append(body.strip()[:300])
                    lines.append("")

    # 综合建议
    if len(scores) >= 2 and all(isinstance(s[1], (int, float)) for s in scores):
        best = max(scores, key=lambda x: float(x[1]))
        lines.append(f"**推荐**: 优先投递岗位 {best[0]}（匹配度 {best[1]} 分）")

    return lines


def _format_optimize(output: dict) -> list[str]:
    """简历优化 → 核心建议摘要 + 全文。"""
    lines = ["## 简历优化建议", ""]
    text = output.get("text", "")
    if text:
        # 如果正文开头已有类似标题，跳过避免重复
        first_line = text.strip().split("\n")[0].strip("# *- ")
        if first_line in ("简历优化建议", "简历优化", "优化建议"):
            lines.append(text)
        else:
            lines.append(text)
    return lines


def _format_interview(output: dict) -> list[str]:
    """面试题 → 按类别整理。"""
    lines = ["## 面试题", ""]
    text = output.get("text", "")
    if text:
        # 面试题通常是 Markdown 列表，保持原样
        lines.append(text)
    return lines


def _format_search(output: dict) -> list[str]:
    """搜索结果 → 干净的列表，去掉版权噪音。

    Phase 1 质量门：如果 verifier_score < 50，不渲染链接列表，
    改为提示用户更换搜索词。
    """
    lines = ["## 搜索结果", ""]

    content = output.get("content", {})
    items = content.get("items", [])

    if not items:
        lines.append("未找到相关结果。")
        return lines

    # ── 质量门：verifier 评分 < 50 时拒止渲染链接列表 ──
    verifier_score = output.get("meta", {}).get("verifier_score")
    if verifier_score is not None and verifier_score < 50:
        query = content.get("query", output.get("meta", {}).get("query", ""))
        lines.append("搜索结果与您的问题关联度较低。建议：")
        lines.append("")
        lines.append("- 使用**更具体的关键词**重新搜索（如加上公司名、岗位名、技术栈）")
        if query:
            lines.append(f"- 尝试更换搜索词（当前搜索词：`{query}`）")
        lines.append("- 缩小搜索范围：指定具体公司、岗位或技术领域")
        return lines

    lines.append(f"共找到 **{len(items)}** 条相关信息：")
    lines.append("")

    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("name") or "无标题"
        url = item.get("url") or ""
        snippet = item.get("snippet") or item.get("summary") or ""

        # 有 URL 就做成超链接
        if url:
            lines.append(f"**{i}. [{title}]({url})**")
        else:
            lines.append(f"**{i}. {title}**")

        # 清洗 snippet：去版权、去招聘提示、截取有用部分
        clean = _clean_snippet(snippet)
        if clean:
            lines.append(f"  {clean[:250]}")
        lines.append("")

    return lines


def _format_recommend(output: dict) -> list[str]:
    """岗位推荐 → 排名列表。"""
    lines = ["## 推荐岗位", ""]
    text = output.get("text", "")
    if text:
        lines.append(text)
    return lines


def _format_resume(output: dict) -> list[str]:
    """生成的简历 → 全文。"""
    lines = ["## 定制简历", ""]
    text = output.get("text", "")
    if text:
        lines.append(text)
    return lines


def _format_list(output: dict) -> list[str]:
    """列表类结果 → 简洁列表。"""
    lines = ["## 资源列表", ""]
    text = output.get("text", "")
    if text:
        lines.append(text)
    return lines


# ═══════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════

def _split_markdown_sections(text: str) -> list[tuple[str, str]]:
    """将 Markdown 按 ## / ### 标题拆分为 (标题, 正文) 对。"""
    sections: list[tuple[str, str]] = []
    current_title = ""
    current_body: list[str] = []

    for line in text.split("\n"):
        if line.startswith("## "):
            if current_body or current_title:
                sections.append((current_title, "\n".join(current_body)))
            current_title = line.strip("# ").strip()
            current_body = []
        elif line.startswith("# "):
            if current_body or current_title:
                sections.append((current_title, "\n".join(current_body)))
            current_title = ""
            current_body = []
        else:
            current_body.append(line)

    if current_body or current_title:
        sections.append((current_title, "\n".join(current_body)))

    return sections


def _clean_snippet(snippet: str) -> str:
    """清洗 snippet，精准去掉版权声明、招聘提示等噪音片段。"""
    import re

    # 用正则去掉常见噪音模式
    noise_patterns = [
        r"版权声明[：:\s].*?[。；;]",
        r"【前言】",
        r"【版权[^】]*】",
        r"Copyright\s*©[^。]*[。]",
        r"本文内容由[^。]*[。]",
        r"原文出处[^。]*[。]",
        r"原文链接[^。]*[。]",
        r"转载请[^。]*[。]",
        r"\bCC\s+\d+\.\d+\s+BY[^ ]*",
        r"联系[^。]*?(?:举报|投诉)[^。]*[。]",
        r"警惕[^。]*?(?:骗|费)[^。]*[。]",
        r"收取[^。]*?(?:费用|押金|培训费|贷款)[^。]*[。]",
    ]

    result = snippet
    for pattern in noise_patterns:
        result = re.sub(pattern, "", result)

    # 去多余空白
    result = re.sub(r"\s+", " ", result).strip()

    return result
