"""External public search service with cleaning, deduplication, and normalization."""

import logging
from typing import Any

from app.infrastructure.bocha.client import BochaClient
from app.infrastructure.bocha.models import PublicSearchResult, SearchHit

logger = logging.getLogger(__name__)

_client: BochaClient | None = None


def _get_client() -> BochaClient:
    global _client
    if _client is None:
        _client = BochaClient()
    return _client


async def public_search(query: str, top_k: int = 5) -> dict[str, Any]:
    """Execute public search and return normalized tool data."""
    client = _get_client()
    try:
        raw_result: PublicSearchResult = await client.search(query=str(query), top_k=int(top_k))
    except ValueError as exc:
        logger.warning("[ExternalSearch] config error: %s", exc)
        return _error_result(query, "config_error", "外部搜索 API Key 未配置", str(exc))
    except Exception as exc:
        logger.exception("[ExternalSearch] search failed: %s", exc)
        err_type = type(exc).__name__
        return _error_result(query, "external_unavailable", f"外部搜索服务不可用 ({err_type})，请稍后重试", str(exc))

    cleaned = _clean_and_dedup(raw_result.hits, max_items=top_k)

    if not cleaned:
        return _empty_result(query)

    text_lines = [f"# 搜索结果: {query}", ""]
    for i, hit in enumerate(cleaned, 1):
        text_lines.append(f"**{i}. [{hit.title}]({hit.url})**")
        if hit.snippet:
            text_lines.append(f"  {hit.snippet[:200]}")
        if hit.source:
            text_lines.append(f"  来源: {hit.source}")
        text_lines.append("")

    return {
        "task_id": None,
        "query": query,
        "items": [
            {
                "title": h.title,
                "url": h.url,
                "snippet": h.snippet,
                "source": h.source,
                "published_at": h.published_at,
            }
            for h in cleaned
        ],
        "count": len(cleaned),
        "text": "\n".join(text_lines),
    }


def _clean_and_dedup(hits: list[SearchHit], max_items: int = 5) -> list[SearchHit]:
    seen_urls: set[str] = set()
    cleaned: list[SearchHit] = []

    for hit in hits:
        if not hit.title.strip():
            continue
        hit.snippet = _truncate(hit.snippet, 500)
        hit.title = _truncate(hit.title, 200)
        norm_url = _normalize_url(hit.url)
        if norm_url in seen_urls:
            continue
        seen_urls.add(norm_url)
        cleaned.append(hit)
        if len(cleaned) >= max_items:
            break

    return cleaned


def _normalize_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if url.startswith("http://"):
        url = url.replace("http://", "https://", 1)
    return url.lower()


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _empty_result(query: str) -> dict[str, Any]:
    """搜索成功但无结果 — 不标记步骤失败，由 verifier 触发 replan。"""
    return {
        "task_id": None,
        "query": query,
        "items": [],
        "count": 0,
        "text": f"# 搜索结果: {query}\n\n搜索未返回结果，请尝试换一个搜索词。",
    }


def _error_result(query: str, error_type: str, user_message: str, detail: str = "") -> dict[str, Any]:
    """搜索不可用 — 标记步骤失败，触发 blocked（不触发 replan）。"""
    return {
        "task_id": None,
        "query": query,
        "items": [],
        "count": 0,
        "error": f"[{error_type}] {user_message}",
        "text": f"# 搜索结果: {query}\n\n**{user_message}**\n\n{detail}" if detail else f"# 搜索结果: {query}\n\n**{user_message}**",
    }
