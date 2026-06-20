from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.db.crud import (
    get_job_by_id,
    get_job_by_local_id,
    insert_job,
    list_jobs_for_user,
)
from app.schemas.job_schema import (
    JobCreateRequest,
    JobCreateResponse,
    JobListItem,
    JobListResponse,
    JobResponse,
)

router = APIRouter(prefix="/api/job", tags=["Job"])

@router.post("", response_model=JobCreateResponse)
def create_job(
    job: JobCreateRequest,
    current_user: dict = Depends(get_current_user),
) -> JobCreateResponse:
    job_id = insert_job(job.company, job.title, job.jd_text, user_id=int(current_user["id"]))
    created_job = get_job_by_id(job_id, user_id=int(current_user["id"]))
    if created_job is None:
        raise HTTPException(status_code=500, detail="岗位创建后未找到")
    return JobCreateResponse(job_id=job_id, local_job_id=int(created_job["local_job_id"]))


@router.get("", response_model=JobListResponse)
def list_jobs(current_user: dict = Depends(get_current_user)) -> JobListResponse:
    items = list_jobs_for_user(user_id=int(current_user["id"]), limit=100)
    return JobListResponse(items=[JobListItem(**item) for item in items])


@router.get("/local/{local_job_id}", response_model=JobResponse)
def get_job_by_local(
    local_job_id: int,
    current_user: dict = Depends(get_current_user),
) -> JobResponse:
    job = get_job_by_local_id(local_job_id, user_id=int(current_user["id"]))
    if job is None:
        raise HTTPException(status_code=404, detail="岗位未找到")
    return JobResponse(**job)

@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: int,
    current_user: dict = Depends(get_current_user),
) -> JobResponse:
    job = get_job_by_id(job_id, user_id=int(current_user["id"]))
    if job is None:
        raise HTTPException(status_code=404, detail="岗位未找到")
    return JobResponse(**job)
