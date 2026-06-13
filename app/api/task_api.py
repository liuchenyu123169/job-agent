from fastapi import APIRouter, HTTPException
from app.db.crud import insert_agent_task, get_task_by_id
from app.schemas.task_schema import TaskResponse

router = APIRouter(prefix="/api/task", tags=["Task"])

@router.get("/", response_model=TaskResponse)
def get_tast(task_id: int) -> TaskResponse:
    task = get_task_by_id(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse(**task)
