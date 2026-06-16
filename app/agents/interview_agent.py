"""Interview Agent — 面试题生成（后续扩展模拟面试）。

从 Coordinator 视角看：
  "基于简历和岗位生成四类面试题（技术/项目/行为/风险），支持 RAG 增强"

内部 pipeline：retrieve_knowledge → generate_questions
两个步骤：先检索知识库做 RAG 增强，再生成最终面试题。
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.state import AgentAnalyzeState
from app.agents.base import SubAgent
from app.agent.workflow import (
    build_interview_questions_prompt_node,
    load_job_node,
    load_resume_node,
    parse_questions_node,
    retrieve_knowledge_node,
)
from app.agent.common import save_success_task
from app.core.llm import invoke_llm

logger = logging.getLogger(__name__)

INTERVIEW_AGENT_SYSTEM_PROMPT = """\
你是面试题生成专家。

你的任务：
1. 先从知识库检索相关技术知识点（RAG）
2. 再基于简历+JD+检索结果生成四类面试题

请直接按顺序执行，生成具体、可追问的技术面试题，避免泛泛而谈。
"""


def _generate_questions_node(state: AgentAnalyzeState) -> dict[str, Any]:
    """LLM 生成面试题节点。"""
    if state.get("error_msg"):
        return {}
    logger.info("[InterviewAgent] LLM 生成面试题")
    raw_output = invoke_llm(state["prompt"])
    return {"raw_output": raw_output}


def _save_interview_task_node(state: AgentAnalyzeState) -> dict[str, Any]:
    """保存面试题生成任务记录。"""
    if state.get("error_msg"):
        return {}
    task_id = save_success_task(
        task_type="INTERVIEW_QUESTIONS",
        resume_id=state["resume_id"],
        job_id=state["job_id"],
        output_data=state["interview_questions"],
        input_data={
            "resume_id": state["resume_id"],
            "job_id": state["job_id"],
            "enable_rag": True,
            "knowledge_used": bool(state.get("knowledge_used")),
            "knowledge_count": state.get("knowledge_count") or 0,
        },
        user_id=state["user_id"],
    )
    return {"task_id": task_id}


def _route_after_load(state: AgentAnalyzeState) -> str:
    return END if state.get("error_msg") else "retrieve_knowledge"


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
        # 复用现有节点函数
        wf.add_node("load_resume", load_resume_node)
        wf.add_node("load_job", load_job_node)
        wf.add_node("retrieve_knowledge", retrieve_knowledge_node)
        wf.add_node("build_prompt", build_interview_questions_prompt_node)
        wf.add_node("llm_generate", _generate_questions_node)
        wf.add_node("parse_questions", parse_questions_node)
        wf.add_node("save_task", _save_interview_task_node)

        wf.add_edge(START, "load_resume")
        wf.add_conditional_edges("load_resume", _route_after_load, {"retrieve_knowledge": "load_job", END: END})
        wf.add_conditional_edges("load_job", _route_after_load, {"retrieve_knowledge": "retrieve_knowledge", END: END})
        wf.add_edge("retrieve_knowledge", "build_prompt")
        wf.add_edge("build_prompt", "llm_generate")
        wf.add_edge("llm_generate", "parse_questions")
        wf.add_edge("parse_questions", "save_task")
        wf.add_edge("save_task", END)
        return wf.compile()


# 全局单例
interview_agent = InterviewAgent()
