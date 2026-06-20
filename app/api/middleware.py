"""FastAPI 中间件 — 请求 ID 注入、请求耗时记录。"""

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.observability.logger import StructuredLogger
from app.observability.metrics import metrics
from app.observability.tracer import set_request_context


class RequestIdMiddleware(BaseHTTPMiddleware):
    """为每个 HTTP 请求生成或继承 request_id，注入 contextvars，记录请求耗时。

    行为：
    1. 从请求头 X-Request-Id 读取（如果前端传了）；否则生成一个新的
    2. 注入到 contextvars（所有下游 logger/tracer 自动继承）
    3. 写入响应头 X-Request-Id
    4. 请求结束时记录 JSON 格式日志
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())[:8]
        trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())[:8]
        set_request_context(request_id=request_id, trace_id=trace_id)

        t0 = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - t0) * 1000, 2)

        response.headers["X-Request-Id"] = request_id
        response.headers["X-Trace-Id"] = trace_id

        metrics.record_http(response.status_code)
        StructuredLogger.log_request(
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response
