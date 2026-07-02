"""LLM 调用层 — 委托 ModelProvider 实现，保持向后兼容的函数签名。

新代码请直接使用 model_provider.invoke() / model_provider.stream()，
并传入 model_key 按任务类型路由模型。
"""

import logging
from typing import Any, AsyncGenerator

from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI

from app.ai.model_provider import model_provider

logger = logging.getLogger(__name__)

# ── 向后兼容的函数（内部委托 model_provider） ──


def invoke_llm(prompt: str, *, model_key: str | None = None) -> str:
    """纯文本 LLM 调用。新代码请传 model_key。"""
    return model_provider.invoke(prompt, model_key=model_key)


async def stream_llm(prompt: str, *, model_key: str | None = None) -> AsyncGenerator[str, None]:
    """异步流式 LLM 调用。新代码请传 model_key。"""
    async for token in model_provider.stream(prompt, model_key=model_key):
        yield token


def bind_tools_to_llm(
    tool_definitions: list[dict[str, Any]],
    model_key: str | None = None,
) -> ChatOpenAI:
    """将工具定义绑定到 LLM，返回支持 function-calling 的模型。"""
    return model_provider.bind_tools(tool_definitions, model_key=model_key)


def invoke_llm_with_tools(
    messages: list[BaseMessage],
    tool_definitions: list[dict[str, Any]],
    *,
    model_key: str | None = None,
) -> AIMessage:
    """带工具调用的 LLM 请求。新代码请传 model_key。"""
    return model_provider.invoke_with_tools(
        messages, tool_definitions, model_key=model_key
    )
