"""FastAPI 中间件 — 请求 ID 注入、请求耗时记录。

注意：这里使用纯 ASGI middleware 而非 BaseHTTPMiddleware。
BaseHTTPMiddleware 会把整个响应体读进内存再返回，这会破坏 StreamingResponse
（SSE 流式推送完全失效）。详见 Starlette 官方文档的警告。
"""

import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.shared.observability.logger import StructuredLogger
from app.shared.observability.metrics import metrics
from app.shared.observability.tracer import set_request_context


class RequestIdMiddleware:
    """纯 ASGI middleware — 不触碰响应体，不影响 StreamingResponse。

    行为：
    1. 从请求头 X-Request-Id 读取（如果前端传了）；否则生成一个新的
    2. 注入到 contextvars（所有下游 logger/tracer 自动继承）
    3. 写入响应头 X-Request-Id
    4. 请求结束时记录 JSON 格式日志
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id: str = ""
        trace_id: str = ""
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"x-request-id":
                request_id = header_value.decode()
            elif header_name == b"x-trace-id":
                trace_id = header_value.decode()

        if not request_id:
            request_id = str(uuid.uuid4())[:8]
        if not trace_id:
            trace_id = str(uuid.uuid4())[:8]

        set_request_context(request_id=request_id, trace_id=trace_id)

        t0 = time.monotonic()
        status_code: int = 0

        async def _send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
                headers: list[tuple[bytes, bytes]] = list(
                    message.get("headers", [])
                )
                headers.append((b"x-request-id", request_id.encode()))
                headers.append((b"x-trace-id", trace_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            duration_ms = round((time.monotonic() - t0) * 1000, 2)
            metrics.record_http(status_code)
            StructuredLogger.log_request(
                method=scope.get("method", ""),
                path=scope.get("path", ""),
                status=status_code,
                duration_ms=duration_ms,
            )
