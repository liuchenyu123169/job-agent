"""Orchestrator Precheck 单元测试 — 工具感知的前置条件检查。

测试 _precheck() 是否根据 plan_steps 中的工具 input_requirements
动态决定需要哪些输入，而不是硬编码要求 resume_id + job_id。
"""

import asyncio
import pytest
from unittest.mock import patch

from app.copilot.state import PipelineContext, TaskState
from app.orchestration.orchestrator import ClosedLoopOrchestrator

# ── DB 函数的 mock 目标路径（_precheck 内部通过 local import 引用） ──
_DB_RESUME = "app.db.crud.get_resume_by_id"
_DB_JOB = "app.db.crud.get_job_by_id"


def _make_context(resume_id=None, job_id=None):
    return PipelineContext(resume_id=resume_id, job_id=job_id)


def _make_task_state(plan_steps):
    ts = TaskState(goal="test", goal_type="prepare", goal_status="planning")
    ts.plan_steps = plan_steps
    return ts


class TestPrecheckSearchOnly:
    """计划只有 search_knowledge → 不需要 resume_id/job_id → 不阻塞。"""

    def test_search_only_no_resume_no_job(self):
        orch = ClosedLoopOrchestrator()
        context = _make_context(resume_id=None, job_id=None)
        task_state = _make_task_state([
            {"id": "step_1", "name": "搜索知识", "tool": "search_knowledge",
             "depends_on": [], "status": "pending"},
        ])

        # Mock DB calls — 不应该被调用（因为不需要 resume/job）
        with patch(_DB_RESUME) as mock_resume, \
             patch(_DB_JOB) as mock_job:
            result = asyncio.new_event_loop().run_until_complete(
                orch._precheck("goal", task_state, context, user_id=1)
            )

        mock_resume.assert_not_called()
        mock_job.assert_not_called()
        assert result.is_blocked() is False
        assert result.goal_status == "running"


class TestPrecheckNeedsResume:
    """计划有 match_analyze → 需要 resume_id → 缺失则阻塞。"""

    def test_missing_resume_blocks(self):
        orch = ClosedLoopOrchestrator()
        context = _make_context(resume_id=None, job_id=1)
        task_state = _make_task_state([
            {"id": "step_1", "name": "匹配分析", "tool": "match_analyze",
             "depends_on": [], "status": "pending"},
        ])

        with patch(_DB_JOB, return_value={"id": 1}), \
             patch(_DB_RESUME) as mock_resume:
            result = asyncio.new_event_loop().run_until_complete(
                orch._precheck("goal", task_state, context, user_id=1)
            )

        mock_resume.assert_not_called()  # 因为 context.resume_id 是 None，直接 block
        assert result.is_blocked() is True
        assert any("简历" in b.get("description", "") for b in result.blockers)

    def test_has_resume_passes(self):
        orch = ClosedLoopOrchestrator()
        context = _make_context(resume_id=1, job_id=1)
        task_state = _make_task_state([
            {"id": "step_1", "name": "匹配分析", "tool": "match_analyze",
             "depends_on": [], "status": "pending"},
        ])

        with patch(_DB_RESUME, return_value={"id": 1}), \
             patch(_DB_JOB, return_value={"id": 1}):
            result = asyncio.new_event_loop().run_until_complete(
                orch._precheck("goal", task_state, context, user_id=1)
            )

        assert result.is_blocked() is False


class TestPrecheckRecommendJobs:
    """推荐岗位只需要 resume_id，不需要 job_id。"""

    def test_recommend_no_job_ok(self):
        orch = ClosedLoopOrchestrator()
        context = _make_context(resume_id=1, job_id=None)  # 没有 job_id
        task_state = _make_task_state([
            {"id": "step_1", "name": "推荐岗位", "tool": "recommend_jobs",
             "depends_on": [], "status": "pending"},
        ])

        with patch(_DB_RESUME, return_value={"id": 1}), \
             patch(_DB_JOB) as mock_job:
            result = asyncio.new_event_loop().run_until_complete(
                orch._precheck("goal", task_state, context, user_id=1)
            )

        mock_job.assert_not_called()  # recommend_jobs 不需要 job_id
        assert result.is_blocked() is False

    def test_recommend_no_resume_blocks(self):
        orch = ClosedLoopOrchestrator()
        context = _make_context(resume_id=None, job_id=1)
        task_state = _make_task_state([
            {"id": "step_1", "name": "推荐岗位", "tool": "recommend_jobs",
             "depends_on": [], "status": "pending"},
        ])

        result = asyncio.new_event_loop().run_until_complete(
            orch._precheck("goal", task_state, context, user_id=1)
        )

        assert result.is_blocked() is True
        assert any("简历" in b.get("description", "") for b in result.blockers)


class TestPrecheckGenerateResume:
    """生成简历只需要 job_id。"""

    def test_generate_resume_no_resume_ok(self):
        orch = ClosedLoopOrchestrator()
        context = _make_context(resume_id=None, job_id=1)
        task_state = _make_task_state([
            {"id": "step_1", "name": "生成简历", "tool": "generate_resume",
             "depends_on": [], "status": "pending"},
        ])

        with patch(_DB_JOB, return_value={"id": 1}), \
             patch(_DB_RESUME) as mock_resume:
            result = asyncio.new_event_loop().run_until_complete(
                orch._precheck("goal", task_state, context, user_id=1)
            )

        mock_resume.assert_not_called()
        assert result.is_blocked() is False


class TestPrecheckListUtilityTools:
    """Utility 工具不需要任何输入。"""

    def test_list_resumes_only(self):
        orch = ClosedLoopOrchestrator()
        context = _make_context(resume_id=None, job_id=None)
        task_state = _make_task_state([
            {"id": "step_1", "name": "列出简历", "tool": "list_resumes",
             "depends_on": [], "status": "pending"},
        ])

        with patch(_DB_RESUME) as mock_resume, \
             patch(_DB_JOB) as mock_job:
            result = asyncio.new_event_loop().run_until_complete(
                orch._precheck("goal", task_state, context, user_id=1)
            )

        mock_resume.assert_not_called()
        mock_job.assert_not_called()
        assert result.is_blocked() is False
