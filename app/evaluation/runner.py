"""评测编排模块 —— 加载评测集、调 workflow、评分、出报告。

CLI:  python -m app.evaluation --workflow match_analyze [--llm-judge] [--samples 3]
API:  POST /api/evaluation/run
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.agent.workflow import (
    run_analyze_workflow,
    run_interview_questions_workflow,
    run_optimize_resume_workflow,
    run_generate_resume_workflow,
)
from app.db.crud import insert_job, insert_resume
from app.db.database import get_conn
from app.evaluation.judge import CaseScore, StableJudgeResult, score_case

logger = logging.getLogger(__name__)

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"

# ── Workflow 映射 ──

_WORKFLOW_MAP: dict[str, Any] = {
    "match_analyze": run_analyze_workflow,
    "interview_questions": run_interview_questions_workflow,
    "resume_optimize": run_optimize_resume_workflow,
    "resume_generate": run_generate_resume_workflow,
}

# 每个 workflow 需要的参数（from case input）
_WORKFLOW_PARAMS: dict[str, list[str]] = {
    "match_analyze": ["resume_id", "job_id", "user_id"],
    "interview_questions": ["resume_id", "job_id", "user_id", "enable_rag"],
    "resume_optimize": ["resume_id", "job_id", "user_id"],
    "resume_generate": ["resume_id", "job_id", "user_id", "personal_info"],
}


# ── 评测结果数据类 ──


@dataclass
class EvalReport:
    """完整评测报告。"""
    workflow: str
    total: int
    passed: int
    avg_final_score: float
    avg_rule_score: float
    avg_judge_score: float
    avg_latency_ms: float
    theme_hit_rate: float
    forbidden_hit_rate: float
    empty_rate: float
    judge_reliable_rate: float
    judge_stability: dict = field(default_factory=dict)
    judge_dimensions: dict = field(default_factory=dict)
    bad_cases: list[dict] = field(default_factory=list)
    case_results: list[dict] = field(default_factory=list)
    timestamp: str = ""


# ── 临时测试数据 ──

def _setup_temp_data(case_input: dict, user_id: int = 1) -> tuple[int, int]:
    """根据用例中的 inline resume_content/job_jd 插入临时数据，返回 (resume_id, job_id)。"""
    resume_content = case_input.get("resume_content", "")
    job_jd = case_input.get("job_jd", "")

    resume_id = case_input.get("resume_id", 0)
    job_id = case_input.get("job_id", 0)

    if resume_content:
        resume_id = insert_resume(file_name=f"eval_temp", content=resume_content, user_id=user_id)
    if job_jd:
        title = f"eval_temp - {case_input.get('job_title', '未命名岗位')}"
        job_id = insert_job(company="评测临时", title=title, jd_text=job_jd, user_id=user_id)

    return resume_id, job_id


def _cleanup_temp_data(resume_id: int, job_id: int) -> None:
    """删除评测插入的临时数据。"""
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        if resume_id:
            cursor.execute("DELETE FROM resume WHERE id = ? AND file_name = 'eval_temp'", (resume_id,))
        if job_id:
            cursor.execute("DELETE FROM job WHERE id = ? AND title LIKE 'eval_temp%'", (job_id,))
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


# ── 评测集加载 ──


def load_dataset(workflow: str) -> list[dict[str, Any]]:
    """加载评测集 YAML 文件。"""
    case_file = DATASETS_DIR / f"{workflow}.yaml"
    if not case_file.is_file():
        logger.warning("评测集文件不存在: %s", case_file)
        return []
    raw = yaml.safe_load(case_file.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"评测集 {case_file} 应为 YAML 列表")
    return raw


# ── 评测编排 ──


def run_evaluation(
    workflow: str,
    llm_judge: bool = True,
    judge_samples: int = 3,
    cases: list[dict] | None = None,
) -> EvalReport:
    """运行完整评测流程。

    Args:
        workflow: 要评测的 workflow 名称
        llm_judge: 是否启用 LLM Judge
        judge_samples: LLM Judge 采样次数
        cases: 指定用例列表（不传则从 YAML 文件加载）

    Returns:
        EvalReport 包含所有评分和 bad cases
    """
    cases = cases or load_dataset(workflow)
    if not cases:
        return EvalReport(workflow=workflow, total=0, passed=0,
                          avg_final_score=0, avg_rule_score=0, avg_judge_score=0,
                          avg_latency_ms=0, theme_hit_rate=0, forbidden_hit_rate=0,
                          empty_rate=0, judge_reliable_rate=0)

    wf_fn = _WORKFLOW_MAP.get(workflow)
    if wf_fn is None:
        raise ValueError(f"未知 workflow: {workflow}，可选: {list(_WORKFLOW_MAP.keys())}")

    results: list[CaseScore] = []

    for case in cases:
        name = case.get("name", "unnamed")
        input_data = case.get("input", {})
        checks = case.get("checks", {})
        reference = case.get("reference", "")
        if isinstance(reference, dict):
            reference = json.dumps(reference, ensure_ascii=False)

        logger.info("[Eval] running %s: %s", workflow, name)

        # 插入临时测试数据（如果用例提供了 inline resume_content/job_jd）
        resume_id, job_id = _setup_temp_data(input_data, user_id=1)

        # 调 workflow
        t0 = time.perf_counter()
        try:
            params = {k: input_data.get(k, 1) for k in _WORKFLOW_PARAMS.get(workflow, [])}
            params.setdefault("user_id", 1)
            params["resume_id"] = resume_id or params.get("resume_id", 1)
            params["job_id"] = job_id or params.get("job_id", 1)
            output = wf_fn(**params)
            raw_output = json.dumps(output, ensure_ascii=False)
        except Exception as exc:
            logger.error("[Eval] workflow failed for %s: %s", name, exc)
            score = CaseScore(case_name=name, errors=[str(exc)])
            results.append(score)
            _cleanup_temp_data(resume_id, job_id)
            continue
        latency_ms = (time.perf_counter() - t0) * 1000

        # 清理临时数据
        _cleanup_temp_data(resume_id, job_id)

        # 提取实际输出内容
        if isinstance(output, dict):
            output_content = output.get("analysis") or output.get("optimization") or \
                              output.get("interview_questions") or output.get("generated_resume") or output
        else:
            output_content = output

        # 评分
        score = score_case(
            case_name=name,
            output=output_content if isinstance(output_content, dict) else None,
            raw_output=raw_output,
            checks=checks,
            reference=str(reference),
            latency_ms=latency_ms,
            enable_llm_judge=llm_judge,
            judge_samples=judge_samples,
        )
        results.append(score)

    # ── 汇总报告 ──
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    avg_final = sum(r.final_score for r in results) / total if total else 0
    avg_rule = sum(r.rule_score for r in results) / total if total else 0
    avg_latency = sum(r.latency_ms for r in results) / total if total else 0

    # Judge 统计
    judge_results = [r.judge for r in results if r.judge and r.judge.reliable]
    avg_judge = sum(j.overall / 5.0 for j in judge_results) / len(judge_results) if judge_results else 0
    reliable_count = len(judge_results)
    judge_reliable_rate = reliable_count / total if total else 0

    # Judge 分维度均值
    dims = ["accuracy", "relevance", "completeness", "specificity", "authenticity"]
    judge_dimensions: dict[str, float] = {}
    if judge_results:
        for dim in dims:
            judge_dimensions[dim] = round(
                sum(getattr(j, dim) for j in judge_results) / len(judge_results), 1
            )

    # Judge 稳定性
    judge_stability: dict[str, float] = {}
    if judge_results:
        for dim in dims:
            stds = [j.stability.get(dim, 0) for j in judge_results if j.stability.get(dim)]
            judge_stability[dim] = round(sum(stds) / len(stds), 2) if stds else 0

    # 规则命中率
    theme_hit_rate = sum(
        r.themes.get("score", 1.0) for r in results if r.themes
    ) / max(sum(1 for r in results if r.themes), 1)
    forbidden_hit_rate = 1.0 - sum(
        r.forbidden.get("score", 1.0) for r in results if r.forbidden
    ) / max(sum(1 for r in results if r.forbidden), 1)
    empty_rate = sum(1 for r in results if r.empty.get("is_empty")) / total if total else 0

    # Bad cases (final_score < 0.5 或有错误)
    bad_cases = [
        {
            "case_name": r.case_name,
            "final_score": r.final_score,
            "errors": r.errors,
            "rule_score": r.rule_score,
            "judge": r.judge.to_dict() if r.judge else None,
            "latency_ms": r.latency_ms,
        }
        for r in results if not r.passed or r.final_score < 0.5
    ]

    # 全部 case 详情
    case_results = [
        {
            "case_name": r.case_name,
            "final_score": r.final_score,
            "rule_score": r.rule_score,
            "passed": r.passed,
            "errors": r.errors,
            "latency_ms": r.latency_ms,
            "structure": r.structure,
            "themes": r.themes,
            "forbidden": r.forbidden,
            "judge": r.judge.to_dict() if r.judge else None,
        }
        for r in results
    ]

    return EvalReport(
        workflow=workflow,
        total=total,
        passed=passed,
        avg_final_score=round(avg_final, 2),
        avg_rule_score=round(avg_rule, 2),
        avg_judge_score=round(avg_judge, 2),
        avg_latency_ms=round(avg_latency, 0),
        theme_hit_rate=round(theme_hit_rate, 2),
        forbidden_hit_rate=round(forbidden_hit_rate, 2),
        empty_rate=round(empty_rate, 2),
        judge_reliable_rate=round(judge_reliable_rate, 2),
        judge_stability=judge_stability,
        judge_dimensions=judge_dimensions,
        bad_cases=bad_cases,
        case_results=case_results,
        timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


# ── 报告导出 ──


def report_to_markdown(report: EvalReport) -> str:
    """生成 Markdown 评测报告。"""
    lines = [
        f"## {report.workflow} 评测报告",
        f"",
        f"**时间**: {report.timestamp}  |  **用例数**: {report.total}  |  **通过**: {report.passed}/{report.total}",
        f"",
        f"### 综合指标",
        f"",
        f"| 指标 | 值 |",
        f"|------|----|",
        f"| 综合分 | {report.avg_final_score:.2f} |",
        f"| 规则分 | {report.avg_rule_score:.2f} |",
        f"| Judge 分 | {report.avg_judge_score:.2f} |",
        f"| 平均耗时 | {report.avg_latency_ms:.0f}ms |",
        f"| 主题命中率 | {report.theme_hit_rate:.0%} |",
        f"| 禁区命中率 | {report.forbidden_hit_rate:.0%} |",
        f"| 空回答率 | {report.empty_rate:.0%} |",
        f"| Judge 可靠率 | {report.judge_reliable_rate:.0%} |",
        f"",
    ]

    if report.judge_dimensions:
        lines.append("### LLM Judge 分维度")
        lines.append("")
        lines.append("| 维度 | 平均分 | 稳定性(σ) |")
        lines.append("|------|--------|-----------|")
        for dim, score in report.judge_dimensions.items():
            std = report.judge_stability.get(dim, "N/A")
            lines.append(f"| {dim} | {score} | {std} |")
        lines.append("")

    if report.bad_cases:
        lines.append(f"### Bad Cases ({len(report.bad_cases)} 条)")
        lines.append("")
        for bc in report.bad_cases[:10]:
            lines.append(f"- **{bc['case_name']}** (综合 {bc['final_score']:.1f})")
            for err in bc.get("errors", []):
                lines.append(f"  - {err}")
            if bc.get("judge") and bc["judge"].get("reasoning"):
                lines.append(f"  - Judge: {bc['judge']['reasoning'][:120]}")
        lines.append("")

    return "\n".join(lines)


def report_to_dict(report: EvalReport) -> dict:
    """导出为 JSON 可序列化字典。"""
    return {
        "workflow": report.workflow,
        "timestamp": report.timestamp,
        "summary": {
            "total": report.total,
            "passed": report.passed,
            "avg_final_score": report.avg_final_score,
            "avg_rule_score": report.avg_rule_score,
            "avg_judge_score": report.avg_judge_score,
            "avg_latency_ms": report.avg_latency_ms,
            "theme_hit_rate": report.theme_hit_rate,
            "forbidden_hit_rate": report.forbidden_hit_rate,
            "empty_rate": report.empty_rate,
            "judge_reliable_rate": report.judge_reliable_rate,
        },
        "judge_dimensions": report.judge_dimensions,
        "judge_stability": report.judge_stability,
        "bad_cases": report.bad_cases,
        "case_results": report.case_results,
    }
