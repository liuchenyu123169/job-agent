import logging
import re
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable

from app.core.constants import DEFAULT_USER_ID
from app.core.llm import invoke_llm, stream_llm
from langgraph.graph import END

from app.db.crud import get_job_by_id, get_resume_by_id, insert_agent_task, insert_task_traces
from app.observability import metrics
from app.prompt_engine import PromptManager
from app.rag.rag_service import search_knowledge

logger = logging.getLogger(__name__)

_step_callback: ContextVar = ContextVar("_step_callback", default=None)
_token_callback: ContextVar = ContextVar("_token_callback", default=None)


async def _stream_llm_with_callback(prompt: str):
    cb = _token_callback.get()
    buffer: list[str] = []
    async for token in stream_llm(prompt):
        buffer.append(token)
        if cb is not None:
            cb(token)
    return "".join(buffer)


def _trace_node(name: str, fn: Callable) -> Callable:
    def wrapper(state: dict) -> dict:
        t0 = time.monotonic()
        result = fn(state)
        dur = round((time.monotonic() - t0) * 1000, 2)
        spans = state.setdefault("trace_spans", [])
        spans.append({"name": name, "duration_ms": dur})
        cb = _step_callback.get()
        if cb is not None:
            cb(name, dur)
        return result

    wrapper.__name__ = fn.__name__
    return wrapper


_prompt_manager = PromptManager(version="v1")


def get_prompt_manager() -> PromptManager:
    return _prompt_manager




def analyze_resume_job(resume_content: str, job_jd: str) -> dict[str, Any]:
    prompt = _prompt_manager.render("match_analyze", resume_content=resume_content, job_jd=job_jd)
    raw_output = invoke_llm(prompt)
    return {"text": raw_output}


async def analyze_resume_job_async(resume_content: str, job_jd: str) -> dict[str, Any]:
    prompt = _prompt_manager.render(
        "match_analyze",
        resume_content=resume_content,
        job_jd=job_jd,
    )
    raw_output = await _stream_llm_with_callback(prompt)
    return {"text": raw_output}


def normalize_match_score(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, min(100, value))
    if isinstance(value, float):
        return max(0, min(100, int(round(value))))
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match:
            try:
                parsed = int(round(float(match.group(0))))
                return max(0, min(100, parsed))
            except ValueError:
                return 0
    return 0


def ensure_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def build_match_reason(
    analysis: dict[str, Any],
    advantages: list[str],
    weaknesses: list[str],
) -> str:
    raw_reason = analysis.get("match_reason")
    if isinstance(raw_reason, str) and raw_reason.strip():
        return raw_reason.strip()
    if advantages:
        if weaknesses:
            return f"优势集中在{advantages[0]}，但仍存在{weaknesses[0]}等差距。"
        return f"优势集中在{advantages[0]}，整体匹配度较好。"
    if weaknesses:
        return f"当前主要短板是{weaknesses[0]}。"
    return ""


def save_success_task(
    task_type: str,
    resume_id: int | None,
    job_id: int | None,
    output_data: dict[str, Any],
    input_data: dict[str, Any] | None = None,
    user_id: int = DEFAULT_USER_ID,
    trace_spans: list[dict] | None = None,
) -> int:
    metrics.record_task(task_type, "SUCCESS")
    return insert_agent_task(
        task_type=task_type,
        resume_id=resume_id,
        job_id=job_id,
        input_data=input_data or {"resume_id": resume_id, "job_id": job_id},
        output_data=output_data,
        status="SUCCESS",
        user_id=user_id,
        trace_spans=trace_spans,
    )


def save_failed_task(
    task_type: str,
    resume_id: int | None,
    job_id: int | None,
    error_msg: str,
    input_data: dict[str, Any] | None = None,
    output_data: dict[str, Any] | None = None,
    user_id: int = DEFAULT_USER_ID,
    trace_spans: list[dict] | None = None,
) -> int:
    metrics.record_task(task_type, "FAILED")
    logger.error("[TASK] %s failed: %s", task_type, error_msg)
    return insert_agent_task(
        task_type=task_type,
        resume_id=resume_id,
        job_id=job_id,
        input_data=input_data or {},
        output_data=output_data,
        status="FAILED",
        error_msg=error_msg,
        user_id=user_id,
        trace_spans=trace_spans,
    )


