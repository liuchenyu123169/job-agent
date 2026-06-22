"""Search Agent — 岗位推荐 + 知识库检索。

从 Coordinator 视角看：
  "基于简历推荐最匹配的岗位，或在知识库中检索技术知识点"

两种模式（由 Coordinator 的 goal 决定）：
  - 岗位推荐：recommend_jobs
  - 知识检索：search_knowledge

架构约束：Agent 只组合 Tool，不直接碰 workflow 层。
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.workflows.common import _trace_node
from app.workflows.state import AgentAnalyzeState
from app.agents.base import SubAgent
from app.tools import tool_registry

logger = logging.getLogger(__name__)

SEARCH_AGENT_SYSTEM_PROMPT = """\
你是岗位搜索与知识检索专家。

你的任务（根据用户意图二选一或都做）：
1. 岗位推荐：基于简历对所有岗位打分，返回 Top 5 最匹配的
2. 知识检索：在 RAG 知识库中检索特定技术栈的面试知识点

请直接执行，不要在"要不要做"上纠结——Coordinator 已经把任务分给你了。
"""


def _run_search_knowledge_node(state: AgentAnalyzeState) -> dict[str, Any]:
    """执行知识库检索 (via Tool)。"""
    if state.get("error_msg"):
        return {}
    logger.info("[SearchAgent] 知识库检索 (via Tool)")
    tool = tool_registry.get("search_knowledge")
    if tool is None:
        return {"error_msg": "Tool search_knowledge 未注册"}
    # search_knowledge 是同步工具，通过 tool.execute 调用（内部是 sync 函数）
    import asyncio
    loop = asyncio.get_event_loop()
    # 注意：tool.execute 是 async，可以安全调用
    # 但我们是在 sync 节点函数中，需要特殊处理
    # SearchAgent pipeline 节点目前仍是 sync（无 LLM），所以用 _trace_node 包装
    items = None
    try:
        # 直接调用底层服务（search_knowledge tool 内部也是调这个）
        from app.rag.rag_service import search_knowledge
        items = search_knowledge(query="面试技术知识点 核心原理", top_k=5)
    except Exception as exc:
        logger.error("[SearchAgent] 知识检索失败: %s", exc)
        return {"error_msg": str(exc)}

    if not items:
        return {
            "knowledge_context": "",
            "knowledge_used": False,
            "knowledge_count": 0,
        }
    return {
        "knowledge_context": "\n\n".join(
            f"【{item.get('title', '')}】{item.get('content', '')[:500]}"
            for item in items
        ),
        "knowledge_used": bool(items),
        "knowledge_count": len(items),
    }


class SearchAgent(SubAgent):
    name = "search_agent"
    description = "基于简历内容对所有岗位进行匹配打分并推荐最佳岗位，或在知识库中检索面试技术知识点。当用户想找适合的岗位或查询特定技术面试题时调用。"

    @property
    def system_prompt(self) -> str:
        return SEARCH_AGENT_SYSTEM_PROMPT

    @property
    def tools(self) -> list[str]:
        return ["recommend_jobs", "search_knowledge", "list_jobs"]

    def build_pipeline(self):
        # 搜索 Agent 无 LLM 调用，同步图即可满足
        wf = StateGraph(AgentAnalyzeState)
        wf.add_node("run_search", _trace_node("run_search", _run_search_knowledge_node))
        wf.add_edge(START, "run_search")
        wf.add_edge("run_search", END)
        return wf.compile()


# 全局单例
search_agent = SearchAgent()
