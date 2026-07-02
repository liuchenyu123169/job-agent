"""八爪鱼页面采集 Client — MCP SSE 协议。"""

import json
import logging
from typing import Any

import httpx

from app.shared.config import BAZHUA_BASE_URL, BAZHUA_TIMEOUT_SECONDS
from app.infrastructure.bazhua.models import ExternalJobPage

logger = logging.getLogger(__name__)


def _parse_sse_body(text: str) -> dict[str, Any]:
    """解析 MCP SSE 响应: event: message\\ndata: {...} → 提取 JSON。"""
    for line in text.split("\n"):
        if line.startswith("data: "):
            return json.loads(line[6:])
    # fallback: 普通 JSON
    return json.loads(text)


class BazhuaClient:
    """八爪鱼 MCP 客户端 — initialize → tools/call。"""

    def __init__(self) -> None:
        self._base_url = BAZHUA_BASE_URL.rstrip("/")
        self._timeout = BAZHUA_TIMEOUT_SECONDS
        self._session_id: str | None = None
        self._api_key: str = ""
        self._request_id = 1

    async def _ensure_session(self) -> None:
        if self._session_id:
            return

        from app.shared.config import BAZHUA_API_KEY as _key
        self._api_key = _key
        if not self._api_key:
            raise ValueError("BAZHUA_API_KEY 未配置")

        headers = {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "job-agent", "version": "1.0.0"},
                "capabilities": {},
            },
            "id": self._request_id,
        }
        self._request_id += 1

        logger.info("[Bazhua] initialize...")
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            resp = await client.post(self._base_url, json=payload, headers=headers)
            logger.info("[Bazhua] init status=%s", resp.status_code)
            resp.raise_for_status()

            sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
            if not sid:
                data = _parse_sse_body(resp.text)
                sid = data.get("result", {}).get("sessionId")
            if not sid:
                raise RuntimeError(f"MCP initialize 未返回 session ID, body={resp.text[:300]}")

            self._session_id = sid
            logger.info("[Bazhua] session=%s", sid)

    async def fetch_job_page(self, url: str) -> ExternalJobPage:
        await self._ensure_session()

        headers = {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": self._session_id,
        }
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "fetch_web_page",
                "arguments": {"url": url},
            },
            "id": self._request_id,
        }
        self._request_id += 1

        logger.info("[Bazhua] tools/call url=%s", url[:80])
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            resp = await client.post(self._base_url, json=payload, headers=headers)
            logger.info("[Bazhua] tools/call status=%s body=%s", resp.status_code, resp.text[:600])
            resp.raise_for_status()
            data = _parse_sse_body(resp.text)

        return self._parse_response(url, data)

    def _parse_response(self, url: str, raw: dict[str, Any]) -> ExternalJobPage:
        result = raw.get("result", {})
        content_items = result.get("content") or raw.get("content") or []

        text_parts = []
        for item in content_items:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))

        result_text = "\n".join(text_parts) if text_parts else str(raw)

        return ExternalJobPage(
            source_url=url,
            page_title="",
            raw_text=result_text,
            company="",
            job_title="",
            location="",
            salary="",
            published_at="",
            raw=raw,
        )
