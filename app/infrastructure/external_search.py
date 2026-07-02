"""External public search service with cleaning, deduplication, and normalization.

Phase 1 止血：增加三级过滤（bigram 相关性 + 域名分级 + snippet 质量），
纯规则，不调 LLM，不增加延迟。
"""

import logging
import re
from typing import Any

from app.infrastructure.bocha.client import BochaClient
from app.infrastructure.bocha.models import PublicSearchResult, SearchHit
from app.shared.text_utils import min_relevance_signal

logger = logging.getLogger(__name__)

_client: BochaClient | None = None

# ── 域名策略：仅招聘/岗位类查询启用路径级过滤 ──

_JOB_QUERY_PATTERNS = [
    r'岗位', r'招聘', r'JD', r'要求', r'职位', r'薪资',
    r'面试', r'笔试', r'入职', r'校招', r'社招', r'内推',
]

_LOW_SIGNAL_PATHS: list[tuple[str, str]] = [
    (r'zhihu\.com/question/', '知乎问题页'),
    (r'zhihu\.com/answer/',   '知乎回答页'),
    (r'douyin\.com/',         '抖音'),
    (r'xiaohongshu\.com/',    '小红书'),
    (r'kuaishou\.com/',       '快手'),
]


def _is_job_query(query: str) -> bool:
    """检查 query 是否属于招聘/岗位类查询。"""
    return any(re.search(p, query) for p in _JOB_QUERY_PATTERNS)


def _filter_domain(url: str, query: str) -> bool:
    """返回 True=保留。仅对招聘类查询启用路径级域名过滤。"""
    if not _is_job_query(query):
        return True
    url_lower = url.lower()
    for pattern, _label in _LOW_SIGNAL_PATHS:
        if re.search(pattern, url_lower):
            return False
    return True


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

    cleaned = _clean_and_dedup(raw_result.hits, max_items=top_k, query=query)

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


def _clean_and_dedup(
    hits: list[SearchHit],
    max_items: int = 5,
    query: str = "",
) -> list[SearchHit]:
    """去重 + 域名过滤 + bigram 相关性 + snippet 质量 → 清洗后的结果列表。"""
    seen_urls: set[str] = set()
    cleaned: list[SearchHit] = []

    for hit in hits:
        # ── 0. 空标题跳过 ──
        if not hit.title.strip():
            continue

        # ── 1. URL 规范化去重 ──
        norm_url = _normalize_url(hit.url)
        if norm_url in seen_urls:
            continue
        seen_urls.add(norm_url)

        # ── 2. 域名过滤（仅招聘类 query 生效）──
        if not _filter_domain(hit.url, query):
            logger.debug("[ExternalSearch] domain filtered: %s → %s", query[:40], hit.url[:60])
            continue

        # ── 3. Snippet 质量底线 ──
        hit.snippet = _truncate(hit.snippet, 500)
        if not _snippet_has_min_quality(hit.snippet):
            logger.debug("[ExternalSearch] low-quality snippet dropped: %s", hit.title[:60])
            continue

        # ── 4. Bigram 相关性粗滤（只拦完全无关的）──
        if query and not min_relevance_signal(query, hit.title, hit.snippet):
            logger.debug("[ExternalSearch] relevance filtered: query=%s title=%s",
                         query[:40], hit.title[:60])
            continue

        hit.title = _truncate(hit.title, 200)
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


def _snippet_has_min_quality(snippet: str) -> bool:
    """检查 snippet 是否有最低信息量。

    规则：
    - < 15 字符 → 拒绝（大概率是占位符）
    - 有效汉字+英文单词占比 < 30% → 拒绝（乱码/全是标点/特殊字符）
    """
    if not snippet:
        return True  # 没有 snippet 不是致命问题，放行
    if len(snippet) < 15:
        return False
    # 有效字符：汉字 + 英文单词 + 数字
    valid = len(re.findall(r'[一-鿿]', snippet)) + len(re.findall(r'[a-zA-Z0-9]', snippet))
    total = len(snippet)
    if total > 0 and valid / total < 0.30:
        return False
    return True


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
