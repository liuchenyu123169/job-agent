"""外部岗位采集 service — HTTP 直抓 + LLM 提取结构化字段。"""

import asyncio
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.ai.llm import invoke_llm
from app.ai.prompt_engine import PromptManager

logger = logging.getLogger(__name__)

_prompt_manager = PromptManager(version="v1")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


async def fetch_job_page(url: str) -> dict[str, Any]:
    """直抓 URL → 提取 HTML 文本 → LLM 提取结构化岗位字段。

    Returns:
        {"source_url": ..., "company": ..., "job_title": ..., "location": ...,
         "salary": ..., "raw_text": ..., "text": "..."}
    """
    # Step 1: HTTP GET
    html = await _fetch_html(url)
    if not html:
        return _empty_result(url, "无法获取页面内容")

    # Step 2: 提取纯文本（去标签、脚本、样式）
    text = _extract_text(html)

    if len(text) < 100:
        return _empty_result(url, f"页面内容过短 ({len(text)} 字符)，可能被反爬")

    # Step 3: LLM 直接解析原始 HTML（保留标签结构，方便定位内容）
    structured = await _llm_extract_fields(url, html[:20000])

    # 构建可读 text
    text_lines = ["# 岗位页面采集结果", ""]
    if structured.get("company"):
        text_lines.append(f"**公司**: {structured['company']}")
    if structured.get("job_title"):
        text_lines.append(f"**岗位**: {structured['job_title']}")
    if structured.get("location"):
        text_lines.append(f"**地点**: {structured['location']}")
    if structured.get("salary"):
        text_lines.append(f"**薪资**: {structured['salary']}")
    text_lines.append("")
    text_lines.append(f"**来源**: {url}")
    text_lines.append("")
    text_lines.append("## JD 内容")
    text_lines.append(structured.get("jd_text", text[:3000]))

    return {
        "task_id": None,
        "source_url": url,
        "page_title": structured.get("job_title", ""),
        "company": structured.get("company", ""),
        "job_title": structured.get("job_title", ""),
        "location": structured.get("location", ""),
        "salary": structured.get("salary", ""),
        "published_at": structured.get("published_at", ""),
        "raw_text": structured.get("jd_text", text),
        "text": "\n".join(text_lines),
    }


async def _fetch_html(url: str) -> str:
    """HTTP GET，返回 HTML 文本。"""
    headers = {"User-Agent": _USER_AGENT, "Accept": "text/html"}
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, trust_env=False) as client:
            resp = await client.get(url, headers=headers)
            logger.info("[JobFetch] status=%s url=%s len=%s", resp.status_code, url[:80], len(resp.text))
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        logger.exception("[JobFetch] HTTP error: %s", exc)
        return ""


def _extract_text(html: str) -> str:
    """从 HTML 提取文本。SPA 页面内容在 script 标签中，一并提取。"""
    try:
        soup = BeautifulSoup(html, "html.parser")

        # 1. 提取可见文本
        for tag in soup(["style", "nav", "footer", "header", "noscript", "meta", "link"]):
            tag.decompose()
        visible = soup.get_text(separator="\n")

        # 2. 提取 script 标签中的 JSON 数据（SPA 内容在这里）
        script_parts = []
        for s in soup.find_all("script"):
            content = s.string or ""
            if content and len(content) > 200:
                # 解码 Unicode 转义
                decoded = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), content)
                script_parts.append(decoded)

        text = visible + "\n" + "\n".join(script_parts)
        text = re.sub(r"\n\s*\n+", "\n", text)
        return text.strip()
    except Exception:
        text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()


def _find_jd_sections(text: str) -> str:
    """从 SPA 噪声文本中定位 JD 相关片段。"""
    markers = ["职位描述", "职位要求", "岗位职责", "任职要求", "岗位描述", "Responsibilities", "Qualifications"]

    # 找每个 marker 的位置
    positions = []
    for m in markers:
        idx = text.find(m)
        if idx >= 0:
            positions.append((idx, m))

    if not positions:
        # 没找到 marker → 取前 8000 字符（包含页面标题等可见内容）
        return text[:8000]

    positions.sort()

    # 围绕每个 marker 取上下文
    parts = [text[:500]]  # 页面头部（标题等）
    for idx, marker in positions:
        start = max(0, idx - 200)
        end = min(len(text), idx + 3000)
        parts.append(f"--- {marker} ---\n{text[start:end]}")

    return "\n".join(parts)


async def _llm_extract_fields(url: str, text: str) -> dict[str, str]:
    """调 LLM 从页面文本中提取结构化岗位字段。"""
    prompt = _prompt_manager.render(
        "extract_job_fields",
        url=url,
        page_text=text,
    )
    try:
        response = await asyncio.to_thread(invoke_llm, prompt, model_key="primary")
        return _parse_llm_json(response)
    except Exception as exc:
        logger.exception("[JobFetch] LLM extraction failed: %s", exc)
        return {"jd_text": text}


def _parse_llm_json(response: str) -> dict[str, str]:
    """解析 LLM 返回的 JSON。拒收纯 JSON 噪音（SPA 数据回显）。"""
    import json as _json

    def _is_noise(data: dict) -> bool:
        """检测是否 LLM 把 SPA 原始数据当结果返回了。"""
        jd = str(data.get("jd_text", ""))
        # SPA 噪音特征：含大量反斜杠转义、tenant_info、jindouyunConfig 等
        noise_markers = ["tenant_info", "jindouyunConfig", "\\\\\\", "{\\\\"]
        return any(m in jd for m in noise_markers)

    for candidate in [_try_parse(response)]:
        if candidate and not _is_noise(candidate):
            return candidate

    return {"jd_text": response}


def _try_parse(text: str) -> dict[str, str] | None:
    import json as _json
    for strategy in [
        lambda t: _json.loads(t.strip()),
        lambda t: _json.loads(re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.DOTALL).group(1)),
        lambda t: _json.loads(re.search(r"\{.*\}", t, re.DOTALL).group(0)),
    ]:
        try:
            return strategy(text)
        except (Exception, AttributeError):
            continue
    return None


def _empty_result(url: str, error: str = "") -> dict[str, Any]:
    return {
        "task_id": None,
        "source_url": url,
        "page_title": "",
        "company": "",
        "job_title": "",
        "location": "",
        "salary": "",
        "published_at": "",
        "raw_text": "",
        "text": f"# 岗位页面采集结果\n\n采集失败: {error}",
        "error": error,
    }


async def create_temp_job_from_fetch(fetch_data: dict[str, Any], user_id: int) -> int | None:
    raw_text = str(fetch_data.get("raw_text") or "")
    job_title = str(fetch_data.get("job_title") or "")
    company = str(fetch_data.get("company") or "")

    if not raw_text or len(raw_text) < 50:
        return None

    job_name = f"{company} - {job_title}" if company and job_title else (job_title or "外部岗位")
    try:
        from app.infrastructure.db.crud import insert_job
        return await asyncio.to_thread(insert_job, company=company or None, title=job_name[:200], jd_text=raw_text[:5000], user_id=user_id)
    except Exception as exc:
        logger.exception("[JobFetch] create temp job failed: %s", exc)
        return None
