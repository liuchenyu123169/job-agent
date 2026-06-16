"""PromptEvaluator — 测试用例管理 / 批量评估 / AB 对比。

设计考量：
  - 评估维度可插拔（structured_output / length / keyword_check ...）
  - 测试用例 YAML 驱动，非技术人员也能新增
  - AB 对比输出 Markdown 表格，可直接粘贴到 PR 描述
  - 所有结果可 JSON 导出，做历史趋势分析

用法：
    evaluator = PromptEvaluator(prompt_manager_v1, prompt_manager_v2)
    report = evaluator.compare("match_analyze", test_cases)
    print(report)
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from app.core.llm import invoke_llm

logger = logging.getLogger(__name__)

EVAL_CASES_DIR = Path(__file__).resolve().parents[1] / "prompts" / "eval_cases"


@dataclass
class EvalResult:
    """单条测试用例的评估结果。"""
    case_name: str
    prompt_version: str
    output: dict[str, Any]  # LLM 返回的 JSON
    latency_ms: float
    metrics: dict[str, float] = field(default_factory=dict)  # {metric_name: score}
    passed: bool = True
    errors: list[str] = field(default_factory=list)


class PromptEvaluator:
    """Prompt 效果评估器。

    测试用例 YAML 格式：
        - name: "Java后端-1"
          variables:
            resume_content: "..."
            job_jd: "..."
          checks:                          # 期望的结构检查
            has_fields: [match_score, advantages, weaknesses, suggestions]
            match_score_range: [0, 100]
            advantages_min_count: 1
          keywords:                        # 期望出现的关键词
            - "Spring"
            - "Java"
    """

    # 内置评估维度（静态方法，可被替换/扩展）
    _DEFAULT_METRICS: dict[str, Callable] = {}

    def __init__(self, prompt_manager, version_label: str | None = None):
        """
        Args:
            prompt_manager: PromptManager 实例
            version_label: 版本标签（如 "v1"），输出报告时用
        """
        self.pm = prompt_manager
        self.version_label = version_label or prompt_manager.version
        self.metrics = dict(self._DEFAULT_METRICS)

    # ── 加载测试用例 ──

    def load_cases(self, template_name: str) -> list[dict[str, Any]]:
        """加载指定模板的测试用例 YAML 文件。"""
        case_file = EVAL_CASES_DIR / f"{template_name}.yaml"
        if not case_file.is_file():
            logger.warning("测试用例文件不存在: %s", case_file)
            return []
        raw = yaml.safe_load(case_file.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError(f"测试用例 {case_file} 应为 YAML 列表")
        return raw

    # ── 单条评估 ──

    def evaluate_one(
        self,
        template_name: str,
        case: dict[str, Any],
        scene: str | None = None,
    ) -> EvalResult:
        """对一条测试用例执行评估。

        Args:
            template_name: 模板名
            case: 单条用例 dict {name, variables, checks?, keywords?}
            scene: few-shot 场景标签

        Returns:
            EvalResult（包含 output / latency / metrics / passed / errors）
        """
        name = case.get("name", "unnamed")
        result = EvalResult(case_name=name, prompt_version=self.version_label, output={})
        errors: list[str] = []

        # 1. 渲染 + LLM 调用
        t0 = time.perf_counter()
        try:
            prompt = self.pm.render(template_name, scene=scene, **case.get("variables", {}))
            raw = invoke_llm(prompt)
            output = self._try_parse_json(raw)
            result.output = output
        except Exception as exc:
            errors.append(f"LLM 调用失败: {exc}")
            result.errors = errors
            result.passed = False
            result.latency_ms = (time.perf_counter() - t0) * 1000
            return result
        result.latency_ms = (time.perf_counter() - t0) * 1000

        # 2. 结构检查
        checks = case.get("checks") or {}
        if "has_fields" in checks:
            for field in checks["has_fields"]:
                if field not in output:
                    errors.append(f"缺少字段: {field}")

        if "match_score_range" in checks and "match_score" in output:
            lo, hi = checks["match_score_range"]
            score = output["match_score"]
            if not isinstance(score, (int, float)) or not (lo <= score <= hi):
                errors.append(f"match_score {score} 不在范围 [{lo}, {hi}]")

        if "advantages_min_count" in checks:
            count = len(output.get("advantages") or [])
            if count < checks["advantages_min_count"]:
                errors.append(f"advantages 数量 {count} < {checks['advantages_min_count']}")

        # 3. 关键词检查
        keywords = case.get("keywords") or []
        output_str = json.dumps(output, ensure_ascii=False)
        for kw in keywords:
            if kw.lower() not in output_str.lower():
                errors.append(f"缺少关键词: {kw}")

        # 4. 自由指标（可扩展）
        for metric_name, metric_fn in self.metrics.items():
            try:
                result.metrics[metric_name] = metric_fn(output, case)
            except Exception as exc:
                errors.append(f"指标 '{metric_name}' 计算失败: {exc}")

        result.errors = errors
        result.passed = len(errors) == 0
        return result

    # ── 批量评估 ──

    def evaluate_batch(
        self,
        template_name: str,
        cases: list[dict[str, Any]] | None = None,
        scene: str | None = None,
    ) -> list[EvalResult]:
        """批量评估。不传 cases 则从 YAML 文件加载。"""
        cases = cases or self.load_cases(template_name)
        if not cases:
            logger.warning("没有测试用例可评估")
            return []
        results: list[EvalResult] = []
        for case in cases:
            logger.info("评估 [%s]: %s", self.version_label, case.get("name", "?"))
            results.append(self.evaluate_one(template_name, case, scene=scene))
        return results

    # ── AB 对比 ──

    def compare(
        self,
        template_name: str,
        other_evaluator: "PromptEvaluator",
        cases: list[dict[str, Any]] | None = None,
    ) -> str:
        """AB 对比两个 PromptManager 版本。

        Returns:
            Markdown 表格字符串，可直接贴 PR。
        """
        cases = cases or self.load_cases(template_name)
        if not cases:
            return "无测试用例"

        results_a = self.evaluate_batch(template_name, cases)
        results_b = other_evaluator.evaluate_batch(template_name, cases)

        # 构建对比表
        lines = [
            f"## Prompt AB 对比：{template_name}",
            f"",
            f"| 用例 | {self.version_label} | {other_evaluator.version_label} | 胜出 |",
            f"|------|{'---' * (len(self.version_label)//2)}|{'---' * (len(other_evaluator.version_label)//2)}|------|",
        ]

        a_wins = b_wins = draws = 0
        for ra, rb in zip(results_a, results_b):
            a_score = self._summary_score(ra)
            b_score = self._summary_score(rb)
            if a_score > b_score:
                winner = self.version_label
                a_wins += 1
            elif b_score > a_score:
                winner = other_evaluator.version_label
                b_wins += 1
            else:
                winner = "平"
                draws += 1
            lines.append(f"| {ra.case_name} | {a_score:.0f}分 ({ra.latency_ms:.0f}ms) | {b_score:.0f}分 ({rb.latency_ms:.0f}ms) | {winner} |")

        # 汇总
        a_avg = sum(self._summary_score(r) for r in results_a) / len(results_a)
        b_avg = sum(self._summary_score(r) for r in results_b) / len(results_b)
        a_lat = sum(r.latency_ms for r in results_a) / len(results_a)
        b_lat = sum(r.latency_ms for r in results_b) / len(results_b)

        lines.extend([
            f"",
            f"**汇总**：{self.version_label} 平均 {a_avg:.0f}分 ({a_lat:.0f}ms)，"
            f"{other_evaluator.version_label} 平均 {b_avg:.0f}分 ({b_lat:.0f}ms)",
            f"胜场：{self.version_label} {a_wins} | {other_evaluator.version_label} {b_wins} | 平 {draws}",
        ])

        return "\n".join(lines)

    # ── 辅助 ──

    @staticmethod
    def _try_parse_json(raw: str) -> dict[str, Any]:
        """尝试解析 LLM 的 JSON 输出。"""
        text = raw.strip()
        if text.startswith("```json"):
            text = text[len("```json"):]
        elif text.startswith("```"):
            text = text[len("```"):]
        if text.endswith("```"):
            text = text[:-3]
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            return {"raw_output": raw}

    @staticmethod
    def _summary_score(result: EvalResult) -> float:
        """综合评分：通过率 + 指标均值。"""
        if not result.passed:
            return 0.0
        if result.metrics:
            return sum(result.metrics.values()) / len(result.metrics)
        return 100.0 if result.passed else 0.0
