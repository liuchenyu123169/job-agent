"""可观测性模块 — 结构化日志、请求链路追踪、内存指标聚合。

组件:
  - StructuredLogger: JSON 格式日志，统一携带 request_id / trace_id
  - traced: 装饰器，自动记录 span 耗时和 metadata
  - MetricsCollector: 内存指标（LLM 调用次数/延迟分位/Token 用量）
"""

from app.observability.logger import StructuredLogger
from app.observability.tracer import traced, get_trace_id, get_current_spans
from app.observability.metrics import metrics

__all__ = ["StructuredLogger", "traced", "get_trace_id", "get_current_spans", "metrics"]
