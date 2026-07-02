"""Normalized output schema for all tools."""

import re
from typing import Any

ARTIFACT_MATCH_ANALYSIS = "match_analysis"
ARTIFACT_RESUME_OPTIMIZATION = "resume_optimization"
ARTIFACT_INTERVIEW_QUESTIONS = "interview_questions"
ARTIFACT_GENERATED_RESUME = "generated_resume"
ARTIFACT_JOB_RECOMMENDATIONS = "job_recommendations"
ARTIFACT_ITEM_LIST = "item_list"
ARTIFACT_KNOWLEDGE_SEARCH = "knowledge_search"
ARTIFACT_TASK_DETAIL = "task_detail"

TOOL_ARTIFACT_MAP: dict[str, str] = {
    # 原子工具
    "match_analyze": ARTIFACT_MATCH_ANALYSIS,
    "optimize_resume": ARTIFACT_RESUME_OPTIMIZATION,
    "generate_interview_questions": ARTIFACT_INTERVIEW_QUESTIONS,
    "generate_resume": ARTIFACT_GENERATED_RESUME,
    "recommend_jobs": ARTIFACT_JOB_RECOMMENDATIONS,
    "list_resumes": ARTIFACT_ITEM_LIST,
    "list_jobs": ARTIFACT_ITEM_LIST,
    "search_knowledge": ARTIFACT_KNOWLEDGE_SEARCH,
    "get_task": ARTIFACT_TASK_DETAIL,
    "public_search": ARTIFACT_KNOWLEDGE_SEARCH,
    "fetch_job_page": ARTIFACT_TASK_DETAIL,
    # 子 Agent（兼容旧路径）
    "resume_agent": ARTIFACT_MATCH_ANALYSIS,
    "interview_agent": ARTIFACT_INTERVIEW_QUESTIONS,
    "search_agent": ARTIFACT_JOB_RECOMMENDATIONS,
}


def normalize_tool_output(tool_name: str, raw: dict[str, Any]) -> dict[str, Any]:
    artifact_type = TOOL_ARTIFACT_MAP.get(tool_name, "generic")
    task_id = raw.get("task_id")

    # 收集所有文本字段（支持 agent 返回多个文本块）
    text_parts: list[str] = []
    for key in ("text", "analysis_text", "optimization_text", "questions_text", "generated_resume"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            text_parts.append(val.strip())
    # 兼容嵌套结构
    if not text_parts:
        for key in ("analysis", "questions", "optimization"):
            val = raw.get(key)
            if isinstance(val, dict):
                t = val.get("text", "")
                if isinstance(t, str) and t.strip():
                    text_parts.append(t.strip())
            elif isinstance(val, str) and val.strip():
                text_parts.append(val.strip())
    text = "\n\n".join(text_parts)

    content: dict[str, Any] = {}
    for key in ("analysis", "questions", "optimization", "items", "resumes", "jobs", "task"):
        value = raw.get(key)
        if value is not None:
            content[key] = value

    meta: dict[str, Any] = {}
    for key in ("count", "candidate_job_count", "match_score", "tech_count", "project_count"):
        value = raw.get(key)
        if value is not None:
            meta[key] = value

    analysis = raw.get("analysis")
    if isinstance(analysis, dict):
        score = analysis.get("match_score")
        if score is not None:
            meta["match_score"] = score
    elif isinstance(analysis, str):
        match = re.search(r"(\d{1,3})\s*(?:分|score)?", analysis)
        if match:
            meta["match_score"] = int(match.group(1))

    return {
        "task_id": task_id,
        "artifact_type": artifact_type,
        "content": content,
        "text": text,
        "meta": meta,
    }


def get_display_text(normalized: dict[str, Any]) -> str:
    return str(normalized.get("text") or "")
