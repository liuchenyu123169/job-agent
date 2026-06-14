from fastapi import APIRouter, HTTPException

from app.db.crud import get_task_by_id, list_agent_tasks
from app.schemas.task_schema import TaskListResponse, TaskResponse

router = APIRouter(prefix="/api/task", tags=["Task"])


@router.get("", response_model=TaskListResponse)
def list_tasks(
    task_type: str | None = None,
    resume_id: int | None = None,
    job_id: int | None = None,
    limit: int = 20,
) -> TaskListResponse:
    items = list_agent_tasks(
        task_type=task_type,
        resume_id=resume_id,
        job_id=job_id,
        limit=limit,
    )
    return TaskListResponse(items=[TaskResponse(**item) for item in items])


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: int) -> TaskResponse:
    task = get_task_by_id(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse(**task)
