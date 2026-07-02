import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.api.deps import get_admin_user
from app.ai.rag.rag_service import build_knowledge_base, search_knowledge
from app.shared.schemas.knowledge_schema import (
    KnowledgeBuildResponse,
    KnowledgeSearchItem,
    KnowledgeSearchResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["Knowledge"])


def _build_knowledge_task() -> None:
    """后台任务：构建知识库。"""
    try:
        result = build_knowledge_base()
        logger.info("知识库构建完成: %d 文件, %d 分块", result["file_count"], result["chunk_count"])
    except Exception as exc:
        logger.exception("知识库构建失败: %s", exc)


@router.post("/build")
def build_knowledge(
    background_tasks: BackgroundTasks,
    _admin: dict = Depends(get_admin_user),
) -> dict:
    """触发知识库构建（后台异步执行）。

    立即返回 accepted 状态，实际构建在后台线程中运行。
    构建完成后结果写入 ChromaDB，可通过搜索接口验证。
    """
    background_tasks.add_task(_build_knowledge_task)
    return {"status": "accepted", "message": "知识库构建已开始，请稍后通过搜索验证结果"}


@router.get("/search", response_model=KnowledgeSearchResponse)
def search(
    query: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=20),
    _admin: dict = Depends(get_admin_user),
) -> KnowledgeSearchResponse:
    try:
        items = search_knowledge(query=query, top_k=top_k)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return KnowledgeSearchResponse(
        query=query,
        top_k=top_k,
        items=[KnowledgeSearchItem(**item) for item in items],
    )
