import json

from fastapi import APIRouter, HTTPException

from app.agent.workflow import run_interview_questions_workflow
from app.agent.workflow import run_analyze_workflow, run_optimize_resume_workflow
from app.schemas.agent_schema import (
    AgentAnalyzeRequest,
    AgentAnalyzeResponse,
    AgentOptimizeResumeRequest,
    AgentOptimizeResumeResponse,
)
from app.schemas.agent_schema import AgentGenerateInterviewQuestionsResponse,AgentGenerateInterviewQuestionsRequest

router = APIRouter(prefix="/api/agent", tags=["Agent"])


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
    result = run_analyze_workflow(payload.resume_id, payload.job_id)

    if result["error_msg"] == "Resume not found":
        raise HTTPException(status_code=404, detail="Resume not found")
    if result["error_msg"] == "Job not found":
        raise HTTPException(status_code=404, detail="Job not found")
    return AgentAnalyzeResponse(task_id=result["task_id"], analysis=result["analysis"])


@router.post("/optimize-resume", response_model=AgentOptimizeResumeResponse)
def optimize_resume(payload: AgentOptimizeResumeRequest) -> AgentOptimizeResumeResponse:
    result = run_optimize_resume_workflow(payload.resume_id, payload.job_id)

    if result["error_msg"] == "Resume not found":
        raise HTTPException(status_code=404, detail="Resume not found")
    if result["error_msg"] == "Job not found":
        raise HTTPException(status_code=404, detail="Job not found")
    return AgentOptimizeResumeResponse(
        task_id=result["task_id"],
        optimization=result["optimization"],
    )

@router.post("/generate-interview-questions", response_model=AgentGenerateInterviewQuestionsResponse)
def generate_interview_questions(payload: AgentGenerateInterviewQuestionsRequest) -> AgentGenerateInterviewQuestionsResponse:
    result = run_interview_questions_workflow(payload.resume_id, payload.job_id)

    if result["error_msg"] == "Resume not found":
        raise HTTPException(status_code=404, detail="Resume not found")
    if result["error_msg"] == "Job not found":
        raise HTTPException(status_code=404, detail="Job not found")
    return AgentGenerateInterviewQuestionsResponse(
        task_id=result["task_id"],
        questions=result["interview_questions"]
    )