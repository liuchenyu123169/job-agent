"""Coordinator Agent — ReAct 调度者，把子 Agent 当成工具来调用。

核心设计：
  - Coordinator 本身是一个 ReAct agent（复用 app/copilot/graph.py 的图结构）
  - 其 "工具" 是子 Agent（SubAgent 实例），每个子 Agent 包装为 ToolDefinition
  - System prompt 告诉 LLM：你是协调者，把任务委派给专业子 Agent

与单 Agent 的区别：
  - 单 Agent：8 个原子工具平铺 → LLM 决策难度高、prompt 长
  - Coordinator：3 个子 Agent 工具 → LLM 先想"该委派给谁"，子 Agent 内部自行执行

面试考点：
  - 为什么子 Agent 用 pipeline 不用 ReAct？→ 确定性任务不需要反复推理
  - 为什么 Coordinator 用 ReAct？→ 任务分解本身是推理密集型，需要动态决策
  - Agent 间通信格式？→ 结构化 dict（success/data/error），不传原始 LLM 文本
"""

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from app.agents.base import SubAgent
from app.copilot.state import PipelineState
from app.core.llm import invoke_llm_with_tools
from app.tools.base import ToolDefinition, ToolResult
from app.tools.registry import tool_registry

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Coordinator System Prompt
# ═══════════════════════════════════════════════════════════════

COORDINATOR_SYSTEM_PROMPT = """\
你是一个求职 AI 协调者（JobAgent Coordinator），负责理解用户需求，然后将子任务委派给专业子 Agent。

## 你的子 Agent 团队
你有以下三个专业子 Agent 可以调用：

- **resume_agent** — 简历匹配分析和优化专家。负责：分析简历与岗位的匹配度（返回分数/优势/劣势/建议），给出简历优化建议。
- **interview_agent** — 面试题生成专家。负责：基于简历和岗位生成四类面试题（技术/项目/行为/风险），支持 RAG 知识库增强。
- **search_agent** — 岗位搜索与知识检索专家。负责：基于简历推荐最匹配的岗位，或在知识库中检索技术面试知识点。

## 你的工作方式
1. **理解用户意图** — 用户想要什么？仔细分析用户输入，识别所有可能的意图。
   如果用户同时提到多个意图（如"分析匹配度，顺便推荐岗位"），你需要委派**所有相关子 Agent**。
2. **分解任务** — 把用户需求拆成 1-3 个子任务，分配给相应的子 Agent
3. **顺序委派** — 如果子任务之间没有依赖（如匹配分析 + 岗位推荐），可以并行调用。
   如果有依赖（如面试题生成应在匹配分析之后），就按顺序调用。
4. **汇总报告** — 子 Agent 返回结果后，给用户一份简洁总结，覆盖所有已完成的子任务

## 常见场景
- "帮我全面备战 XX 岗位" → resume_agent → interview_agent
- "看看哪些岗位适合我" → search_agent
- "我只想准备面试" → interview_agent
- "帮我分析这个岗位匹配度" → resume_agent
- "分析匹配度，顺便推荐几个岗位" → resume_agent + search_agent（并行，无依赖）
- "全面备战，也帮我看看其他岗位" → resume_agent + search_agent + interview_agent

## 规则
1. 先确认 resume_id 和 job_id 都已知，否则先让用户选择
2. 每个子 Agent 调用完检查返回的 success 字段
3. 用中文回复
4. 汇报时用具体数据（匹配分数、问题数量），不要泛泛而谈
5. **如果用户表达了多个意图，必须委派所有相关的子 Agent，不要只做一个**
"""

# ═══════════════════════════════════════════════════════════════
# 子 Agent → ToolDefinition 包装
# ═══════════════════════════════════════════════════════════════

def _wrap_sub_agent_tool(agent: SubAgent) -> ToolDefinition:
    """将 SubAgent 包装为 ToolDefinition，Coordinator 的 ReAct 循环可调用。

    关键：execute 函数内部的逻辑是调用 agent.run()，然后返回 ToolResult。
    Coordinator 不需要知道子 Agent 内部有几个步骤、调了哪些 LLM——
    它只看到"调用了一个工具，拿到了结果"。
    """

    async def _execute(
        resume_id: int = 0,
        job_id: int = 0,
        user_id: int = 0,
        **kwargs,
    ) -> ToolResult:
        goal = kwargs.pop("goal", f"执行 {agent.name} 的默认任务")
        result = await asyncio.to_thread(
            agent.run,
            goal=str(goal),
            resume_id=int(resume_id),
            job_id=int(job_id),
            user_id=int(user_id),
        )
        if result["success"]:
            return ToolResult.ok(result["data"] or {})
        return ToolResult.fail(result.get("error") or "unknown error")

    return ToolDefinition(
        name=agent.name,
        description=agent.description,
        parameters={
            "type": "object",
            "properties": {
                "resume_id": {"type": "integer", "description": "简历 ID"},
                "job_id": {"type": "integer", "description": "岗位 ID"},
                "goal": {"type": "string", "description": "子任务描述，告诉子 Agent 要做什么"},
            },
            "required": ["resume_id", "job_id"],
        },
        execute=_execute,
        keywords=[],
        render_type="generic",
    )


