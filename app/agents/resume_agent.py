"""Resume Agent — 匹配分析 + 简历优化。

从 Coordinator 视角看就是一个工具：
  "分析简历与岗位匹配度，并给出简历优化建议"

内部 pipeline：match_analyze → optimize_resume
两个步骤依赖同一个 resume+job，无分支逻辑，pipeline 模式最合适。
"""

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.common import _trace_node
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

from app.agent.workflow import analyze_graph_async, optimize_resume_graph_async

async def _run_match_node_async(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
      return {}
    logger.info("[ResumeAgent] 步骤1: 匹配分析 (async)")
    final_state = await analyze_graph_async.ainvoke({
      "user_id": state["user_id"],
      "resume_id": state["resume_id"],
      "job_id": state["job_id"],
    })
    if final_state.get("error_msg"):
      return {"error_msg": final_state["error_msg"]}
    return {
      "analysis_text": final_state.get("analysis_text", ""),
      "task_id": final_state.get("task_id"),
    }

async def _run_optimize_node_async(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
      return {}
    logger.info("[ResumeAgent] 步骤2: 简历优化 (async)")
    final_state = await optimize_resume_graph_async.ainvoke({
      "user_id": state["user_id"],
      "resume_id": state["resume_id"],
      "job_id": state["job_id"],
    })
    if final_state.get("error_msg"):
      return {"error_msg": final_state["error_msg"]}
    return {
      "analysis_text": state.get("analysis_text"),
      "optimization_text": final_state.get("optimization_text", ""),
      "task_id": final_state.get("task_id"),
    }

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
        "analysis_text": result.get("analysis_text", ""),
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
        "analysis_text": state.get("analysis_text"),  # 保留上一步的匹配分析结果
        "optimization_text": result.get("optimization_text", ""),
        "task_id": result.get("task_id"),
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
        wf.add_node("run_match", _trace_node("run_match", _run_match_node))
        wf.add_node("run_optimize", _trace_node("run_optimize", _run_optimize_node))
        wf.add_edge(START, "run_match")
        wf.add_conditional_edges("run_match", _route_after_match, {"run_optimize": "run_optimize", END: END})
        wf.add_edge("run_optimize", END)
        return wf.compile()

    def build_pipeline_async(self):
        wf = StateGraph(AgentAnalyzeState)
        wf.add_node("run_match", _run_match_node_async)  # ← async 版
        wf.add_node("run_optimize", _run_optimize_node_async)  # ← async 版
        wf.add_edge(START, "run_match")
        wf.add_conditional_edges("run_match", _route_after_match, {"run_optimize": "run_optimize", END: END})
        wf.add_edge("run_optimize", END)
        return wf.compile()


# 全局单例
resume_agent = ResumeAgent()
