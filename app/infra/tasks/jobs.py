"""后台任务函数 — arq worker 执行。"""

import logging

from app.infra.tasks.models import TaskStatus

logger = logging.getLogger(__name__)


async def build_rag_job(ctx, knowledge_dir: str = "data/knowledge") -> dict:
    """后台重建 RAG 知识库。进度 0 → 1。"""
    await ctx.set_progress(0.1)

    from app.rag.rag_service import build_knowledge_base
    result = build_knowledge_base()
    await ctx.set_progress(0.95)

    logger.info("[build_rag] done: %s", result)
    return {
        "status": TaskStatus.SUCCESS,
        "file_count": result.get("file_count", 0),
        "chunk_count": result.get("chunk_count", 0),
    }


async def eval_run_job(
    ctx,
    workflow: str = "match_analyze",
    llm_judge: bool = True,
    judge_samples: int = 3,
) -> dict:
    """后台运行评测。"""
    await ctx.set_progress(0.05)

    from app.evaluation.runner import run_evaluation, report_to_dict
    report = await run_evaluation(
        workflow=workflow,
        llm_judge=llm_judge,
        judge_samples=judge_samples,
    )
    await ctx.set_progress(0.95)

    result = report_to_dict(report)
    logger.info("[eval_run] %s: %s/%s passed", workflow, result["summary"]["passed"], result["summary"]["total"])
    return {
        "status": TaskStatus.SUCCESS,
        "report": result,
    }


async def batch_analyze_job(
    ctx,
    resume_id: int,
    job_ids: list[int],
    user_id: int,
    enable_rag: bool = True,
) -> dict:
    """批量匹配分析：一个简历 × 多个岗位。进度按完成比例递增。"""
    from app.workflows.state import make_initial_state
    from app.workflows.analyze import analyze_graph

    total = len(job_ids)
    results = []
    errors = []

    for i, job_id in enumerate(job_ids):
        try:
            initial = make_initial_state(user_id, resume_id, job_id, enable_rag=enable_rag)
            final_state = await analyze_graph.ainvoke(initial)
            results.append({
                "job_id": job_id,
                "success": not final_state.get("error_msg"),
                "analysis_text": final_state.get("analysis_text", "")[:500],
            })
        except Exception as exc:
            errors.append({"job_id": job_id, "error": str(exc)})

        await ctx.set_progress((i + 1) / total)

    all_success = len(errors) == 0
    some_success = len(results) > 0
    status = TaskStatus.SUCCESS if all_success else (
        TaskStatus.PARTIAL_SUCCESS if some_success else TaskStatus.FAILED
    )
    logger.info("[batch_analyze] %d/%d ok, %d errors", len(results), total, len(errors))
    return {
        "status": status,
        "total": total,
        "ok": len(results),
        "errors": errors,
        "results": results,
    }
