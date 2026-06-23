"""Search Agent — 岗位推荐 + 知识库检索。

从 Coordinator 视角看：
  "基于简历推荐最匹配的岗位，或在知识库中检索技术知识点"

内部 pipeline：同时执行 recommend_jobs + search_knowledge，结果合并返回。

架构约束：Agent 只组合 Tool，不直接碰 workflow 层。
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

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


async def _run_recommend_node(state: AgentAnalyzeState) -> dict[str, Any]:
    """执行岗位推荐（通过 recommend_jobs Tool）。"""
    if state.get("error_msg"):
        return {}
    logger.info("[SearchAgent] 岗位推荐 (via Tool)")
    tool = tool_registry.get("recommend_jobs")
    if tool is None:
        return {"error_msg": "Tool recommend_jobs 未注册"}
    try:
        result = await tool.execute(
            resume_id=int(state["resume_id"]),
            user_id=int(state["user_id"]),
            top_k=5,
            max_jobs=10,
        )
        if not result.success:
            logger.warning("[SearchAgent] 岗位推荐失败: %s", result.error)
            return {}  # 推荐失败不阻塞知识检索
        data = result.data or {}
        return {
            "recommend_items": data.get("items", []),
            "recommend_count": data.get("candidate_job_count", 0),
        }
    except Exception as exc:
        logger.error("[SearchAgent] 岗位推荐异常: %s", exc)
        return {}  # 不阻塞


async def _run_knowledge_node(state: AgentAnalyzeState) -> dict[str, Any]:
    """执行知识库检索（通过 search_knowledge Tool）。"""
    if state.get("error_msg"):
        return {}
    logger.info("[SearchAgent] 知识库检索 (via Tool)")
    tool = tool_registry.get("search_knowledge")
    if tool is None:
        return {}  # 知识检索不是必须的
    try:
        result = await tool.execute(query="面试技术知识点 核心原理", top_k=5)
        if not result.success:
            return {}
        data = result.data or {}
        items = data.get("items", [])
        if not items:
            return {"knowledge_used": False, "knowledge_count": 0}
        return {
            "knowledge_context": "\n\n".join(
                f"【{item.get('title', '')}】{item.get('content', '')[:500]}"
                for item in items
            ),
            "knowledge_used": True,
            "knowledge_count": len(items),
        }
    except Exception as exc:
        logger.error("[SearchAgent] 知识检索异常: %s", exc)
        return {}


def _merge_results(state: AgentAnalyzeState) -> dict[str, Any]:
    """合并推荐和检索结果。"""
    if state.get("error_msg"):
        return {}
    items = state.get("recommend_items") or []
    return {
        "recommend_items": items,
        "recommend_count": state.get("recommend_count", 0),
        "knowledge_context": state.get("knowledge_context", ""),
        "knowledge_used": state.get("knowledge_used", False),
        "knowledge_count": state.get("knowledge_count", 0),
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
        """两个独立任务并行执行，结果合并返回。"""
        wf = StateGraph(AgentAnalyzeState)
        # 两个节点并行（无依赖，LangGraph 会自动并发）
        wf.add_node("run_recommend", _run_recommend_node)
        wf.add_node("run_knowledge", _run_knowledge_node)
        wf.add_node("merge", _merge_results)
        wf.add_edge(START, "run_recommend")
        wf.add_edge(START, "run_knowledge")
        wf.add_edge("run_recommend", "merge")
        wf.add_edge("run_knowledge", "merge")
        wf.add_edge("merge", END)
        return wf.compile()


# 全局单例
search_agent = SearchAgent()
