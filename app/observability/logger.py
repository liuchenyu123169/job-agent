"""结构化日志 — 统一携带 request_id / trace_id，关键事件 JSON 格式输出。

用法:
    from app.observability import StructuredLogger

    StructuredLogger.log_llm_call(model="glm-4-flash", duration_ms=1540, tokens_in=800, tokens_out=350)
    StructuredLogger.log_rag_query(duration_ms=210, hit_count=5, query="Spring Boot 面试题")
    StructuredLogger.log_request(method="POST", path="/api/copilot/run", status=200, duration_ms=3400)
"""

import json
import logging
import time
from typing import Any

from app.observability.tracer import get_request_id, get_trace_id

logger = logging.getLogger("observability")

def _base_record(event: str, **fields: Any) -> dict[str, Any]:
    """构建基础日志记录，注入 request_id 和 trace_id。"""
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "event": event,
        "request_id": get_request_id(),
        "trace_id": get_trace_id(),
        **fields,
    }


class StructuredLogger:
    """结构化日志记录器 — 关键事件以 JSON 单行输出，便于日志采集系统解析。"""

    @staticmethod
    def log_llm_call(
        model: str = "",
        duration_ms: float = 0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        prompt_chars: int = 0,
        response_chars: int = 0,
    ) -> None:
        """记录 LLM 调用完成事件。"""
        record = _base_record("llm_call",
            model=model,
            duration_ms=duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            prompt_chars=prompt_chars,
            response_chars=response_chars,
        )
        logger.info(json.dumps(record, ensure_ascii=False))

    @staticmethod
    def log_rag_query(
        duration_ms: float = 0,
        hit_count: int = 0,
        query: str = "",
        candidate_k: int = 0,
    ) -> None:
        """记录 RAG 检索完成事件。"""
        record = _base_record("rag_query",
            duration_ms=duration_ms,
            hit_count=hit_count,
            query=query[:100],
            candidate_k=candidate_k,
        )
        logger.info(json.dumps(record, ensure_ascii=False))

    @staticmethod
    def log_request(
        method: str = "",
        path: str = "",
        status: int = 0,
        duration_ms: float = 0,
        user_id: int = 0,
    ) -> None:
        """记录 HTTP 请求完成事件。"""
        record = _base_record("http_request",
            method=method,
            path=path,
            status=status,
            duration_ms=duration_ms,
            user_id=user_id,
        )
        logger.info(json.dumps(record, ensure_ascii=False))

    @staticmethod
    def log_db_query(
        operation: str = "",
        duration_ms: float = 0,
        table: str = "",
    ) -> None:
        """记录慢数据库查询事件（>100ms 时自动触发）。"""
        record = _base_record("slow_db_query",
            operation=operation,
            duration_ms=duration_ms,
            table=table,
        )
        logger.warning(json.dumps(record, ensure_ascii=False))
