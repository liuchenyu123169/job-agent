from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.db.crud import get_task_by_id, list_agent_tasks
from app.schemas.task_schema import TaskListResponse, TaskResponse

router = APIRouter(prefix="/api/task", tags=["Task"])


@router.get("", response_model=TaskListResponse)
def list_tasks(
    task_type: str | None = None,
    resume_id: int | None = None,
    job_id: int | None = None,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
) -> TaskListResponse:
    items = list_agent_tasks(
        task_type=task_type,
        resume_id=resume_id,
        job_id=job_id,
        limit=limit,
        user_id=int(current_user["id"]),
    )
    return TaskListResponse(items=[TaskResponse(**item) for item in items])


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: int,
    current_user: dict = Depends(get_current_user),
) -> TaskResponse:
    task = get_task_by_id(task_id, user_id=int(current_user["id"]))
    if task is None:
        raise HTTPException(status_code=404, detail="任务未找到")
    return TaskResponse(**task)
