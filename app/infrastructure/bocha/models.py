"""博查公开搜索 — 内部统一数据模型。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchHit:
    """单条搜索结果。"""
    title: str
    url: str
    snippet: str
    source: str = ""
    published_at: str = ""


@dataclass
class PublicSearchResult:
    """一次搜索的完整结果。"""
    query: str
    hits: list[SearchHit] = field(default_factory=list)
    total_count: int = 0
    raw: dict[str, Any] | None = None
