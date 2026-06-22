"""Interview Agent — 面试题生成（后续扩展模拟面试）。

从 Coordinator 视角看：
  "基于简历和岗位生成四类面试题（技术/项目/行为/风险），支持 RAG 增强"

内部 pipeline：直接调用 generate_interview_questions Tool 完成完整流程。

架构约束：Agent 只组合 Tool，不直接碰 workflow 层。
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.workflows.state import AgentAnalyzeState
from app.agents.base import SubAgent
from app.tools import tool_registry

logger = logging.getLogger(__name__)

INTERVIEW_AGENT_SYSTEM_PROMPT = """\
你是面试题生成专家。

你的任务：
1. 先从知识库检索相关技术知识点（RAG）
2. 再基于简历+JD+检索结果生成四类面试题

请直接按顺序执行，生成具体、可追问的技术面试题，避免泛泛而谈。
"""


async def _run_interview_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    logger.info("[InterviewAgent] 面试题生成 (via Tool)")
    tool = tool_registry.get("generate_interview_questions")
    if tool is None:
        return {"error_msg": "Tool generate_interview_questions 未注册"}
    result = await tool.execute(
        resume_id=int(state["resume_id"]),
        job_id=int(state["job_id"]),
        user_id=int(state["user_id"]),
        enable_rag=state.get("enable_rag", True),
    )
    if not result.success:
        return {"error_msg": result.error or "generate_interview_questions failed"}
    data = result.data or {}
    return {
        "questions_text": str(data.get("questions", "")),
        "task_id": data.get("task_id"),
    }


class InterviewAgent(SubAgent):
    name = "interview_agent"
    description = "基于简历和岗位生成面试题，涵盖技术题/项目题/行为题/风险题四类，支持 RAG 知识库增强。在匹配分析之后，用户需要准备面试时调用。"

    @property
    def system_prompt(self) -> str:
        return INTERVIEW_AGENT_SYSTEM_PROMPT

    @property
    def tools(self) -> list[str]:
        return ["generate_interview_questions", "search_knowledge"]

    def build_pipeline(self):
        wf = StateGraph(AgentAnalyzeState)
        wf.add_node("run_interview", _run_interview_node)
        wf.add_edge(START, "run_interview")
        wf.add_edge("run_interview", END)
        return wf.compile()


# 全局单例
interview_agent = InterviewAgent()
