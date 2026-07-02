"""岗位页面采集工具 — 调用八爪鱼等抓取服务，获取外部岗位 JD 内容。"""

import logging

from app.tools.base import InputRequirements, ToolDefinition, ToolResult
from app.tools.registry import tool_registry

logger = logging.getLogger(__name__)

FETCH_JOB_PAGE_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "目标岗位详情页 URL，例如 'https://www.zhipin.com/job_detail/xxx.html'",
        },
    },
    "required": ["url"],
}


async def fetch_job_page_execute(url: str, **kwargs) -> ToolResult:
    """抓取岗位页面内容，返回标准化 JD 信息。"""
    logger.info("[fetch_job_page] url=%s", url[:80])

    try:
        from app.infrastructure.external_job import fetch_job_page as _fetch

        data = await _fetch(url=str(url))
        if data.get("error"):
            return ToolResult.fail(str(data["error"]))
        return ToolResult.ok(data)
    except Exception as exc:
        logger.exception("[fetch_job_page] failed: %s", exc)
        return ToolResult.fail(str(exc))


fetch_job_page_tool = ToolDefinition(
    name="fetch_job_page",
    description=(
        "从外部 URL 抓取岗位详情页内容，提取公司、岗位名称、地点、薪资、JD 描述等信息。"
        "适用于用户提供了岗位链接而非 job_id 的场景，抓取后可创建临时岗位记录用于后续分析。"
    ),
    parameters=FETCH_JOB_PAGE_PARAMETERS,
    execute=fetch_job_page_execute,
    keywords=["抓取", "采集", "fetch", "爬取", "链接", "url", "页面"],
    render_type="generic",
    input_requirements=InputRequirements(),
)

tool_registry.register(fetch_job_page_tool)
