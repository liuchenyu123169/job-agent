from pydantic import BaseModel

class JobCreateRequest(BaseModel):
    company: str | None = None
    title: str
    jd_text: str

class JobCreateResponse(BaseModel):
    job_id: int
    local_job_id: int

class JobResponse(BaseModel):
    id: int
    local_job_id: int | None = None
    company: str | None = None
    title: str
    jd_text: str
    parsed_json: str | None = None
    created_at: str | None = None


class JobListItem(BaseModel):
    id: int
    local_job_id: int | None = None
    company: str | None = None
    title: str
    jd_preview: str
    created_at: str | None = None


class JobListResponse(BaseModel):
    items: list[JobListItem]
