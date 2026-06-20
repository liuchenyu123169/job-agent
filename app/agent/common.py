import json
import logging
import re
import time
from typing import Any, Callable

from app.core.constants import DEFAULT_USER_ID
from app.core.llm import invoke_llm
from app.db.crud import insert_agent_task
from app.prompt_engine import PromptManager

logger = logging.getLogger(__name__)


def _trace_node(name: str, fn: Callable) -> Callable:
    """包装工作流节点函数，自动记录耗时到 state[\"trace_spans\"]。

    用法:
        graph.add_node(\"load_resume\", _trace_node(\"load_resume\", load_resume_node))
    """
    def wrapper(state: dict) -> dict:
        t0 = time.monotonic()
        result = fn(state)
        dur = round((time.monotonic() - t0) * 1000, 2)
        spans = state.setdefault("trace_spans", [])
        spans.append({"name": name, "duration_ms": dur})
        return result
    wrapper.__name__ = fn.__name__
    return wrapper

# 全局 PromptManager 单例（v1 版本，默认不启用 few-shot）
_prompt_manager = PromptManager(version="v1")


def get_prompt_manager() -> PromptManager:
    """获取全局 PromptManager 实例（可替换 few_shot_store）。"""
    return _prompt_manager


def _clean_llm_json_output(text: str) -> str:
    cleaned = text.strip()

    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json") :]
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```") :]

    if cleaned.endswith("```"):
        cleaned = cleaned[: -len("```")]

    return cleaned.strip()


def parse_llm_json_output(raw_output: str) -> dict[str, Any]:
    try:
        return json.loads(_clean_llm_json_output(raw_output))
    except json.JSONDecodeError:
        return {"raw_output": raw_output}


def analyze_resume_job(resume_content: str, job_jd: str) -> dict[str, Any]:
    prompt = _prompt_manager.render(
        "match_analyze",
        resume_content=resume_content,
        job_jd=job_jd,
    )
    raw_output = invoke_llm(prompt)
    return parse_llm_json_output(raw_output)


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
