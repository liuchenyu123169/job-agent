"""后台任务 API — 入队、查状态、取结果。

使用方式：
  POST /api/tasks/eval/run          → 入队评测任务
  POST /api/tasks/rag/build         → 入队 RAG 重建
  POST /api/tasks/batch/analyze     → 入队批量分析
  GET  /api/tasks/{task_id}         → 查状态 + 进度
  GET  /api/tasks/{task_id}/result  → 查结果
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.infrastructure.tasks.client import enqueue, get_progress, get_result
from app.infrastructure.tasks.models import TaskStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])


# ── 入队端点 ──

@router.post("/eval/run")
async def eval_run(
    workflow: str = "match_analyze",
    llm_judge: bool = True,
    judge_samples: int = 3,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """入队评测任务。"""
    job = await enqueue(
        "app.infra.tasks.jobs.eval_run_job",
        workflow=workflow,
        llm_judge=llm_judge,
        judge_samples=judge_samples,
    )
    if job is None:
        raise HTTPException(status_code=503, detail="任务队列不可用（Redis 未连接）")
    logger.info("[Tasks] eval_run enqueued: %s workflow=%s", job["task_id"], workflow)
    return job


@router.post("/rag/build")
async def rag_build(
    knowledge_dir: str = "data/knowledge",
    current_user: dict = Depends(get_current_user),
) -> dict:
    """入队 RAG 知识库重建任务。"""
    job = await enqueue(
        "app.infra.tasks.jobs.build_rag_job",
        knowledge_dir=knowledge_dir,
    )
    if job is None:
        raise HTTPException(status_code=503, detail="任务队列不可用（Redis 未连接）")
    logger.info("[Tasks] rag_build enqueued: %s", job["task_id"])
    return job


@router.post("/batch/analyze")
async def batch_analyze(
    resume_id: int,
    job_ids: list[int],
    enable_rag: bool = True,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """入队批量匹配分析任务。"""
    job = await enqueue(
        "app.infra.tasks.jobs.batch_analyze_job",
        resume_id=resume_id,
        job_ids=job_ids,
        user_id=int(current_user["id"]),
        enable_rag=enable_rag,
    )
    if job is None:
        raise HTTPException(status_code=503, detail="任务队列不可用（Redis 未连接）")
    logger.info("[Tasks] batch_analyze enqueued: %s resume=%d jobs=%d", job["task_id"], resume_id, len(job_ids))
    return job


# ── 查询端点 ──

@router.get("/{task_id}")
async def task_status(task_id: str) -> dict:
    """查询任务状态和进度。"""
    progress = await get_progress(task_id)
    result_info = await get_result(task_id)

    response: dict = {"task_id": task_id, "progress": progress}
    if result_info:
        response["status"] = result_info.get("status", "unknown")
        if result_info.get("result"):
            response["result"] = result_info["result"]
    else:
        response["status"] = TaskStatus.QUEUED if progress is None else TaskStatus.RUNNING
    return response


@router.get("/{task_id}/result")
async def task_result(task_id: str) -> dict:
    """查询任务结果。"""
    result_info = await get_result(task_id)
    if result_info is None:
        raise HTTPException(status_code=404, detail="任务未找到或已过期")
    return result_info
