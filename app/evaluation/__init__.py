"""JobAgent 自动化评测模块。

用法:
    # CLI
    python -m app.evaluation --workflow match_analyze [--llm-judge] [--samples 3]

    # API
    POST /api/evaluation/run
    body: {"workflows": ["match_analyze"], "llm_judge": true, "judge_samples": 3}
"""

from app.evaluation.runner import (
    EvalReport,
    load_dataset,
    report_to_dict,
    report_to_markdown,
    run_evaluation,
)

__all__ = [
    "EvalReport",
    "load_dataset",
    "report_to_dict",
    "report_to_markdown",
    "run_evaluation",
]
