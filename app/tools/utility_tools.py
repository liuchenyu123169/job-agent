"""辅助工具 — 知识库检索、简历/岗位列表查询、任务查询。"""

import logging

from app.db.crud import (
    get_task_by_id,
    list_jobs_for_user,
    list_resumes_for_user,
)
from app.rag.rag_service import search_knowledge
from app.tools.base import ToolDefinition, ToolResult
from app.tools.registry import tool_registry

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  search_knowledge — RAG 知识库检索
# ═══════════════════════════════════════════════════════════════

SEARCH_KNOWLEDGE_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "检索查询文本，例如 'Java 多线程面试题'",
        },
        "top_k": {
            "type": "integer",
            "description": "返回的知识片段数量，默认为 5",
            "default": 5,
        },
    },
    "required": ["query"],
}


async def search_knowledge_execute(query: str, top_k: int = 5, **kwargs) -> ToolResult:
    """在 RAG 知识库中检索相关知识片段。"""
    logger.info("[search_knowledge] query=%s top_k=%s", query, top_k)
    try:
        items = search_knowledge(query=str(query), top_k=int(top_k))
        return ToolResult.ok({"items": items, "count": len(items)})
    except Exception as exc:
        logger.error("[search_knowledge] failed: %s", exc)
        return ToolResult.fail(str(exc))


# ═══════════════════════════════════════════════════════════════
#  list_resumes — 简历列表
# ═══════════════════════════════════════════════════════════════

LIST_RESUMES_PARAMETERS: dict = {
    "type": "object",
    "properties": {},
}


async def list_resumes_execute(user_id: int, **kwargs) -> ToolResult:
    """列出当前用户的所有简历。"""
    logger.info("[list_resumes] user_id=%s", user_id)
    try:
        items = list_resumes_for_user(user_id=int(user_id))
        return ToolResult.ok({"resumes": items, "count": len(items)})
    except Exception as exc:
        logger.error("[list_resumes] failed: %s", exc)
        return ToolResult.fail(str(exc))


# ═══════════════════════════════════════════════════════════════
#  list_jobs — 岗位列表
# ═══════════════════════════════════════════════════════════════

LIST_JOBS_PARAMETERS: dict = {
    "type": "object",
    "properties": {},
}


async def list_jobs_execute(user_id: int, **kwargs) -> ToolResult:
    """列出当前用户的所有岗位。"""
    logger.info("[list_jobs] user_id=%s", user_id)
    try:
        items = list_jobs_for_user(user_id=int(user_id), limit=100)
        return ToolResult.ok({"jobs": items, "count": len(items)})
    except Exception as exc:
        logger.error("[list_jobs] failed: %s", exc)
        return ToolResult.fail(str(exc))


# ═══════════════════════════════════════════════════════════════
#  get_task — 任务详情查询
# ═══════════════════════════════════════════════════════════════

GET_TASK_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "integer",
            "description": "任务 ID",
        },
    },
    "required": ["task_id"],
}


async def get_task_execute(task_id: int, user_id: int, **kwargs) -> ToolResult:
    """查询指定任务的详情和结果。"""
    logger.info("[get_task] task_id=%s user_id=%s", task_id, user_id)
    try:
        task = get_task_by_id(int(task_id), user_id=int(user_id))
        if task is None:
            return ToolResult.fail(f"Task {task_id} not found")
        return ToolResult.ok({"task": task})
    except Exception as exc:
        logger.error("[get_task] failed: %s", exc)
        return ToolResult.fail(str(exc))


# ═══════════════════════════════════════════════════════════════
#  注册所有辅助工具
# ═══════════════════════════════════════════════════════════════

search_knowledge_tool = ToolDefinition(
    name="search_knowledge",
    description="在 RAG 知识库中检索面试相关知识片段，可用于查找特定技术栈的面试题或知识点。",
    parameters=SEARCH_KNOWLEDGE_PARAMETERS,
    execute=search_knowledge_execute,
)

list_resumes_tool = ToolDefinition(
    name="list_resumes",
    description="列出当前用户上传的所有简历，当需要确认有哪些简历可用时调用。",
    parameters=LIST_RESUMES_PARAMETERS,
    execute=list_resumes_execute,
)

list_jobs_tool = ToolDefinition(
    name="list_jobs",
    description="列出当前用户创建的所有岗位描述，当需要确认有哪些岗位可分析时调用。",
    parameters=LIST_JOBS_PARAMETERS,
    execute=list_jobs_execute,
)

get_task_tool = ToolDefinition(
    name="get_task",
    description="根据任务 ID 查询任务的执行结果，用于查看历史分析任务的详细信息。",
    parameters=GET_TASK_PARAMETERS,
    execute=get_task_execute,
)

tool_registry.register(search_knowledge_tool)
tool_registry.register(list_resumes_tool)
tool_registry.register(list_jobs_tool)
tool_registry.register(get_task_tool)
