from fastapi import APIRouter, HTTPException
from app.db.crud import get_job_by_id, insert_job
from app.schemas.job_schema import (
    JobCreateRequest,
    JobCreateResponse,
    JobResponse,
)

router = APIRouter(prefix="/api/job", tags=["Job"])

@router.post("", response_model=JobCreateResponse)
def create_job(job: JobCreateRequest) -> JobCreateResponse:
    job_id = insert_job(job.company, job.title, job.jd_text)
    return JobCreateResponse(job_id=job_id)

@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int) -> JobResponse:
    job = get_job_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(**job)
