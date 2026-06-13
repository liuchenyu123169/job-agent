from fastapi import FastAPI
from app.api.resume_api import router as resume_router
from app.api.job_api import router as job_router
from app.api.task_api import router as task_router

app = FastAPI()
app.include_router(resume_router)
app.include_router(job_router)
app.include_router(task_router)



@app.get("/health")
def health(title="JobAgent API"):
    return {"status": "ok"}
