"""请求链路追踪 — contextvars 传递 trace_id/request_id，装饰器自动记录 span。

用法:
    from app.shared.observability import traced

    @traced("llm_call")
    def invoke_llm(prompt: str) -> str:
        ...
    自动记录 span 名称、耗时、metadata（通过 return 或 trace_metadata 上下文设置）。
"""

import logging
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── contextvars（线程安全 + 异步安全） ──
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
span_stack: ContextVar[list[dict]] = ContextVar("span_stack", default=[])


def get_request_id() -> str:
    return request_id_var.get()


def get_trace_id() -> str:
    return trace_id_var.get()


def get_current_spans() -> list[dict]:
    return list(span_stack.get())


def set_request_context(request_id: str = "", trace_id: str = "") -> None:
    """由中间件在请求开始时调用，注入 request_id 和 trace_id。"""
    if request_id:
        request_id_var.set(request_id)
    if trace_id:
        trace_id_var.set(trace_id)
    else:
        trace_id_var.set(str(uuid.uuid4())[:8])
    span_stack.set([])


@dataclass
class SpanContext:
    """装饰器内部使用的 span 上下文管理器。"""
    name: str
    start_time: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)

    def stop(self) -> dict[str, Any]:
        duration_ms = round((time.monotonic() - self.start_time) * 1000, 2)
        span = {
            "span_id": str(uuid.uuid4())[:8],
            "name": self.name,
            "duration_ms": duration_ms,
            "metadata": dict(self.metadata),
        }
        # 追加到当前请求的 span 栈
        spans = list(span_stack.get())
        spans.append(span)
        span_stack.set(spans)
        return span


# 当前活跃的 span 上下文（用于在 traced 函数内部追加 metadata）
_active_span: ContextVar[SpanContext | None] = ContextVar("_active_span", default=None)


def add_trace_metadata(key: str, value: Any) -> None:
    """在 traced 函数内部调用，向当前 span 追加 metadata。"""
    ctx = _active_span.get()
    if ctx is not None:
        ctx.metadata[key] = value


def traced(span_name: str):
    """装饰器：自动记录被装饰函数的耗时和调用的 span。

    Args:
        span_name: span 名称，如 "llm_call", "rag_search"

    用法:
        @traced("llm_call")
        def invoke_llm(prompt: str) -> str:
            add_trace_metadata("prompt_chars", len(prompt))
            return response
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            ctx = SpanContext(name=span_name)
            token = _active_span.set(ctx)
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                span = ctx.stop()
                _active_span.reset(token)
                rid = request_id_var.get()
                tid = trace_id_var.get()
                logger.info(
                    "[%s][%s] span=%s duration=%.2fms meta=%s",
                    rid, tid, span["name"], span["duration_ms"], span["metadata"],
                )
        return wrapper
    return decorator
