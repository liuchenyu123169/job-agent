from pydantic import BaseModel


class ResumeCreateRequest(BaseModel):
    file_name: str
    content: str


class ResumeCreateResponse(BaseModel):
    resume_id: int


class ResumeResponse(BaseModel):
    id: int
    file_name: str
    content: str
    parsed_json: str | None = None
    created_at: str | None = None
