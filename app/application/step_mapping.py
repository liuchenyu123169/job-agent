"""步骤到工具的映射 — Planner LLM 生成的 step["tool"] → tool_registry 工具名。

支持精确匹配和模糊子串匹配，确保 Planner 输出的一定程度"不规范"也能正确路由。
"""

import logging

logger = logging.getLogger(__name__)

# 精确映射表：Planner 步骤名 → tool_registry 工具名
STEP_TOOL_MAP: dict[str, str] = {
    "match_analyze": "match_analyze",
    "match_analysis": "match_analyze",
    "optimize_resume": "optimize_resume",
    "resume_optimization": "optimize_resume",
    "generate_resume": "generate_resume",
    "resume_generation": "generate_resume",
    "generate_interview_questions": "generate_interview_questions",
    "interview_questions": "generate_interview_questions",
    "recommend_jobs": "recommend_jobs",
    "job_recommendation": "recommend_jobs",
    "search_knowledge": "search_knowledge",
    "knowledge_search": "search_knowledge",
    "knowledge_query": "search_knowledge",
    "rag_search": "search_knowledge",
    "list_resumes": "list_resumes",
    "my_resumes": "list_resumes",
    "list_jobs": "list_jobs",
    "my_jobs": "list_jobs",
    "get_task": "get_task",
    "task_detail": "get_task",
    "task_query": "get_task",
    # ── 公开搜索 ──
    "public_search": "public_search",
    "web_search": "public_search",
    "company_search": "public_search",
    "internet_search": "public_search",
    "online_search": "public_search",
    # ── 岗位页面采集 ──
    "fetch_job_page": "fetch_job_page",
    "job_page_fetch": "fetch_job_page",
    "scrape_job": "fetch_job_page",
    "extract_job_page": "fetch_job_page",
    "fetch_job_url": "fetch_job_page",
}

# 工具名 → 默认参数列表（resume_id + job_id 由执行时注入）
_TOOL_DEFAULT_PARAMS: dict[str, dict] = {
    "generate_interview_questions": {"enable_rag": True},
    "recommend_jobs": {"top_k": 5},
}


def resolve(step_tool: str) -> tuple[str | None, dict]:
    """将 Planner 输出的步骤 tool 字段解析为实际工具名和默认参数。

    解析策略：
      1. 精确匹配 STEP_TOOL_MAP
      2. 子串模糊匹配（step_tool 包含已知工具名，或已知工具名包含 step_tool）
      3. 都不匹配 → (None, {})，调用方应标记步骤失败

    Args:
        step_tool: Planner 输出的工具标识符（可能是自然语言描述的）

    Returns:
        (tool_name, default_params) — tool_name 为 None 表示无法解析
    """
    if not step_tool:
        return None, {}

    key = step_tool.strip().lower()

    # 1. 精确匹配
    if key in STEP_TOOL_MAP:
        tool_name = STEP_TOOL_MAP[key]
        return tool_name, _TOOL_DEFAULT_PARAMS.get(tool_name, {})

    # 2. 子串模糊匹配
    for map_key, tool_name in STEP_TOOL_MAP.items():
        if key in map_key or map_key in key:
            logger.info("step_mapping: fuzzy match '%s' → %s (via '%s')", step_tool, tool_name, map_key)
            return tool_name, _TOOL_DEFAULT_PARAMS.get(tool_name, {})

    logger.warning("step_mapping: cannot resolve step tool '%s'", step_tool)
    return None, {}
