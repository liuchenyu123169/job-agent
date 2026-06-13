from fastapi import APIRouter, HTTPException

from app.db.crud import get_resume_by_id, insert_resume
from app.schemas.resume_schema import (
    ResumeCreateRequest,
    ResumeCreateResponse,
    ResumeResponse,
)

router = APIRouter(prefix="/api/resume", tags=["Resume"])


@router.post("", response_model=ResumeCreateResponse)
def create_resume(payload: ResumeCreateRequest) -> ResumeCreateResponse:
    resume_id = insert_resume(payload.file_name, payload.content)
    return ResumeCreateResponse(resume_id=resume_id)


@router.get("/{resume_id}", response_model=ResumeResponse)
def get_resume(resume_id: int) -> ResumeResponse:
    resume = get_resume_by_id(resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    return ResumeResponse(**resume)
