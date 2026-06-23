"""Agent 注册中心 — 全局单例，管理 SubAgent 的注册与查找。

与 tool_registry 分离：
  - tool_registry: 原子能力 (match_analyze, optimize_resume, ...)
  - agent_registry: 组合能力 (resume_agent, interview_agent, search_agent)

Coordinator 只面向 agent_registry 做调度，不直接操作原子 Tool。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.base import SubAgent


class AgentRegistry:
    """SubAgent 注册中心，支持按名称查找。"""

    def __init__(self) -> None:
        self._agents: dict[str, "SubAgent"] = {}

    def register(self, agent: "SubAgent") -> None:
        """注册一个 SubAgent，同名覆盖。"""
        self._agents[agent.name] = agent

    def get(self, name: str) -> "SubAgent | None":
        """按名称查找 SubAgent，未找到返回 None。"""
        return self._agents.get(name)

    def list_all(self) -> list["SubAgent"]:
        """返回所有已注册的 SubAgent。"""
        return list(self._agents.values())

    def get_names(self) -> list[str]:
        """返回所有已注册的 SubAgent 名称列表。"""
        return list(self._agents.keys())


# 全局单例
agent_registry = AgentRegistry()