_TECH_TERM_RE = re.compile(r"\b([A-Z][a-zA-Z0-9+#.]{1,36})\b")
_CN_BRACKET_RE = re.compile(r"[《「【]([^》」】]+)[》」】]")
_SKIP_WORDS: set[str] = {
    "The", "A", "An", "I", "We", "You", "He", "She", "It", "They",
    "This", "That", "These", "Those", "Here", "There",
    "Is", "Are", "Was", "Were", "Be", "Been", "Being",
    "Can", "Will", "Would", "Could", "Should", "May", "Might", "Must",
    "Has", "Have", "Had", "Do", "Does", "Did",
    "In", "On", "At", "To", "For", "Of", "With", "By", "From",
    "And", "Or", "But", "Not", "No", "Yes", "If", "So",
    "All", "Each", "Any", "Some", "More", "Most",
    "One", "Two", "First", "Next", "Other",
    "About", "Also", "Just", "Only", "Very", "How", "What", "When",
    "Then", "Now", "Still", "Even", "Such", "Than", "Like",
}


def _rag_log(message: str) -> None:
    print(message, flush=True)
    logger.info(message)


def _extract_tech_terms(text: str) -> list[str]:
    source = text or ""
    terms: list[str] = []
    seen: set[str] = {"API", "SDK", "JDK", "JVM"}

    for match in _TECH_TERM_RE.finditer(source):
        word = match.group(1)
        if word in _SKIP_WORDS or word.lower() in _SKIP_WORDS:
            continue
        if word in seen:
            continue
        seen.add(word)
        terms.append(word)

    for match in _CN_BRACKET_RE.finditer(source):
        phrase = match.group(1).strip()
        if len(phrase) >= 2 and phrase not in seen:
            seen.add(phrase)
            terms.append(phrase)

    return terms


def _get_kb_source_names(knowledge_dir: str = "") -> list[str]:
    base = Path(knowledge_dir) if knowledge_dir else Path("data/knowledge")
    if not base.exists() or not base.is_dir():
        return []
    names: list[str] = []
    for fpath in sorted(base.rglob("*.md")):
        names.append(fpath.stem)
    for fpath in sorted(base.rglob("*.txt")):
        names.append(fpath.stem)
    return names


def _dedupe_key(item: dict[str, Any]) -> str:
    source = str(item.get("source") or "").strip()
    title = str(item.get("title") or "").strip()
    content = str(item.get("content") or "").strip()
    return f"{source}::{title or content[:50]}"


