"""公开搜索工具 — 调用博查等外部搜索引擎，获取公开信息。"""

import logging

from app.tools.base import InputRequirements, ToolDefinition, ToolResult
from app.tools.registry import tool_registry

logger = logging.getLogger(__name__)

PUBLIC_SEARCH_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索查询文本，例如 '腾讯后端开发岗位技术栈要求'",
        },
        "top_k": {
            "type": "integer",
            "description": "返回搜索结果数量，默认 5",
            "default": 5,
        },
    },
    "required": ["query"],
}


async def public_search_execute(query: str, top_k: int = 5, **kwargs) -> ToolResult:
    """执行公开搜索，返回标准化结果。"""
    logger.info("[public_search] query=%s top_k=%s", query[:60], top_k)

    try:
        from app.infrastructure.external_search import public_search as _search

        data = await _search(query=str(query), top_k=int(top_k))
        if data.get("error"):
            return ToolResult.fail(str(data["error"]))
        return ToolResult.ok(data)
    except Exception as exc:
        logger.exception("[public_search] failed: %s", exc)
        return ToolResult.fail(str(exc))


public_search_tool = ToolDefinition(
    name="public_search",
    description=(
        "在公开互联网上搜索信息，返回相关网页的标题、URL 和摘要。"
        "适用于查找公司背景、行业信息、技术栈趋势、岗位要求等公开资料。"
        "不是对比工具，搜索结果需后续步骤总结后才产生结论。"
    ),
    parameters=PUBLIC_SEARCH_PARAMETERS,
    execute=public_search_execute,
    keywords=["搜索", "检索", "查找", "public", "web", "查"],
    render_type="item_list",
    input_requirements=InputRequirements(query=True),
)

tool_registry.register(public_search_tool)
