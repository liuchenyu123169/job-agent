"""Agent Run API — 任务推进状态的 CRUD 端点。

与 copilot_session 的职责分离：
  - copilot_session: "聊过什么"（对话历史）
  - agent_run:       "任务做到哪了"（任务推进状态）
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.infrastructure.db.crud import (
    create_agent_run,
    get_agent_run,
    list_agent_runs,
    update_agent_run,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-runs", tags=["Agent Runs"])


class AgentRunUpdateRequest(BaseModel):
    """PATCH /api/agent-runs/{run_id} 的请求体。所有字段可选，仅更新传入的非 None 字段。"""
    status: str | None = Field(default=None, description="任务状态: created/planning/running/blocked/verifying/completed/failed")
    goal_type: str | None = Field(default=None, description="任务类型: prepare/compare/optimize/review/plan")
    plan_steps: list[dict] | None = Field(default=None, description="计划步骤列表")
    current_step: str | None = Field(default=None, description="当前正在执行的 step id")
    completed_steps: list[str] | None = Field(default=None, description="已完成的 step id 列表")
    pending_steps: list[str] | None = Field(default=None, description="待执行的 step id 列表")
    failed_steps: list[str] | None = Field(default=None, description="失败的 step id 列表")
    blockers: list[dict] | None = Field(default=None, description="阻塞项列表")
    next_action: str | None = Field(default=None, description="下一步行动描述")
    acceptance_criteria: list[str] | None = Field(default=None, description="验收标准列表")
    verification_results: list[dict] | None = Field(default=None, description="验收结果列表")
    replan_count: int | None = Field(default=None, description="重规划次数")
    final_report: str | None = Field(default=None, description="最终输出报告")
    next_suggestions: list[str] | None = Field(default=None, description="下一步建议列表")
    task_ids: list[int] | None = Field(default=None, description="关联的 agent_task ID 列表")


@router.post("")
def create_run(
    goal: str = Query(..., min_length=1, description="用户目标描述"),
    goal_type: str = Query(..., min_length=1, description="任务类型: prepare/compare/optimize/review/plan"),
    session_id: int | None = Query(default=None, description="关联的会话 ID（可选）"),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """创建新的 agent_run 记录。

    返回完整的 agent_run 行（dict），初始 status 为 'created'。
    """
    user_id = int(current_user["id"])
    logger.info("Creating agent_run: user=%d goal_type=%s goal=%s", user_id, goal_type, goal[:80])
    return create_agent_run(
        goal=goal,
        goal_type=goal_type,
        user_id=user_id,
        session_id=session_id,
    )


@router.get("")
def list_runs(
    limit: int = Query(default=20, ge=1, le=100, description="返回条数上限"),
    status: str | None = Query(default=None, description="按状态筛选"),
    goal_type: str | None = Query(default=None, description="按任务类型筛选"),
    session_id: int | None = Query(default=None, description="按会话 ID 筛选"),
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """列出当前用户的 agent_run 历史，按创建时间倒序。"""
    user_id = int(current_user["id"])
    return list_agent_runs(
        user_id=user_id,
        limit=limit,
        status=status,
        goal_type=goal_type,
        session_id=session_id,
    )


@router.get("/{run_id}")
def get_run(
    run_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """查询单个 agent_run 的完整详情。"""
    user_id = int(current_user["id"])
    run = get_agent_run(run_id, user_id=user_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run 未找到")
    return run


@router.patch("/{run_id}")
def update_run(
    run_id: int,
    body: AgentRunUpdateRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """部分更新 agent_run。仅更新请求体中传入的非 None 字段。

    支持更新状态、计划步骤、阻塞项、验收结果、最终报告等。
    """
    user_id = int(current_user["id"])

    # 先确认记录存在且属于当前用户
    existing = get_agent_run(run_id, user_id=user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Agent run 未找到")

    logger.info("Updating agent_run: id=%d fields=%s", run_id,
                 [k for k, v in body.model_dump().items() if v is not None])

    updated = update_agent_run(
        run_id=run_id,
        user_id=user_id,
        status=body.status,
        goal_type=body.goal_type,
        plan_steps=body.plan_steps,
        current_step=body.current_step,
        completed_steps=body.completed_steps,
        pending_steps=body.pending_steps,
        failed_steps=body.failed_steps,
        blockers=body.blockers,
        next_action=body.next_action,
        acceptance_criteria=body.acceptance_criteria,
        verification_results=body.verification_results,
        replan_count=body.replan_count,
        final_report=body.final_report,
        next_suggestions=body.next_suggestions,
        task_ids=body.task_ids,
    )
    if updated is None:
        raise HTTPException(status_code=500, detail="更新失败")
    return updated
