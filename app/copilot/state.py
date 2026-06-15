"""Pipeline 状态定义 — LangGraph 用的 TypedDict + 累积上下文数据类。"""

from dataclasses import dataclass, field
from typing import Any, TypedDict

from langchain_core.messages import BaseMessage


@dataclass
class PipelineContext:
    """Pipeline 执行期间的累积上下文。

    在工具调用链中不断积累信息：用户选定了哪个简历、哪个岗位、
    中间步骤的分析结果、最终任务 ID 列表等。
    """
    # 用户选定的资源
    resume_id: int | None = None
    job_id: int | None = None

    # 各步骤的执行结果（按工具名存储）
    tool_results: dict[str, dict[str, Any]] = field(default_factory=dict)

    # 已完成的工具调用顺序记录
    executed_tools: list[str] = field(default_factory=list)

    # 产生的任务 ID 列表
    task_ids: list[int] = field(default_factory=list)

    def record_result(self, tool_name: str, result: dict[str, Any]) -> None:
        """记录一个工具的执行结果。"""
        self.executed_tools.append(tool_name)
        self.tool_results[tool_name] = result
        task_id = result.get("task_id")
        if task_id is not None:
            self.task_ids.append(int(task_id))

    def to_summary(self) -> dict[str, Any]:
        """将上下文导出为可供汇总的结构。"""
        return {
            "resume_id": self.resume_id,
            "job_id": self.job_id,
            "executed_tools": list(self.executed_tools),
            "task_ids": list(self.task_ids),
            "tool_results": dict(self.tool_results),
        }


class PipelineState(TypedDict):
    """LangGraph StateGraph 使用的状态类型。

    核心字段 messages 是 LangChain 消息列表，
    LangGraph 的 ToolNode 依赖这个字段自动拼接工具调用和结果。
    """
    messages: list[BaseMessage]
    context: PipelineContext
    user_id: int
