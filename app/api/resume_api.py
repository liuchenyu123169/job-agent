from fastapi import APIRouter, File, HTTPException, UploadFile

from app.db.crud import get_resume_by_id, insert_resume
from app.schemas.resume_schema import (
    ResumeCreateRequest,
    ResumeCreateResponse,
    ResumeResponse,
    ResumeUploadResponse,
)
from app.utils.resume_parser import parse_resume_file

router = APIRouter(prefix="/api/resume", tags=["Resume"])


@router.post("", response_model=ResumeCreateResponse)
def create_resume(payload: ResumeCreateRequest) -> ResumeCreateResponse:
    resume_id = insert_resume(payload.file_name, payload.content)
    return ResumeCreateResponse(resume_id=resume_id)


@router.post("/upload", response_model=ResumeUploadResponse)
async def upload_resume(file: UploadFile = File(...)) -> ResumeUploadResponse:
    try:
        file_bytes = await file.read()
        content = parse_resume_file(file_bytes, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Failed to parse resume file") from exc

    file_name = file.filename or "uploaded_resume"
    resume_id = insert_resume(file_name, content)
    return ResumeUploadResponse(
        resume_id=resume_id,
        file_name=file_name,
        content_preview=content[:200],
    )


@router.get("/{resume_id}", response_model=ResumeResponse)
def get_resume(resume_id: int) -> ResumeResponse:
    resume = get_resume_by_id(resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    return ResumeResponse(**resume)

