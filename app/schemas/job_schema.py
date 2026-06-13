from pydantic import BaseModel

class JobCreateRequest(BaseModel):
    company: str | None = None
    title: str
    jd_text: str

class JobCreateResponse(BaseModel):
    job_id: int

class JobResponse(BaseModel):
    id: int
    company: str | None = None
    title: str
    jd_text: str
    parsed_json: str | None = None
    created_at: str | None = None