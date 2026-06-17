"""CLI 入口: python -m app.evaluation --workflow match_analyze"""

from app.evaluation import run_evaluation, report_to_markdown
import argparse

parser = argparse.ArgumentParser(description="JobAgent 评测工具")
parser.add_argument("--workflow", "-w", required=True,
                    choices=["match_analyze", "interview_questions", "resume_optimize", "resume_generate"],
                    help="要评测的 workflow")
parser.add_argument("--llm-judge", action="store_true", default=True,
                    help="启用 LLM Judge 评分 (默认开启)")
parser.add_argument("--no-llm-judge", action="store_false", dest="llm_judge",
                    help="仅规则评分，不调 LLM Judge")
parser.add_argument("--samples", type=int, default=3,
                    help="LLM Judge 采样次数 (默认3)")

args = parser.parse_args()

print(f"评测 {args.workflow} (LLM Judge={'ON' if args.llm_judge else 'OFF'}, samples={args.samples})")
print()
report = run_evaluation(
    workflow=args.workflow,
    llm_judge=args.llm_judge,
    judge_samples=args.samples,
)
print(report_to_markdown(report))
