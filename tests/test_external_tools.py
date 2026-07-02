import pytest

from app.tools.fetch_job_page_tool import fetch_job_page_execute
from app.tools.public_search_tool import public_search_execute


@pytest.mark.anyio
async def test_public_search_tool_returns_fail_on_service_error(monkeypatch):
    async def _fake_search(**kwargs):
        return {"items": [], "count": 0, "error": "missing api key"}

    monkeypatch.setattr(
        "app.services.external_search_service.public_search",
        _fake_search,
    )

    result = await public_search_execute(query="字节跳动 APM")

    assert result.success is False
    assert result.error == "missing api key"


@pytest.mark.anyio
async def test_fetch_job_page_tool_returns_fail_on_service_error(monkeypatch):
    async def _fake_fetch(**kwargs):
        return {"raw_text": "", "error": "fetch failed"}

    monkeypatch.setattr(
        "app.services.external_job_service.fetch_job_page",
        _fake_fetch,
    )

    result = await fetch_job_page_execute(url="https://example.com/job")

    assert result.success is False
    assert result.error == "fetch failed"
