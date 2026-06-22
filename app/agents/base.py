"""SubAgent 基类 — 每个子 Agent 有自己的 system_prompt + 工具集 + 内部 pipeline。

设计考量：
  - 子 Agent 内部用 pipeline 而非 ReAct，因为其任务步骤固定（匹配→优化→出题）。
    简单任务不需要 LLM 反复推理，pipeline 更稳定、更快、更省 token。
  - run_stream_async() 返回结构化 dict，Coordinator 直接消费，不做二次解析。
  - 子 Agent 之间不直接通信——所有结果通过 Coordinator 中转。
    这避免了"哪个 Agent 应该跟哪个 Agent 说话"的耦合问题。
  - 纯异步：只保留 astream() 执行路径，sync invoke/stream 已删除。
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable

from langgraph.graph import StateGraph

from app.workflows.state import AgentAnalyzeState, make_initial_state

logger = logging.getLogger(__name__)


class SubAgent(ABC):
    """子 Agent 抽象基类。

    子类需要实现:
      - system_prompt: 子 Agent 的角色描述
      - tools: 可用工具名列表（从 tool_registry 按名获取）
      - build_pipeline(): 构建内部 StateGraph pipeline（异步）

    调用方式：
      result = await agent.run_stream_async(goal="...", resume_id=1, job_id=2, user_id=1)
    """

    name: str
    description: str  # Coordinator 看到的描述

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
        """子 Agent 可用的工具名列表，如 ['match_analyze', 'optimize_resume']。

        build_pipeline() 中应通过 tool_registry 调用这些工具。
        """
        ...

    @abstractmethod
    def build_pipeline(self):
        """构建子 Agent 内部执行的 StateGraph pipeline（异步）。

        典型结构：
          START → node_a → node_b → node_c → END

        每个节点从 tool_registry 获取 ToolDefinition 并调用其 execute()。
        编译后的 graph 存在 self._graph，通过 astream() 执行。
        """
        ...

    # ── 公共接口 ──

    async def run_stream_async(
        self, goal: str, resume_id: int, job_id: int, user_id: int,
        on_step: "Callable[[str, float], None] | None" = None,
        on_token: "Callable[[str], None] | None" = None,
    ) -> dict[str, Any]:
        """异步流式执行 — 支持 token 级 SSE 推送。

        Args:
            goal: 子任务描述
            resume_id: 简历 ID
            job_id: 岗位 ID
            user_id: 用户 ID
            on_step: 节点完成回调 (node_name, duration_ms)
            on_token: token 回调 (token_text)
        """
        logger.info("[%s] 开始异步流式执行: goal=%s", self.name, goal)

        from app.workflows.common import _step_callback, _token_callback

        step_token = _step_callback.set(on_step) if on_step else None
        token_token = _token_callback.set(on_token) if on_token else None

        initial = make_initial_state(user_id, resume_id, job_id)
        final_node_state = initial

        try:
            async for chunk in self._graph.astream(initial):
                for _node_name, node_state in chunk.items():
                    final_node_state = node_state

            if final_node_state.get("error_msg"):
                logger.warning("[%s] 异步执行失败: %s", self.name, final_node_state["error_msg"])
                return {"success": False, "data": None, "error": final_node_state["error_msg"]}

            data: dict[str, Any] = {
                "task_id": final_node_state.get("task_id"),
            }
            if final_node_state.get("analysis_text"):
                data["analysis_text"] = final_node_state["analysis_text"]
            if final_node_state.get("optimization_text"):
                data["optimization_text"] = final_node_state["optimization_text"]
            if final_node_state.get("questions_text"):
                data["questions_text"] = final_node_state["questions_text"]
            if final_node_state.get("generated_resume"):
                data["generated_resume"] = final_node_state["generated_resume"]

            logger.info("[%s] 异步流式执行成功: keys=%s", self.name, [k for k in data if data[k]])
            return {"success": True, "data": data, "error": None}

        except Exception as exc:
            logger.exception("[%s] 异步流式执行异常: %s", self.name, exc)
            return {"success": False, "data": None, "error": str(exc)}
        finally:
            if step_token is not None:
                _step_callback.reset(step_token)
            if token_token is not None:
                _token_callback.reset(token_token)
