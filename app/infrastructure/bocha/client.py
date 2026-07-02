"""博查公开搜索 Client — HTTP 请求 + 响应解析。"""

import logging
from typing import Any

import httpx

from app.shared.config import BOCHA_BASE_URL, BOCHA_SEARCH_PATH, BOCHA_TIMEOUT_SECONDS
from app.infrastructure.bocha.models import PublicSearchResult, SearchHit

logger = logging.getLogger(__name__)


def _extract_items(data: dict[str, Any]) -> list:
    """从 Bocha data 字典中提取结果列表。

    支持: {"webPages": {"value": [...]}}, {"webPages": [...]}, {"list": [...]} 等
    """
    for field in ("webPages", "pages", "list", "items", "results", "documents", "records"):
        val = data.get(field)
        if val is None:
            continue
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            inner = val.get("value") or val.get("items") or val.get("results") or val.get("list")
            if isinstance(inner, list):
                return inner
    return []


class BochaClient:
    """博查公开搜索 API 客户端。"""

    def __init__(self) -> None:
        self._base_url = BOCHA_BASE_URL.rstrip("/")
        self._timeout = BOCHA_TIMEOUT_SECONDS

    async def search(self, query: str, top_k: int = 5) -> PublicSearchResult:
        from app.shared.config import BOCHA_API_KEY as _key
        api_key = _key
        logger.info("[Bocha] key_len=%s base_url=%s", len(api_key), self._base_url)
        if not api_key:
            raise ValueError("BOCHA_API_KEY 未配置，请在 .env 中设置")

        url = f"{self._base_url}{BOCHA_SEARCH_PATH}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {"query": query, "top_k": top_k}

        logger.info("[Bocha] search query=%s top_k=%s", query[:60], top_k)

        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        logger.info("[Bocha] response keys=%s status_code=%s", list(data.keys()), response.status_code)
        return self._parse_response(query, data)

    def _parse_response(self, query: str, raw: dict[str, Any]) -> PublicSearchResult:
        hits: list[SearchHit] = []

        data_raw = raw.get("data")
        if isinstance(data_raw, dict):
            items = _extract_items(data_raw)
        elif isinstance(data_raw, list):
            items = data_raw
        else:
            items = raw.get("results") or raw.get("items") or raw.get("result") or []

        if not items:
            logger.warning(
                "[Bocha] no items. data_keys=%s preview=%s",
                list(data_raw.keys()) if isinstance(data_raw, dict) else "N/A",
                str(data_raw)[:200] if data_raw else "EMPTY",
            )

        for item in items:
            if isinstance(item, dict):
                hits.append(SearchHit(
                    title=str(item.get("name") or item.get("title") or "").strip(),
                    url=str(item.get("url") or "").strip(),
                    snippet=str(item.get("snippet") or item.get("summary") or "").strip(),
                    source=str(item.get("source") or item.get("from") or "").strip(),
                    published_at=str(item.get("published_at") or item.get("date") or "").strip(),
                ))

        return PublicSearchResult(
            query=query,
            hits=hits,
            total_count=len(hits),
            raw=raw,
        )
