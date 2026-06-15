from pydantic import BaseModel


class ResumeCreateRequest(BaseModel):
    file_name: str
    content: str


class ResumeCreateResponse(BaseModel):
    resume_id: int
    local_resume_id: int


class ResumeUploadResponse(BaseModel):
    resume_id: int
    local_resume_id: int
    file_name: str
    content_preview: str


class ResumeResponse(BaseModel):
    id: int
    local_resume_id: int | None = None
    file_name: str
    content: str
    parsed_json: str | None = None
    created_at: str | None = None


class ResumeListItem(BaseModel):
    id: int
    local_resume_id: int | None = None
    file_name: str
    content_preview: str
    created_at: str | None = None


class ResumeListResponse(BaseModel):
    items: list[ResumeListItem]
