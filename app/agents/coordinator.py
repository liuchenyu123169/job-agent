"""Coordinator Agent — ReAct 调度者，把子 Agent 当成工具来调用。

核心设计：
  - Coordinator 本身是一个 ReAct agent（复用 app/copilot/graph.py 的图结构）
  - 其 "工具" 是子 Agent（SubAgent 实例），通过 agent_registry 管理
  - System prompt 告诉 LLM：你是协调者，把任务委派给专业子 Agent

与单 Agent 的区别：
  - 单 Agent：8 个原子工具平铺 → LLM 决策难度高、prompt 长
  - Coordinator：3 个子 Agent 工具 → LLM 先想"该委派给谁"，子 Agent 内部自行执行

面试考点：
  - 为什么子 Agent 用 pipeline 不用 ReAct？→ 确定性任务不需要反复推理
  - 为什么 Coordinator 用 ReAct？→ 任务分解本身是推理密集型，需要动态决策
  - Agent 间通信格式？→ 结构化 dict（success/data/error），不传原始 LLM 文本
"""

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from app.agents.base import SubAgent
from app.agents.registry import agent_registry
from app.copilot.state import PipelineState
from app.core.llm import invoke_llm_with_tools

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
1. 如果「当前上下文」已包含 resume_id / job_id，直接调用子 Agent，不要再问用户。只有缺失时才询问
2. 用户说"没有偏好"/"随便"/"都行" → 直接用已有信息执行，不要追问
3. 每个子 Agent 调用完检查返回的 success 字段
4. 用中文回复
5. 汇报时用具体数据（匹配分数、问题数量），不要泛泛而谈
6. **如果用户表达了多个意图，必须委派所有相关的子 Agent，不要只做一个**
"""


# ═══════════════════════════════════════════════════════════════
# 子 Agent → OpenAI function-calling 格式生成
# ═══════════════════════════════════════════════════════════════

def _agent_to_function_def(agent: SubAgent) -> dict:
    """将 SubAgent 转为 OpenAI function-calling 格式的工具定义。

    不再创建 ToolDefinition 对象，也不注册到 tool_registry。
    Coordinator 内部直接使用此格式。
    """
    return {
        "type": "function",
        "function": {
            "name": agent.name,
            "description": agent.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "resume_id": {"type": "integer", "description": "简历 ID"},
                    "job_id": {"type": "integer", "description": "岗位 ID"},
                    "goal": {"type": "string", "description": "子任务描述，告诉子 Agent 要做什么"},
                },
                "required": ["resume_id", "job_id"],
            },
        },
    }


def _get_agent_function_defs() -> list[dict]:
    """从 agent_registry 生成所有已注册 Agent 的 function-calling 定义。"""
    return [_agent_to_function_def(a) for a in agent_registry.list_all()]


# ═══════════════════════════════════════════════════════════════
# Coordinator ReAct Graph（结构与 copilot/graph.py 一致）
# ═══════════════════════════════════════════════════════════════

def create_coordinator_graph(sub_agents: list[SubAgent]):
    """构建 Coordinator 的 ReAct 循环图。

    Args:
        sub_agents: 子 Agent 列表，用于日志输出（实际调度走 agent_registry）

    Returns:
        编译后的 LangGraph StateGraph
    """
    # 确保子 Agent 都在 agent_registry 中注册（幂等）
    for agent in sub_agents:
        agent_registry.register(agent)

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

        # 从 agent_registry 生成 function definitions（不再污染 tool_registry）
        tool_defs = _get_agent_function_defs()
        response: AIMessage = invoke_llm_with_tools(messages, tool_defs, model_key="fast")
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

    # ── tools_node：直接调用子 Agent ──

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

            agent = agent_registry.get(tool_name)
            if agent is None:
                result = {"success": False, "error": f"未知子 Agent: {tool_name}"}
            else:
                try:
                    inject_args = dict(tool_args)
                    inject_args.setdefault("user_id", user_id)
                    if context.resume_id:
                        inject_args.setdefault("resume_id", context.resume_id)
                    if context.job_id:
                        inject_args.setdefault("job_id", context.job_id)

                    # 直接调 agent.run_stream_async()，不再通过 Tool 包装
                    agent_result = await agent.run_stream_async(
                        goal=str(inject_args.pop("goal", f"执行 {tool_name}")),
                        resume_id=int(inject_args.get("resume_id", 0)),
                        job_id=int(inject_args.get("job_id", 0)),
                        user_id=int(inject_args.get("user_id", user_id)),
                        # Coordinator 路径不需要 SSE token 推送
                        on_step=None,
                        on_token=None,
                    )
                    result = {
                        "success": agent_result["success"],
                        "data": agent_result.get("data"),
                        "error": agent_result.get("error"),
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
