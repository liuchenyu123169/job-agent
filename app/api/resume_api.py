from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import get_current_user
from app.infrastructure.db.crud import (
    get_resume_by_id,
    get_resume_by_local_id,
    insert_resume,
    list_resumes_for_user,
)
from app.shared.schemas.resume_schema import (
    ResumeCreateRequest,
    ResumeCreateResponse,
    ResumeListItem,
    ResumeListResponse,
    ResumeResponse,
    ResumeUploadResponse,
)
from app.shared.utils.resume_parser import parse_resume_file

router = APIRouter(prefix="/api/resume", tags=["Resume"])


@router.post("", response_model=ResumeCreateResponse)
def create_resume(
    payload: ResumeCreateRequest,
    current_user: dict = Depends(get_current_user),
) -> ResumeCreateResponse:
    resume_id = insert_resume(
        payload.file_name,
        payload.content,
        user_id=int(current_user["id"]),
    )
    resume = get_resume_by_id(resume_id, user_id=int(current_user["id"]))
    if resume is None:
        raise HTTPException(status_code=500, detail="简历创建后未找到")
    return ResumeCreateResponse(
        resume_id=resume_id,
        local_resume_id=int(resume["local_resume_id"]),
    )


@router.post("/upload", response_model=ResumeUploadResponse)
async def upload_resume(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
) -> ResumeUploadResponse:
    try:
        file_bytes = await file.read()
        content = parse_resume_file(file_bytes, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="简历文件解析失败") from exc

    file_name = file.filename or "uploaded_resume"
    resume_id = insert_resume(file_name, content, user_id=int(current_user["id"]))
    resume = get_resume_by_id(resume_id, user_id=int(current_user["id"]))
    if resume is None:
        raise HTTPException(status_code=500, detail="简历创建后未找到")
    return ResumeUploadResponse(
        resume_id=resume_id,
        local_resume_id=int(resume["local_resume_id"]),
        file_name=file_name,
        content_preview=content[:200],
    )


@router.get("", response_model=ResumeListResponse)
def list_resumes(current_user: dict = Depends(get_current_user)) -> ResumeListResponse:
    items = list_resumes_for_user(user_id=int(current_user["id"]))
    return ResumeListResponse(items=[ResumeListItem(**item) for item in items])


@router.get("/local/{local_resume_id}", response_model=ResumeResponse)
def get_resume_by_local(
    local_resume_id: int,
    current_user: dict = Depends(get_current_user),
) -> ResumeResponse:
    resume = get_resume_by_local_id(local_resume_id, user_id=int(current_user["id"]))
    if resume is None:
        raise HTTPException(status_code=404, detail="简历未找到")
    return ResumeResponse(**resume)


@router.get("/{resume_id}", response_model=ResumeResponse)
def get_resume(
    resume_id: int,
    current_user: dict = Depends(get_current_user),
) -> ResumeResponse:
    resume = get_resume_by_id(resume_id, user_id=int(current_user["id"]))
    if resume is None:
        raise HTTPException(status_code=404, detail="简历未找到")
    return ResumeResponse(**resume)