# ═══════════════════════════════════════════════════════════════
# Coordinator ReAct Graph（结构与 copilot/graph.py 完全一致）
# ═══════════════════════════════════════════════════════════════

def create_coordinator_graph(sub_agents: list[SubAgent]):
    """构建 Coordinator 的 ReAct 循环图。

    Args:
        sub_agents: 子 Agent 列表，每个都会被注册为 Coordinator 的工具

    Returns:
        编译后的 LangGraph StateGraph
    """
    # 将子 Agent 注册到 tool_registry（临时注册，Coordinator 专用）
    sub_tool_names: set[str] = set()
    for agent in sub_agents:
        tool = _wrap_sub_agent_tool(agent)
        tool_registry.register(tool)
        sub_tool_names.add(tool.name)
        logger.info("[Coordinator] 注册子 Agent 工具: %s", tool.name)

    # ── agent_node：LLM 决策 ──

    def agent_node(state: PipelineState) -> dict[str, Any]:
        messages = state["messages"]
        if not messages or not isinstance(messages[0], SystemMessage):
            ctx = state.get("context")
            prompt = COORDINATOR_SYSTEM_PROMPT
            # 注入当前上下文信息，避免 LLM 反复询问已有的简历/岗位
            if ctx is not None:
                ctx_info = []
                if ctx.resume_id:
                    ctx_info.append(f"- 当前简历 ID: {ctx.resume_id}")
                if ctx.job_id:
                    ctx_info.append(f"- 当前岗位 ID: {ctx.job_id}")
                if ctx.personal_info:
                    ctx_info.append(f"- 用户提供的个人信息: {ctx.personal_info[:200]}")
                if ctx_info:
                    prompt += "\n\n## 当前上下文（已由前端传入，无需再次询问）\n" + "\n".join(ctx_info)
                    prompt += "\n调用子 Agent 时请直接传入这些 ID。"
            messages = [SystemMessage(content=prompt)] + list(messages)

        tool_defs = tool_registry.get_function_definitions()
        response: AIMessage = invoke_llm_with_tools(messages, tool_defs)
        return {"messages": messages + [response]}

    # ── router：LLM 是否调用工具 ──

    def router(state: PipelineState):
        messages = state["messages"]
        if not messages:
            return "__end__"
        last_message = messages[-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"
        return "__end__"

    # ── tools_node：执行子 Agent 调用 ──

    async def tools_node(state: PipelineState) -> dict[str, Any]:
        messages = state["messages"]
        context = state["context"]
        user_id = state["user_id"]

        last_message = messages[-1]
        if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
            return {}

        tool_messages: list[ToolMessage] = []

        for tool_call in last_message.tool_calls:
            tool_name = tool_call.get("name", "")
            tool_args = tool_call.get("args", {})
            tool_call_id = tool_call.get("id", "")

            logger.info("[Coordinator] 委派任务给 %s args=%s", tool_name, tool_args)

            tool = tool_registry.get(tool_name)
            if tool is None:
                result = {"success": False, "error": f"未知子 Agent: {tool_name}"}
            else:
                try:
                    inject_args = dict(tool_args)
                    inject_args.setdefault("user_id", user_id)
                    if context.resume_id:
                        inject_args.setdefault("resume_id", context.resume_id)
                    if context.job_id:
                        inject_args.setdefault("job_id", context.job_id)

                    tool_result = await tool.execute(**inject_args)
                    result = {
                        "success": tool_result.success,
                        "data": tool_result.data,
                        "error": tool_result.error,
                    }
                except Exception as exc:
                    logger.error("[Coordinator] 子 Agent 执行异常: %s", exc)
                    result = {"success": False, "error": str(exc)}

            if result["success"] and result.get("data"):
                context.record_result(tool_name, result["data"])

            tool_messages.append(
                ToolMessage(
                    content=json.dumps(result, ensure_ascii=False),
                    tool_call_id=tool_call_id,
                    name=tool_name,
                )
            )

            logger.info("[Coordinator] %s 完成: success=%s", tool_name, result["success"])

        return {"messages": messages + tool_messages, "context": context}

    # ── 构建图 ──

    workflow = StateGraph(PipelineState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tools_node)
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", router, {"tools": "tools", "__end__": END})
    workflow.add_edge("tools", "agent")

    return workflow.compile()
