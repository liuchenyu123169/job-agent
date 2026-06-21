"""LLM 调用层 — 支持纯文本调用和带工具的 function-calling 调用。"""

import logging
from typing import Any, AsyncGenerator

from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI

from app.core.config import MODEL_NAME, ZHIPU_BASE_URL, get_api_key
from app.observability import StructuredLogger, metrics, traced
from app.observability.tracer import add_trace_metadata

logger = logging.getLogger(__name__)


def _build_llm(temperature: float = 0.7) -> ChatOpenAI:
    """构建 LLM 实例（统一配置入口）。"""
    return ChatOpenAI(
        api_key=get_api_key(),
        base_url=ZHIPU_BASE_URL,
        model=MODEL_NAME,
        temperature=temperature,
    )


def _extract_token_usage(response: AIMessage) -> dict[str, int]:
    """从 LangChain AIMessage.response_metadata 提取真实 token_usage。"""
    meta = getattr(response, "response_metadata", {}) or {}
    usage = meta.get("token_usage", {})
    return {
        "tokens_in": usage.get("prompt_tokens", 0),
        "tokens_out": usage.get("completion_tokens", 0),
    }


@traced("llm_call")
def invoke_llm(prompt: str) -> str:
    """纯文本 LLM 调用，返回字符串响应。自动记录耗时和 token 用量。"""
    llm = _build_llm()
    response = llm.invoke(prompt)
    content = str(response.content)

    usage = _extract_token_usage(response)
    add_trace_metadata("model", MODEL_NAME)
    add_trace_metadata("prompt_chars", len(prompt))
    add_trace_metadata("response_chars", len(content))
    add_trace_metadata("tokens_in", usage["tokens_in"])
    add_trace_metadata("tokens_out", usage["tokens_out"])

    # 使用字符级估算兜底
    tokens_in = usage["tokens_in"] or len(prompt) // 3
    tokens_out = usage["tokens_out"] or len(content) // 3

    StructuredLogger.log_llm_call(
        model=MODEL_NAME,
        duration_ms=0,  # traced 装饰器已记录，这里用 0 避免重复
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        prompt_chars=len(prompt),
        response_chars=len(content),
    )
    metrics.record_llm_call(
        model=MODEL_NAME,
        duration_ms=0,  # traced 已单独记录
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    return content


def bind_tools_to_llm(tool_definitions: list[dict[str, Any]]) -> ChatOpenAI:
    """将工具定义绑定到 LLM 实例，生成支持 function-calling 的模型。"""
    llm = _build_llm(temperature=0.5)
    # 将 OpenAI function-calling 格式转换为 LangChain tool 格式
    langchain_tools = [_langchain_tool_from_definition(td) for td in tool_definitions]
    return llm.bind_tools(langchain_tools)


@traced("llm_call_with_tools")
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

    usage = _extract_token_usage(response)
    total_chars = sum(len(str(m.content or "")) for m in messages)
    tokens_in = usage["tokens_in"] or total_chars // 3
    tokens_out = usage["tokens_out"] or len(str(response.content or "")) // 3
    add_trace_metadata("model", MODEL_NAME)
    add_trace_metadata("tokens_in", tokens_in)
    add_trace_metadata("tokens_out", tokens_out)
    metrics.record_llm_call(model=MODEL_NAME, duration_ms=0, tokens_in=tokens_in, tokens_out=tokens_out)
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

async def stream_llm(prompt: str) -> AsyncGenerator[str, None]:
    """逐 token 流式返回 LLM 输出"""
    llm = _build_llm()
    async for chunk in llm.astream(prompt):
        content = chunk.content
        if isinstance(content, str) and content:
            yield content