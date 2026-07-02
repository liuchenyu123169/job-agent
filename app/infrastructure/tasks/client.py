"""arq 客户端 — 从 API 层入队任务和查询结果。"""

import logging
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings

from app.infrastructure.cache.manager import get_redis_settings

logger = logging.getLogger(__name__)

_host, _port = get_redis_settings()

_settings = RedisSettings(
    host=_host,
    port=_port,
    conn_retries=0,          # 不重试
    conn_retry_delay=0,      # 不等
    conn_timeout=1,          # 1 秒超时
)
_pool = None
_disabled = False


async def _get_pool():
    global _pool, _disabled
    if _disabled:
        return None
    if _pool is None:
        try:
            _pool = await create_pool(_settings)
        except Exception:
            _disabled = True   # 永久降级，不再重试
            return None
    return _pool


async def enqueue(name: str, **kwargs) -> dict[str, Any] | None:
    """入队一个任务，返回 arq Job 信息。Redis 不可用时返回 None。"""
    pool = await _get_pool()
    if pool is None:
        return None
    job = await pool.enqueue_job(name, **kwargs)
    return {"task_id": job.job_id, "status": "queued"}


async def get_result(task_id: str) -> dict | None:
    """查询任务结果。"""
    pool = await _get_pool()
    if pool is None:
        return None
    job_info = await pool.get_job_result(task_id)
    if job_info is None:
        return None
    return {
        "task_id": task_id,
        "status": getattr(job_info, "status", "unknown"),
        "result": getattr(job_info, "result", None),
    }


async def get_progress(task_id: str) -> float | None:
    """查询任务进度（0~1）。"""
    pool = await _get_pool()
    if pool is None:
        return None
    try:
        job = await pool.get_job(task_id)
        if job is None:
            return None
        progress = await job.progress()
        return progress if progress is not None else 0.0
    except Exception:
        return None
