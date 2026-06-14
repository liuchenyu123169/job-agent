from pydantic import BaseModel
from typing import Any

class TaskResponse(BaseModel):
    id: int
    task_type: str
    resume_id: int | None = None
    job_id: int | None = None
    input_json: dict[str, Any] | str | None = None
    output_json: dict[str, Any] | str | None = None
    status: str
    error_msg: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
