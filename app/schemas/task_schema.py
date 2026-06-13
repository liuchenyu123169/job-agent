from pydantic import BaseModel
from typing import Any

class TaskResponse(BaseModel):
    id: int
    task_type: str
    resume_id: int | None = None
    job_id: int | None = None
    input_json: dict[str, Any] | None = None
    output_json: dict[str, Any] | None = None
    status: str
    error_log: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
