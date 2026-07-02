import pytest

from app.copilot.state import PipelineContext
from app.orchestration.orchestrator import ClosedLoopOrchestrator
from app.tools.base import ToolResult


@pytest.mark.anyio
async def test_execute_step_uses_planner_args(monkeypatch):
    orch = ClosedLoopOrchestrator()
    context = PipelineContext(goal="分析岗位", external_urls=["https://example.com/job"])

    captured = {}

    class _Tool:
        async def execute(self, **kwargs):
            captured.update(kwargs)
            return ToolResult.ok({"source_url": kwargs.get("url"), "raw_text": "x" * 80})

    monkeypatch.setattr(
        "app.orchestration.orchestrator.tool_registry.get",
        lambda name: _Tool(),
    )

    step = {
        "id": "step_1",
        "tool": "fetch_job_page",
        "args": {"url": "https://planner.example/job/1"},
    }

    result = await orch._execute_step(step, context, user_id=1)

    assert result["source_url"] == "https://planner.example/job/1"
    assert captured["url"] == "https://planner.example/job/1"


@pytest.mark.anyio
async def test_execute_step_generates_public_search_query_from_extra_context(monkeypatch):
    orch = ClosedLoopOrchestrator()
    context = PipelineContext(
        goal="帮我了解这个岗位",
        extra_context_text="腾讯 后端开发 岗位 技术栈",
    )

    captured = {}

    class _Tool:
        async def execute(self, **kwargs):
            captured.update(kwargs)
            return ToolResult.ok({"items": [{"title": "t", "url": "u"}], "count": 1})

    monkeypatch.setattr(
        "app.orchestration.orchestrator.tool_registry.get",
        lambda name: _Tool(),
    )

    step = {
        "id": "step_1",
        "tool": "public_search",
        "name": "搜索外部资料",
    }

    await orch._execute_step(step, context, user_id=1)

    assert captured["query"] == "腾讯 后端开发 岗位 技术栈"


def test_extract_json_available_on_orchestrator():
    orch = ClosedLoopOrchestrator()

    data = orch._extract_json('```json\n{"plan_steps":[{"id":"step_1"}]}\n```')

    assert data is not None
    assert data["plan_steps"][0]["id"] == "step_1"
