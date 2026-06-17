from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_admin_user
from app.rag.rag_service import build_knowledge_base, search_knowledge
from app.schemas.knowledge_schema import (
    KnowledgeBuildResponse,
    KnowledgeSearchItem,
    KnowledgeSearchResponse,
)


router = APIRouter(prefix="/api/knowledge", tags=["Knowledge"])


@router.post("/build", response_model=KnowledgeBuildResponse)
def build_knowledge(_admin: dict = Depends(get_admin_user)) -> KnowledgeBuildResponse:
    try:
        result = build_knowledge_base()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return KnowledgeBuildResponse(
        success=True,
        message="knowledge base built successfully",
        file_count=result["file_count"],
        chunk_count=result["chunk_count"],
    )


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
