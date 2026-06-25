import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

from fastapi import FastAPI
from app.api.middleware import RequestIdMiddleware
from app.api.auth_api import router as auth_router
from app.api.agent_api import router as agent_router
from app.api.knowledge_api import router as knowledge_router
from app.api.resume_api import router as resume_router
from app.api.job_api import router as job_router
from app.api.copilot_api import router as copilot_router
from app.api.admin_api import router as admin_router
from app.api.evaluation_api import router as evaluation_router
from app.api.task_api import router as task_router
from app.api.tasks_api import router as bg_task_router
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import check_jwt_secret
from app.db.database import init_db

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

app.add_middleware(RequestIdMiddleware)

app.include_router(agent_router)
app.include_router(auth_router)
app.include_router(knowledge_router)
app.include_router(resume_router)
app.include_router(job_router)
app.include_router(copilot_router)
app.include_router(evaluation_router)
app.include_router(task_router)
app.include_router(bg_task_router)
app.include_router(admin_router)

# Prometheus 指标暴露（/metrics 端点）
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app)
except ImportError:
    logging.getLogger(__name__).warning(
        "prometheus-fastapi-instrumentator 未安装，/metrics 端点不可用"
    )


@app.on_event("startup")
def on_startup() -> None:
    check_jwt_secret()
    init_db()
    # 构建 Skill 参考嵌入向量（供意图识别 embedding fallback 使用）
    try:
        from app.skills.intent_classifier import build_skill_embeddings
        from app.skills.registry import skill_registry
        build_skill_embeddings(skill_registry.list_all())
    except Exception:
        logging.getLogger(__name__).warning("Skill embeddings 构建失败，intent embedding fallback 将不可用", exc_info=True)


@app.get("/health")
def health(title="JobAgent API"):
    return {"status": "ok"}


@app.get("/api/admin/metrics")
def get_metrics():
    """返回内存中的可观测性指标摘要。"""
    from app.observability.metrics import metrics
    return metrics.summary()
