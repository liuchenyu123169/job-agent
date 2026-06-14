from fastapi import FastAPI
from app.api.agent_api import router as agent_router
from app.api.knowledge_api import router as knowledge_router
from app.api.resume_api import router as resume_router
from app.api.job_api import router as job_router
from app.api.task_api import router as task_router
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent_router)
app.include_router(knowledge_router)
app.include_router(resume_router)
app.include_router(job_router)
app.include_router(task_router)



@app.get("/health")
def health(title="JobAgent API"):
    return {"status": "ok"}
