"""内存指标聚合器 — LLM 调用次数、延迟分位、Token 用量。

用法:
    from app.observability import metrics

    metrics.record_llm_call(model="glm-4-flash", duration_ms=1540, tokens_in=800, tokens_out=350)
    print(metrics.summary())
"""

import time
from collections import defaultdict
from typing import Any


class MetricsCollector:
    """线程不安全的内存指标聚合器（单进程使用，适合 SQLite 单写场景）。"""

    def __init__(self) -> None:
        self._started_at = time.time()
        self._llm_calls: list[dict] = []           # [{model, duration_ms, tokens_in, tokens_out}]
        self._rag_queries: list[dict] = []          # [{duration_ms, hit_count}]
        self._http_requests: dict[str, int] = defaultdict(int)  # {status_code: count}

    def record_llm_call(self, model: str, duration_ms: float, tokens_in: int, tokens_out: int) -> None:
        self._llm_calls.append({
            "model": model,
            "duration_ms": duration_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        })

    def record_rag_query(self, duration_ms: float, hit_count: int) -> None:
        self._rag_queries.append({"duration_ms": duration_ms, "hit_count": hit_count})

    def record_http(self, status: int) -> None:
        self._http_requests[str(status)] += 1

    def summary(self) -> dict[str, Any]:
        """返回当前累积指标的摘要。"""
        uptime_s = int(time.time() - self._started_at)

        # LLM 统计
        llm_total = len(self._llm_calls)
        llm_total_tokens = sum(c["tokens_in"] + c["tokens_out"] for c in self._llm_calls)
        llm_total_duration = sum(c["duration_ms"] for c in self._llm_calls)
        llm_p95 = _percentile([c["duration_ms"] for c in self._llm_calls], 95) if self._llm_calls else 0
        llm_p50 = _percentile([c["duration_ms"] for c in self._llm_calls], 50) if self._llm_calls else 0
        llm_by_model: dict[str, int] = defaultdict(int)
        for c in self._llm_calls:
            llm_by_model[c["model"]] += 1

        # RAG 统计
        rag_total = len(self._rag_queries)
        rag_avg_duration = sum(q["duration_ms"] for q in self._rag_queries) / rag_total if rag_total else 0
        rag_avg_hits = sum(q["hit_count"] for q in self._rag_queries) / rag_total if rag_total else 0

        return {
            "uptime_seconds": uptime_s,
            "llm": {
                "total_calls": llm_total,
                "total_tokens": llm_total_tokens,
                "total_duration_ms": llm_total_duration,
                "p50_ms": llm_p50,
                "p95_ms": llm_p95,
                "by_model": dict(llm_by_model),
            },
            "rag": {
                "total_queries": rag_total,
                "avg_duration_ms": round(rag_avg_duration, 1),
                "avg_hits": round(rag_avg_hits, 1),
            },
            "http": {
                "total_requests": sum(self._http_requests.values()),
                "by_status": dict(self._http_requests),
            },
        }

    def reset(self) -> None:
        self.__init__()


def _percentile(data: list[float], p: float) -> float:
    """计算百分位数（线性插值）。"""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100.0
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_data):
        return sorted_data[f] * (1 - c) + sorted_data[f + 1] * c
    return sorted_data[f]


# 全局单例
metrics = MetricsCollector()
