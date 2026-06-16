import json
import logging
import re
from typing import Any

from app.core.constants import DEFAULT_USER_ID
from app.core.llm import invoke_llm
from app.db.crud import insert_agent_task
from app.prompt_engine import PromptManager

logger = logging.getLogger(__name__)

# 全局 PromptManager 单例（v1 版本，默认不启用 few-shot）
_prompt_manager = PromptManager(version="v1")


def get_prompt_manager() -> PromptManager:
    """获取全局 PromptManager 实例（可替换 few_shot_store）。"""
    return _prompt_manager


def read_prompt_template(prompt_file_name: str) -> str:
    """【已弃用】请用 get_prompt_manager().render() 替代。

    保留此函数以兼容旧代码，内部已委托给 PromptManager。
    """
    # 从文件名提取模板名（去掉 .txt / .j2 后缀，去掉 _ 转 - 等）
    template_name = prompt_file_name.rsplit(".", 1)[0]
    # 兼容旧的 .txt 文件名映射到 .j2 模板
    mapping = {
        "match_analyze": "match_analyze",
        "resume_optimize": "resume_optimize",
        "interview_questions": "interview_questions",
    }
    name = mapping.get(template_name, template_name)
    return _prompt_manager.render(name)


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
) -> int:
    return insert_agent_task(
        task_type=task_type,
        resume_id=resume_id,
        job_id=job_id,
        input_data=input_data or {"resume_id": resume_id, "job_id": job_id},
        output_data=output_data,
        status="SUCCESS",
        user_id=user_id,
    )


def save_failed_task(
    task_type: str,
    resume_id: int | None,
    job_id: int | None,
    error_msg: str,
    input_data: dict[str, Any] | None = None,
    output_data: dict[str, Any] | None = None,
    user_id: int = DEFAULT_USER_ID,
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
    )
