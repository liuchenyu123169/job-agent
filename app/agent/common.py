import json
from pathlib import Path
from typing import Any

from app.db.crud import insert_agent_task

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def read_prompt_template(prompt_file_name: str) -> str:
    prompt_path = PROMPTS_DIR / prompt_file_name
    return prompt_path.read_text(encoding="utf-8")


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


def save_success_task(
    task_type: str,
    resume_id: int,
    job_id: int,
    output_data: dict[str, Any],
    input_data: dict[str, Any] | None = None,
) -> int:
    return insert_agent_task(
        task_type=task_type,
        resume_id=resume_id,
        job_id=job_id,
        input_data=input_data or {"resume_id": resume_id, "job_id": job_id},
        output_data=output_data,
        status="SUCCESS",
    )
