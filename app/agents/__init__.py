"""多 Agent 协作模块 — Coordinator + 专业子 Agent 层次化架构。

Coordinator (协调者, ReAct agent)
  ├── ResumeAgent     → 匹配分析 + 简历优化
  ├── InterviewAgent  → 面试题生成
  └── SearchAgent     → 岗位推荐 + 知识检索

子 Agent 从 Coordinator 视角看就是 ToolDefinition，内部运行自己的 pipeline。
"""

from app.agents.base import SubAgent
from app.agents.resume_agent import resume_agent
from app.agents.interview_agent import interview_agent
from app.agents.search_agent import search_agent
from app.agents.coordinator import create_coordinator_graph, COORDINATOR_SYSTEM_PROMPT

__all__ = [
    "SubAgent",
    "resume_agent",
    "interview_agent",
    "search_agent",
    "create_coordinator_graph",
    "COORDINATOR_SYSTEM_PROMPT",
]
