import logging
from typing import Any

from app.core.constants import DEFAULT_USER_ID
from app.db.crud import get_resume_by_id, insert_task_traces, list_jobs_for_user
from app.observability.tracer import get_current_spans, traced
from app.workflows.common import (
    analyze_resume_job,
    build_match_reason,
    ensure_string_list,
    normalize_match_score,
    save_failed_task,
    save_success_task,
)

logger = logging.getLogger(__name__)


@traced("recommend_jobs")
def recommend_jobs_for_resume(
    resume_id: int,
    top_k: int = 5,
    max_jobs: int = 10,
    user_id: int = DEFAULT_USER_ID,
) -> dict[str, Any]:
    input_payload = {
        "resume_id": resume_id,
        "top_k": top_k,
        "max_jobs": max_jobs,
    }
    logger.info("[RECOMMEND] start resume_id=%s user_id=%s", resume_id, user_id)

    resume = get_resume_by_id(resume_id, user_id=user_id)
    if resume is None:
        error_msg = "简历未找到"
        save_failed_task(
            task_type="JOB_RECOMMEND",
            resume_id=resume_id,
            job_id=None,
            error_msg=error_msg,
            input_data=input_payload,
            user_id=user_id,
        )
        return {
            "task_id": None,
            "resume_id": resume_id,
            "top_k": top_k,
            "candidate_job_count": 0,
            "items": [],
            "error_msg": error_msg,
        }

    input_payload["local_resume_id"] = resume.get("local_resume_id")

    candidate_jobs = list_jobs_for_user(user_id=user_id, limit=max_jobs, newest_first=True)
    candidate_job_count = len(candidate_jobs)
    logger.info("[RECOMMEND] candidate_job_count=%s", candidate_job_count)

    result: dict[str, Any] = {
        "resume_id": resume_id,
        "top_k": top_k,
        "candidate_job_count": candidate_job_count,
        "items": [],
    }
    input_payload["candidate_job_count"] = candidate_job_count

    if not candidate_jobs:
        task_id = save_success_task(
            task_type="JOB_RECOMMEND",
            resume_id=resume_id,
            job_id=None,
            input_data=input_payload,
            output_data=result,
            user_id=user_id,
            trace_spans=get_current_spans(),
        )
        result["task_id"] = task_id
        spans = get_current_spans()
        insert_task_traces(task_id, spans)
        logger.info("[RECOMMEND] finished items=0")
        return {**result, "error_msg": None}

    scored_items: list[dict[str, Any]] = []
    errors: list[str] = []
    resume_content = str(resume.get("content") or "")

    for job in candidate_jobs:
        job_id = int(job["id"])
        title = str(job.get("title") or "")
        logger.info("[RECOMMEND] analyzing job_id=%s title=%s", job_id, title)
        try:
            analysis = analyze_resume_job(
                resume_content=resume_content,
                job_jd=str(job.get("jd_text") or ""),
            )
            advantages = ensure_string_list(analysis.get("advantages"))
            weaknesses = ensure_string_list(analysis.get("weaknesses"))
            suggestions = ensure_string_list(analysis.get("suggestions"))
            match_score = normalize_match_score(analysis.get("match_score"))
            match_reason = build_match_reason(analysis, advantages, weaknesses)
            logger.info("[RECOMMEND] job_id=%s match_score=%s", job_id, match_score)
            scored_items.append(
                {
                    "job_id": job_id,
                    "local_job_id": job.get("local_job_id"),
                    "company": job.get("company"),
                    "title": job.get("title"),
                    "match_score": match_score,
                    "match_reason": match_reason,
                    "advantages": advantages,
                    "weaknesses": weaknesses,
                    "suggestions": suggestions,
                }
            )
        except Exception as exc:
            error = f"job_id={job_id} failed: {exc}"
            errors.append(error)
            logger.warning("[RECOMMEND] %s", error)

    scored_items.sort(key=lambda item: (item["match_score"], item["job_id"]), reverse=True)
    result["items"] = scored_items[:top_k]
    if errors:
        result["errors"] = errors

    task_id = save_success_task(
        task_type="JOB_RECOMMEND",
        resume_id=resume_id,
        job_id=None,
        input_data=input_payload,
        output_data=result,
        user_id=user_id,
    )
    result["task_id"] = task_id
    spans = get_current_spans()
    insert_task_traces(task_id, spans)
    logger.info("[RECOMMEND] finished items=%s", len(result["items"]))
    return {**result, "error_msg": None}
