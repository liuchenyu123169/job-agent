"""SubAgent 基类 — 每个子 Agent 有自己的 system_prompt + 工具集 + 内部 pipeline。

设计考量：
  - 子 Agent 内部用 pipeline 而非 ReAct，因为其任务步骤固定（匹配→优化→出题）。
    简单任务不需要 LLM 反复推理，pipeline 更稳定、更快、更省 token。
  - run() 返回结构化 dict，Coordinator 直接消费，不做二次解析。
  - 子 Agent 之间不直接通信——所有结果通过 Coordinator 中转。
    这避免了"哪个 Agent 应该跟哪个 Agent 说话"的耦合问题。
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.state import AgentAnalyzeState, make_initial_state

logger = logging.getLogger(__name__)


class SubAgent(ABC):
    """子 Agent 抽象基类。

    子类需要实现:
      - system_prompt: 子 Agent 的角色描述和工具使用说明
      - tools: 可用工具名列表（从 tool_registry 按名获取）
      - build_pipeline(): 构建内部 StateGraph pipeline

    调用方式：
      result = agent.run(goal="...", resume_id=1, job_id=2, user_id=1)
    """

    name: str
    description: str  # Coordinator 看到的工具描述

    def __init__(self):
        self._graph = self.build_pipeline()

    # ── 子类必须实现 ──

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """子 Agent 收到任务时的系统提示词。"""
        ...

    @property
    @abstractmethod
    def tools(self) -> list[str]:
        """子 Agent 可用的工具名列表，如 ['match_analyze', 'optimize_resume']。"""
        ...

    @abstractmethod
    def build_pipeline(self):
        """构建子 Agent 内部执行的 StateGraph pipeline。

        典型结构：
          START → node_a → node_b → node_c → END

        每个节点从 tool_registry 获取 ToolDefinition 并调用其 execute()。
        编译后的 graph 存在 self._graph。
        """
        ...

    # ── 公共接口 ──

    def run(self, goal: str, resume_id: int, job_id: int, user_id: int) -> dict[str, Any]:
        """执行子任务。

        Args:
            goal: 子任务描述（Coordinator 告诉子 Agent 要做什么）
            resume_id: 简历 ID
            job_id: 岗位 ID
            user_id: 用户 ID

        Returns:
            {"success": bool, "data": {...}, "error": str|None}
        """
        logger.info("[%s] 开始执行: goal=%s resume_id=%s job_id=%s", self.name, goal, resume_id, job_id)

        initial = make_initial_state(user_id, resume_id, job_id)

        try:
            final_state = self._graph.invoke(initial)
            if final_state.get("error_msg"):
                logger.warning("[%s] 执行失败: %s", self.name, final_state["error_msg"])
                return {"success": False, "data": None, "error": final_state["error_msg"]}

            # 提取有效结果
            data: dict[str, Any] = {
                "task_id": final_state.get("task_id"),
            }
            if final_state.get("analysis"):
                data["analysis"] = final_state["analysis"]
            if final_state.get("optimization"):
                data["optimization"] = final_state["optimization"]
            if final_state.get("interview_questions"):
                data["questions"] = final_state["interview_questions"]

            logger.info("[%s] 执行成功: keys=%s", self.name, [k for k in data if data[k]])
            return {"success": True, "data": data, "error": None}

        except Exception as exc:
            logger.exception("[%s] 执行异常: %s", self.name, exc)
            return {"success": False, "data": None, "error": str(exc)}

