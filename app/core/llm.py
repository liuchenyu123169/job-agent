"""LLM 调用层 — 支持纯文本调用和带工具的 function-calling 调用。"""

import logging
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI

from app.core.config import MODEL_NAME, ZHIPU_BASE_URL, get_api_key

logger = logging.getLogger(__name__)


def _build_llm(temperature: float = 0.7) -> ChatOpenAI:
    """构建 LLM 实例（统一配置入口）。"""
    return ChatOpenAI(
        api_key=get_api_key(),
        base_url=ZHIPU_BASE_URL,
        model=MODEL_NAME,
        temperature=temperature,
    )


def invoke_llm(prompt: str) -> str:
    """纯文本 LLM 调用，返回字符串响应。"""
    llm = _build_llm()
    response = llm.invoke(prompt)
    return str(response.content)


def bind_tools_to_llm(tool_definitions: list[dict[str, Any]]) -> ChatOpenAI:
    """将工具定义绑定到 LLM 实例，生成支持 function-calling 的模型。"""
    llm = _build_llm(temperature=0.5)
    # 将 OpenAI function-calling 格式转换为 LangChain tool 格式
    langchain_tools = [_langchain_tool_from_definition(td) for td in tool_definitions]
    return llm.bind_tools(langchain_tools)


def invoke_llm_with_tools(
    messages: list[BaseMessage],
    tool_definitions: list[dict[str, Any]],
) -> AIMessage:
    """带工具调用的 LLM 请求，返回 AIMessage（可能包含 tool_calls）。

    返回的 AIMessage 中：
    - 如果 LLM 决定调用工具，message.tool_calls 不为空
    - 如果 LLM 给出最终回复，message.content 有文本内容
    """
    llm_with_tools = bind_tools_to_llm(tool_definitions)
    response = llm_with_tools.invoke(messages)
    return response


# ── 将 OpenAI function-calling 格式转为 LangChain tool 格式 ──

def _langchain_tool_from_definition(tool_def: dict[str, Any]) -> dict[str, Any]:
    """将 OpenAI 格式的工具定义转为 LangChain bind_tools 接受的格式。

    输入格式（来自 ToolDefinition.to_openai_function）：
        {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}

    输出格式（LangChain bind_tools 接受）：
        {"name": "...", "description": "...", "parameters": {...}}
    """
    func = tool_def.get("function", tool_def)
    return {
        "name": func["name"],
        "description": func.get("description", ""),
        "parameters": func.get("parameters", {"type": "object", "properties": {}}),
    }
