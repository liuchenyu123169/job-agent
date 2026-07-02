"""八爪鱼岗位采集 — 内部统一数据模型。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExternalJobPage:
    """从外部 URL 抓取的岗位页面。"""
    source_url: str
    page_title: str = ""
    raw_text: str = ""
    company: str = ""
    job_title: str = ""
    location: str = ""
    salary: str = ""
    published_at: str = ""
    raw: dict[str, Any] | None = None
