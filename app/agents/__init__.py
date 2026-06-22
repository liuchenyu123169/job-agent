"""多 Agent 协作模块 — Coordinator + 专业子 Agent 层次化架构。

Coordinator (协调者, ReAct agent)
  ├── ResumeAgent     → 匹配分析 + 简历优化
  ├── InterviewAgent  → 面试题生成
  └── SearchAgent     → 岗位推荐 + 知识检索

两层注册中心分离：
  - tool_registry: 原子能力 (ToolDefinition)
  - agent_registry: 组合能力 (SubAgent)

Coordinator 只面向 agent_registry 调度，不直接操作原子 Tool。
SubAgent 内部组合 Tool，不直接碰 workflow。
"""

from app.agents.base import SubAgent
from app.agents.registry import agent_registry, AgentRegistry
from app.agents.resume_agent import resume_agent
from app.agents.interview_agent import interview_agent
from app.agents.search_agent import search_agent
from app.agents.coordinator import create_coordinator_graph, COORDINATOR_SYSTEM_PROMPT

# 注册 3 个子 Agent 到 agent_registry
agent_registry.register(resume_agent)
agent_registry.register(interview_agent)
agent_registry.register(search_agent)

__all__ = [
    "SubAgent",
    "AgentRegistry",
    "agent_registry",
    "resume_agent",
    "interview_agent",
    "search_agent",
    "create_coordinator_graph",
    "COORDINATOR_SYSTEM_PROMPT",
]
