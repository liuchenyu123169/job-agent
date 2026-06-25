"""CacheManager — Redis 缓存层，统一管理 LLM / RAG 结果缓存。

设计：
  - 缓存未命中 → 执行 compute_fn → 写 Redis → 返回
  - 缓存命中 → 直接返回
  - Redis 不可用 → 降级直通（不抛异常）
  - Key 包含 prompt_version / model_name / rag_hash，参数变化自动破缓存
"""

import hashlib
import json
import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "")


def get_redis_settings():
    """从 REDIS_URL 解析出 arq/RedisSettings 需要的 host + port。

    统一口径：全项目只配 REDIS_URL，不单独配 REDIS_HOST / REDIS_PORT。
    """
    url = REDIS_URL
    host, port = "localhost", 6379
    if url:
        # redis://host:port/db → host:port
        try:
            no_scheme = url.split("://")[1] if "://" in url else url
            host_part = no_scheme.split("/")[0]
            if ":" in host_part:
                host, port_str = host_part.rsplit(":", 1)
                port = int(port_str)
            else:
                host = host_part
        except Exception:
            pass
    return host, port


class _NoopRedis:
    """Redis 不可用时的空实现，所有操作返回 None（等于永远 miss）。"""

    async def get(self, _key: str) -> bytes | None:
        return None

    async def setex(self, _key: str, _ttl: int, _value: str) -> None:
        pass

    async def delete(self, _key: str) -> None:
        pass

    async def ping(self) -> bool:
        return False


class CacheManager:
    """统一缓存接口。

    用法:
        from app.infra.cache import cache_manager

        key = cache_manager.key("llm", "match_analyze", resume_hash, job_hash, version, model)
        result = await cache_manager.get_or_compute(key, ttl=1800, compute_fn=actual_call)
    """

    def __init__(self) -> None:
        self._redis = None
        self._ready = False

    async def _ensure_client(self):
        """延迟初始化 Redis 连接（自动重试降级状态）。"""
        if self._ready:
            return
        if not REDIS_URL:
            if self._redis is None:
                logger.info("[Cache] REDIS_URL not set, caching disabled")
            self._redis = _NoopRedis()
            return
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(REDIS_URL, socket_connect_timeout=2)
            await self._redis.ping()
            self._ready = True
            logger.info("[Cache] Redis connected: %s", REDIS_URL)
        except Exception as exc:
            if not self._ready:
                logger.warning("[Cache] Redis unavailable (%s), caching disabled", exc)
            self._redis = _NoopRedis()

    @staticmethod
    def key(*parts: str) -> str:
        """生成缓存 key。任意参数变化 → key 不同 → 自动 miss。"""
        raw = "|".join(str(p) for p in parts if p)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    async def get_or_compute(
        self,
        key: str,
        ttl: int = 1800,
        compute_fn: Callable | None = None,
    ) -> Any:
        """读取缓存，未命中则执行 compute_fn 并回写。

        Args:
            key: 缓存 key
            ttl: 过期时间（秒），默认 30 分钟
            compute_fn: 缓存未命中时的计算函数（async callable）

        Returns:
            缓存数据或 compute_fn 的返回值
        """
        await self._ensure_client()

        # 命中
        try:
            cached = await self._redis.get(key)
            if cached:
                logger.debug("[Cache] hit: %s", key)
                return json.loads(cached)
        except Exception as exc:
            logger.warning("[Cache] get failed: %s", exc)

        # miss
        if compute_fn is None:
            return None

        logger.debug("[Cache] miss: %s", key)
        value = await compute_fn()

        # 回写
        try:
            await self._redis.setex(
                key, ttl,
                json.dumps(value, ensure_ascii=False, default=str),
            )
        except Exception as exc:
            logger.warning("[Cache] setex failed: %s", exc)

        return value

    async def invalidate(self, key: str) -> None:
        """主动删除缓存。"""
        await self._ensure_client()
        try:
            await self._redis.delete(key)
        except Exception as exc:
            logger.warning("[Cache] delete failed: %s", exc)

    @property
    def ready(self) -> bool:
        return self._ready


# 全局单例
cache_manager = CacheManager()
