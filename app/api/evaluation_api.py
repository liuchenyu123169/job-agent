"""评测 API — 触发评测、查看历史报告。"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.evaluation.runner import (
    _WORKFLOW_MAP,
    report_to_dict,
    report_to_markdown,
    run_evaluation,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evaluation", tags=["Evaluation"])

RESULTS_DIR = Path(__file__).resolve().parents[2] / "evaluation_results"
RESULTS_DIR.mkdir(exist_ok=True)


class EvalRunRequest(BaseModel):
    workflows: list[str] | str = Field(
        default=["match_analyze"],
        description="要评测的 workflow 列表，传字符串自动转数组",
    )
    llm_judge: bool = Field(default=True, description="是否启用 LLM Judge 评分")
    judge_samples: int = Field(default=3, ge=1, le=5, description="LLM Judge 采样次数")


@router.post("/run")
def run_eval(
    payload: EvalRunRequest,
) -> dict:
    """运行评测，返回报告（开发工具，无需登录）。

    调用方式：
        curl -X POST http://127.0.0.1:8000/api/evaluation/run \\
          -H "Content-Type: application/json" \\
          -d '{"workflows":["match_analyze"],"llm_judge":true,"judge_samples":3}'
    """
    user_id = 1  # 评测用默认用户
    all_reports: dict[str, dict] = {}

    # 字符串自动转数组
    workflows = payload.workflows if isinstance(payload.workflows, list) else [payload.workflows]

    for wf in workflows:
        if wf not in _WORKFLOW_MAP:
            all_reports[wf] = {"error": f"未知 workflow: {wf}", "available": list(_WORKFLOW_MAP.keys())}
            continue

        logger.info("[Eval] running %s (llm_judge=%s, samples=%d, user=%d)",
                     wf, payload.llm_judge, payload.judge_samples, user_id)
        report = run_evaluation(
            workflow=wf,
            llm_judge=payload.llm_judge,
            judge_samples=payload.judge_samples,
        )
        all_reports[wf] = report_to_dict(report)

        # 保存 JSON 结果
        ts = report.timestamp.replace(":", "").replace("T", "_")[:15]
        result_file = RESULTS_DIR / f"{wf}_{ts}.json"
        result_file.write_text(
            json.dumps(report_to_dict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[Eval] report saved: %s", result_file)

        # 同时保存 Markdown
        md_file = RESULTS_DIR / f"{wf}_{ts}.md"
        md_file.write_text(report_to_markdown(report), encoding="utf-8")

    return {
        "status": "completed",
        "workflows": list(all_reports.keys()),
        "reports": all_reports,
        "saved_to": str(RESULTS_DIR),
    }


@router.get("/workflows")
def list_workflows() -> list[str]:
    """列出所有可评测的 workflow。"""
    return list(_WORKFLOW_MAP.keys())


@router.get("/results")
def list_results() -> list[dict]:
    """列出历史评测结果文件。"""
    if not RESULTS_DIR.is_dir():
        return []
    results = []
    for f in sorted(RESULTS_DIR.glob("*.json"), reverse=True):
        results.append({
            "file": f.name,
            "size": f.stat().st_size,
            "created_at": f.stat().st_ctime,
        })
    return results[:20]
