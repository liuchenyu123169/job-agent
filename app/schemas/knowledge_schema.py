from typing import Optional

from pydantic import BaseModel


class KnowledgeBuildResponse(BaseModel):
    success: bool
    message: str
    file_count: int
    chunk_count: int


class KnowledgeSearchItem(BaseModel):
    content: str
    source: Optional[str] = None
    score: Optional[float] = None


class KnowledgeSearchResponse(BaseModel):
    query: str
    top_k: int
    items: list[KnowledgeSearchItem]
