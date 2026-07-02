"""Copilot Graph — LangGraph ReAct 循环，LLM 自主决策工具调用链路。"""

import json
import logging
from typing import Any, Literal

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from app.shared.state import PipelineState
from app.application.copilot.system_prompt import SYSTEM_PROMPT
from app.ai.llm import invoke_llm_with_tools
from app.tools import tool_registry

logger = logging.getLogger(__name__)


# ──────────────────────── agent_node ────────────────────────

def agent_node(state: PipelineState) -> dict[str, Any]:
    """LLM 决策节点：分析对话历史，决定下一步调用哪个工具或给出最终回复。"""
    messages = state["messages"]

    # 首次调用时插入系统提示词作为第一条消息
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)

    tool_defs = tool_registry.get_function_definitions()
    response: AIMessage = invoke_llm_with_tools(messages, tool_defs, model_key="fast")

    return {"messages": messages + [response]}


# ──────────────────────── router ────────────────────────

def router(state: PipelineState) -> Literal["tools", "__end__"]:
    """路由判断：LLM 是否要求调用工具。"""
    messages = state["messages"]
    if not messages:
        return "__end__"

    last_message = messages[-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return "__end__"


# ──────────────────────── tools_node（async）────────────────────────

async def tools_node(state: PipelineState) -> dict[str, Any]:
    """工具执行节点（异步）：执行 LLM 请求的所有工具调用，将结果作为 ToolMessage 追加。"""
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

        logger.info("[Copilot] 执行工具: %s args=%s", tool_name, tool_args)

        tool = tool_registry.get(tool_name)
        if tool is None:
            result = {"success": False, "error": f"未知工具: {tool_name}"}
        else:
            try:
                # 注入 user_id 和已选定的资源 ID
                inject_args = dict(tool_args)
                inject_args.setdefault("user_id", user_id)
                if context.resume_id and "resume_id" in tool.parameters.get("properties", {}):
                    inject_args.setdefault("resume_id", context.resume_id)
                if context.job_id and "job_id" in tool.parameters.get("properties", {}):
                    inject_args.setdefault("job_id", context.job_id)

                tool_result = await tool.execute(**inject_args)
                result = {
                    "success": tool_result.success,
                    "data": tool_result.data,
                    "error": tool_result.error,
                }
            except Exception as exc:
                logger.error("[Copilot] 工具执行异常: %s", exc)
                result = {"success": False, "error": str(exc)}

        # 将执行结果记录到上下文
        if result["success"] and result.get("data"):
            context.record_result(tool_name, result["data"])

        # 构建 ToolMessage 返回给 LLM
        tool_messages.append(
            ToolMessage(
                content=json.dumps(result, ensure_ascii=False),
                tool_call_id=tool_call_id,
                name=tool_name,
            )
        )

        logger.info("[Copilot] 工具 %s 完成, success=%s", tool_name, result["success"])

    return {"messages": messages + tool_messages, "context": context}


# ──────────────────────── 构建 Graph ────────────────────────

def build_copilot_graph() -> StateGraph:
    """构建 Copilot ReAct 循环图。"""
    workflow = StateGraph(PipelineState)

    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tools_node)

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", router, {"tools": "tools", "__end__": END})
    workflow.add_edge("tools", "agent")

    return workflow.compile()


# 编译后的 Graph 实例
copilot_graph = build_copilot_graph()
