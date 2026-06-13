import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.llm import invoke_llm
from app.db.crud import get_job_by_id, get_resume_by_id, insert_agent_task
from app.schemas.agent_schema import AgentAnalyzeRequest, AgentAnalyzeResponse

router = APIRouter(prefix="/api/agent", tags=["Agent"])

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "match_analyze.txt"


def clean_llm_json_output(text: str) -> str:
    cleaned = text.strip()

    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json") :]
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```") :]

    if cleaned.endswith("```"):
        cleaned = cleaned[: -len("```")]

    return cleaned.strip()


@router.post("/analyze", response_model=AgentAnalyzeResponse)
def analyze_match(payload: AgentAnalyzeRequest) -> AgentAnalyzeResponse:
    resume = get_resume_by_id(payload.resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")

    job = get_job_by_id(payload.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.format(
        resume_content=resume["content"],
        job_jd=job["jd_text"],
    )

    raw_output = invoke_llm(prompt)
    try:
        analysis = json.loads(clean_llm_json_output(raw_output))
    except json.JSONDecodeError:
        analysis = {"raw_output": raw_output}

    task_id = insert_agent_task(
        task_type="MATCH_ANALYZE",
        resume_id=payload.resume_id,
        job_id=payload.job_id,
        input_data={"resume_id": payload.resume_id, "job_id": payload.job_id},
        output_data=analysis,
        status="SUCCESS",
    )
    return AgentAnalyzeResponse(task_id=task_id, analysis=analysis)