def retrieve_knowledge_node(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    if state.get("enable_rag") is False:
        _rag_log("[RAG][interview] skipped: enable_rag=false")
        return {
            "knowledge_context": "",
            "knowledge_used": False,
            "knowledge_count": 0,
            "rag_queries": [],
            "rag_hit_titles": [],
            "rag_hit_sources": [],
        }

    resume = state.get("resume") or {}
    job = state.get("job") or {}
    resume_content = str(resume.get("content", ""))
    job_jd = str(job.get("jd_text", ""))

    _rag_log("[RAG][interview] retrieve_knowledge_node started")

    job_terms = _extract_tech_terms(job_jd)
    resume_terms = _extract_tech_terms(resume_content)
    all_terms = list(dict.fromkeys(job_terms + resume_terms))

    _rag_log(f"[RAG] job_terms={job_terms}")
    _rag_log(f"[RAG] resume_terms={resume_terms}")

    if not all_terms:
        all_terms = ["核心技术", "面试"]

    combined_query = "面试题 " + " ".join(all_terms[:8])
    _rag_log(f"[RAG] combined_query={combined_query[:100]}")

    merged_items = search_knowledge(combined_query, top_k=30)
    _rag_log(f"[RAG] single_query hits={len(merged_items)}")

    if not merged_items:
        return {
            "knowledge_context": "",
            "knowledge_used": False,
            "knowledge_count": 0,
            "rag_queries": [combined_query],
            "rag_hit_titles": [],
            "rag_hit_sources": [],
        }

    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in merged_items:
        content = str(item.get("content") or "").strip()
        if len(content) < 40:
            continue
        key = _dedupe_key(item)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(dict(item))

    deduped.sort(key=lambda x: x.get("score") if x.get("score") is not None else 999.0)

    final_items: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    for item in deduped:
        if len(final_items) >= 5:
            break
        source = str(item.get("source") or "")
        if source_counts.get(source, 0) >= 2:
            continue
        final_items.append(item)
        source_counts[source] = source_counts.get(source, 0) + 1

    blocks: list[str] = []
    hit_titles: list[str] = []
    hit_sources: list[str] = []

    for index, item in enumerate(final_items, start=1):
        title = str(item.get("title") or "").strip()
        source = str(item.get("source") or "").strip()
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        _rag_log(f"[RAG] hit title={title or '<empty>'} source={source or '<empty>'} score={item.get('score')}")
        blocks.append(
            "\n".join([
                f"【知识片段 {index}】",
                f"标题：{title}",
                f"来源：{source}",
                f"内容：{content}",
            ])
        )
        hit_titles.append(title)
        hit_sources.append(source)

    if not blocks:
        _rag_log("[RAG] fallback: all items filtered out")
        return {
            "knowledge_context": "",
            "knowledge_used": False,
            "knowledge_count": 0,
            "rag_queries": [combined_query],
            "rag_hit_titles": [],
            "rag_hit_sources": [],
        }

    return {
        "knowledge_context": "\n\n".join(blocks),
        "knowledge_used": True,
        "knowledge_count": len(blocks),
        "rag_queries": [combined_query],
        "rag_hit_titles": hit_titles,
        "rag_hit_sources": hit_sources,
    }


def load_resume_node(state) -> dict[str, Any]:
    resume = get_resume_by_id(state["resume_id"], user_id=state["user_id"])
    if resume is None:
        return {"error_msg": "简历未找到"}
    return {"resume": resume}


def load_job_node(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    job = get_job_by_id(state["job_id"], user_id=state["user_id"])
    if job is None:
        return {"error_msg": "岗位未找到"}
    return {"job": job}


def build_prompt_node(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    prompt = get_prompt_manager().render(
        "match_analyze",
        resume_content=state["resume"]["content"],
        job_jd=state["job"]["jd_text"],
    )
    return {"prompt": prompt}


async def llm_analyze_node_async(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    analysis = await analyze_resume_job_async(
        resume_content=state["resume"]["content"],
        job_jd=state["job"]["jd_text"],
    )
    return {"analysis": analysis}


def parse_result_node(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    analysis = state.get("analysis") or {}
    return {"analysis_text": analysis.get("text", "") or ""}


def save_task_node(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    text = state.get("analysis_text") or ""
    task_id = save_success_task(
        task_type="MATCH_ANALYZE",
        resume_id=state["resume_id"],
        job_id=state["job_id"],
        output_data={"text": text[:2000]},
        input_data={
            "resume_id": state["resume_id"],
            "job_id": state["job_id"],
            "local_resume_id": (state.get("resume") or {}).get("local_resume_id"),
            "local_job_id": (state.get("job") or {}).get("local_job_id"),
        },
        user_id=state["user_id"],
        trace_spans=state.get("trace_spans", []),
    )
    insert_task_traces(task_id, state.get("trace_spans", []))
    return {"task_id": task_id, "analysis_text": text}


def build_optimize_prompt_node(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    prompt = get_prompt_manager().render(
        "resume_optimize",
        resume_content=state["resume"]["content"],
        job_jd=state["job"]["jd_text"],
    )
    return {"prompt": prompt}


async def llm_optimize_node_async(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    raw = await _stream_llm_with_callback(state["prompt"])
    return {"raw_output": raw}


def parse_optimization_node(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    return {"optimization_text": state.get("raw_output", "") or ""}


def save_optimize_task_node(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    text = state.get("optimization_text") or ""
    task_id = save_success_task(
        task_type="RESUME_OPTIMIZE",
        resume_id=state["resume_id"],
        job_id=state["job_id"],
        output_data={"text": text[:2000]},
        input_data={
            "resume_id": state["resume_id"],
            "job_id": state["job_id"],
            "local_resume_id": (state.get("resume") or {}).get("local_resume_id"),
            "local_job_id": (state.get("job") or {}).get("local_job_id"),
        },
        user_id=state["user_id"],
        trace_spans=state.get("trace_spans", []),
    )
    insert_task_traces(task_id, state.get("trace_spans", []))
    return {"task_id": task_id, "analysis_text": state.get("analysis_text"), "optimization_text": text}


def build_interview_questions_prompt_node(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    prompt = get_prompt_manager().render(
        "interview_questions",
        resume_content=state["resume"]["content"],
        job_jd=state["job"]["jd_text"],
        knowledge_context=state.get("knowledge_context") or "",
    )
    return {"prompt": prompt}


async def llm_generate_questions_node_async(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    raw_output = await _stream_llm_with_callback(state["prompt"])
    return {"raw_output": raw_output}


def parse_questions_node(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    return {"questions_text": state.get("raw_output", "") or ""}


def save_questions_task_node(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    text = state.get("questions_text") or ""
    task_id = save_success_task(
        task_type="INTERVIEW_QUESTIONS",
        resume_id=state["resume_id"],
        job_id=state["job_id"],
        output_data={"text": text[:2000]},
        input_data={
            "resume_id": state["resume_id"],
            "job_id": state["job_id"],
            "local_resume_id": (state.get("resume") or {}).get("local_resume_id"),
            "local_job_id": (state.get("job") or {}).get("local_job_id"),
            "enable_rag": bool(state.get("enable_rag", True)),
            "knowledge_used": bool(state.get("knowledge_used")),
            "knowledge_count": state.get("knowledge_count") or 0,
            "rag_queries": state.get("rag_queries") or [],
            "rag_hit_titles": state.get("rag_hit_titles") or [],
            "rag_hit_sources": state.get("rag_hit_sources") or [],
        },
        user_id=state["user_id"],
        trace_spans=state.get("trace_spans", []),
    )
    insert_task_traces(task_id, state.get("trace_spans", []))
    return {"task_id": task_id, "questions_text": text}


def load_or_prepare_resume_node(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    resume_id = state.get("resume_id", 0)
    if resume_id and resume_id > 0:
        resume = get_resume_by_id(resume_id, user_id=state["user_id"])
        if resume is None:
            return {"error_msg": "简历未找到"}
        return {"resume": resume}
    personal_info = state.get("personal_info") or ""
    if not personal_info.strip():
        return {"error_msg": "请提供简历 ID 或输入个人信息"}
    return {"resume": {"content": personal_info.strip(), "file_name": "用户输入"}}


def build_generate_resume_prompt_node(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    prompt = get_prompt_manager().render(
        "resume_generate",
        resume_content=state["resume"]["content"],
        job_jd=state["job"]["jd_text"],
    )
    return {"prompt": prompt}


async def llm_generate_resume_node_async(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    raw_output = await _stream_llm_with_callback(state["prompt"])
    return {"raw_output": raw_output}


def parse_generated_resume_node(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    cleaned = (state["raw_output"] or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return {"generated_resume": cleaned}


def save_generate_resume_task_node(state) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    task_id = save_success_task(
        task_type="RESUME_GENERATE",
        resume_id=state["resume_id"] if state.get("resume_id", 0) > 0 else None,
        job_id=state["job_id"],
        output_data={"generated_resume": state["generated_resume"]},
        input_data={
            "resume_id": state.get("resume_id"),
            "job_id": state["job_id"],
            "personal_info_used": not (state.get("resume_id", 0) > 0),
            "personal_info_length": len(state.get("personal_info") or ""),
            "local_job_id": (state.get("job") or {}).get("local_job_id"),
        },
        user_id=state["user_id"],
        trace_spans=state.get("trace_spans", []),
    )
    insert_task_traces(task_id, state.get("trace_spans", []))
    return {"task_id": task_id, "interview_questions": state.get("interview_questions"), "generated_resume": state.get("generated_resume")}


def route_on_error(state) -> str:
    if state.get("error_msg"):
        return END
    return "load_job"


def route_after_job(state) -> str:
    if state.get("error_msg"):
        return END
    return "build_prompt"


def route_after_job_for_optimize(state) -> str:
    if state.get("error_msg"):
        return END
    return "build_optimize_prompt"


def route_after_job_for_interview(state) -> str:
    if state.get("error_msg"):
        return END
    return "retrieve_knowledge"


def route_after_resume_load(state) -> str:
    if state.get("error_msg"):
        return END
    return "load_job"


def route_after_job_for_generate(state) -> str:
    if state.get("error_msg"):
        return END
    return "build_generate_resume_prompt"
