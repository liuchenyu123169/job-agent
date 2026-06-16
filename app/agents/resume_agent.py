"""Resume Agent — 匹配分析 + 简历优化。

从 Coordinator 视角看就是一个工具：
  "分析简历与岗位匹配度，并给出简历优化建议"

内部 pipeline：match_analyze → optimize_resume
两个步骤依赖同一个 resume+job，无分支逻辑，pipeline 模式最合适。
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.state import AgentAnalyzeState
from app.agent.workflow import run_analyze_workflow, run_optimize_resume_workflow
from app.agents.base import SubAgent

logger = logging.getLogger(__name__)

RESUME_AGENT_SYSTEM_PROMPT = """\
你是求职匹配与简历优化专家。

你的任务流程固定：
1. 先分析简历与岗位的匹配度（match_analyze）
2. 再给出简历优化建议（optimize_resume）

请直接按顺序执行，不需要额外思考或规划。结果中包含匹配分数和优化建议。
"""


def _run_match_node(state: AgentAnalyzeState) -> dict[str, Any]:
    """执行匹配分析，复用现有 workflow。"""
    if state.get("error_msg"):
        return {}
    logger.info("[ResumeAgent] 步骤1: 匹配分析")
    result = run_analyze_workflow(
        resume_id=int(state["resume_id"]),
        job_id=int(state["job_id"]),
        user_id=int(state["user_id"]),
    )
    if result.get("error_msg"):
        return {"error_msg": result["error_msg"]}
    return {
        "analysis": result.get("analysis"),
        "task_id": result.get("task_id"),
    }


def _run_optimize_node(state: AgentAnalyzeState) -> dict[str, Any]:
    """执行简历优化，复用现有 workflow。"""
    if state.get("error_msg"):
        return {}
    logger.info("[ResumeAgent] 步骤2: 简历优化")
    result = run_optimize_resume_workflow(
        resume_id=int(state["resume_id"]),
        job_id=int(state["job_id"]),
        user_id=int(state["user_id"]),
    )
    if result.get("error_msg"):
        return {"error_msg": result["error_msg"]}
    return {
        "optimization": result.get("optimization"),
    }


def _route_after_match(state: AgentAnalyzeState) -> str:
    return END if state.get("error_msg") else "run_optimize"


class ResumeAgent(SubAgent):
    name = "resume_agent"
    description = "分析简历与岗位的匹配度（返回分数/优势/劣势/建议），并给出针对性的简历优化建议。当用户想了解自己与某个岗位的匹配程度，或需要改进简历时调用。"

    @property
    def system_prompt(self) -> str:
        return RESUME_AGENT_SYSTEM_PROMPT

    @property
    def tools(self) -> list[str]:
        return ["match_analyze", "optimize_resume"]

    def build_pipeline(self):
        wf = StateGraph(AgentAnalyzeState)
        wf.add_node("run_match", _run_match_node)
        wf.add_node("run_optimize", _run_optimize_node)
        wf.add_edge(START, "run_match")
        wf.add_conditional_edges("run_match", _route_after_match, {"run_optimize": "run_optimize", END: END})
        wf.add_edge("run_optimize", END)
        return wf.compile()


# 全局单例
resume_agent = ResumeAgent()
