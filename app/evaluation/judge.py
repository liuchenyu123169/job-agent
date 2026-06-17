"""评测评分模块 —— 规则指标检查 + LLM-as-Judge 质量评分。

规则层：确定性检查（结构合规、主题命中、禁区检测、空输出、耗时）
LLM Judge 层：主观质量评分（准确性/相关性/完整性/具体性/真实性），支持多次采样
"""

import json
import logging
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.llm import invoke_llm

logger = logging.getLogger(__name__)

# ── 规则指标 ──


def check_structure(output: dict, required_fields: list[str]) -> dict:
    """检查输出是否包含必需字段。"""
    missing = [f for f in required_fields if f not in (output or {})]
    return {
        "passed": len(missing) == 0,
        "total": len(required_fields),
        "missing": missing,
        "score": 1.0 - len(missing) / max(len(required_fields), 1),
    }


def check_themes(output_str: str, required_themes: list[str]) -> dict:
    """检查输出中是否命中要求的关键主题。"""
    text = output_str.lower()
    hits = [t for t in required_themes if t.lower() in text]
    return {
        "total": len(required_themes),
        "hits": hits,
        "misses": [t for t in required_themes if t.lower() not in text],
        "score": len(hits) / max(len(required_themes), 1),
    }


def check_forbidden(output_str: str, forbidden_claims: list[str]) -> dict:
    """检查输出中是否出现了禁止编造的内容。"""
    text = output_str.lower()
    hits = [c for c in forbidden_claims if c.lower() in text]
    return {
        "total": len(forbidden_claims),
        "hits": hits,
        "score": 1.0 - len(hits) / max(len(forbidden_claims), 1) if forbidden_claims else 1.0,
    }


def check_empty(output: dict | str | None) -> dict:
    """检查输出是否为空或无效。"""
    if output is None:
        return {"is_empty": True, "score": 0.0}
    if isinstance(output, str):
        stripped = output.strip()
        empty = len(stripped) < 20 and any(
            g in stripped for g in ["你好", "请提供", "请问", "好的"]
        )
        return {"is_empty": empty, "score": 0.0 if empty else 1.0}
    if isinstance(output, dict):
        empty = len(output) == 0 or all(not v for v in output.values() if isinstance(v, (str, list)))
        return {"is_empty": empty, "score": 0.0 if empty else 1.0}
    return {"is_empty": False, "score": 1.0}


# ── LLM Judge ──

_JUDGE_PROMPT = """你是一个评测裁判，负责评估求职助手的回答质量。

## 评估维度

对每个维度给出 1-5 分，参考以下锚点：

### 准确性 (accuracy)
- 5: 所有分析都与简历和JD一致，无事实错误
- 4: 主要分析正确，有1处不准确但不影响结论
- 3: 大方向对，有2-3处细节偏差
- 2: 有明显事实错误，影响了结论
- 1: 完全错误或编造了不存在的信息

### 相关性 (relevance)
- 5: 每条建议都针对该岗位的具体要求
- 4: 大部分贴合，个别建议通用化
- 3: 部分建议通用，部分贴合
- 2: 大部分建议与岗位无关
- 1: 全是空话，换个岗位也能用

### 完整性 (completeness)
- 5: 覆盖所有关键维度，无遗漏
- 4: 覆盖主要维度，1个次要维度未提
- 3: 覆盖主要维度，个别次要维度未提
- 2: 遗漏了1个重要维度
- 1: 遗漏多个重要维度

### 具体性 (specificity)
- 5: 每条建议指向具体技能/项目位置，有可操作步骤
- 4: 大部分建议具体，少数笼统
- 3: 部分建议具体，部分笼统
- 2: 大部分笼统
- 1: 全是"建议提升技能"类空话

### 真实性 (authenticity)
- 5: 完全基于用户提供的信息，无任何编造
- 4: 有1处不确定的推断但不影响使用
- 3: 有1处合理推断但未标注为推测
- 2: 有少量编造或过度推断
- 1: 编造了经历、项目、技术栈

## 系统输出
{system_output}

## 参考答案
{reference}

请直接输出 JSON（不要 markdown 代码块）：
{{
  "accuracy": <int>,
  "relevance": <int>,
  "completeness": <int>,
  "specificity": <int>,
  "authenticity": <int>,
  "overall": <int>,
  "reasoning": "<2-3句简述评分理由>"
}}"""


@dataclass
class JudgeResult:
    """单次 LLM Judge 评分结果。"""
    accuracy: float = 0
    relevance: float = 0
    completeness: float = 0
    specificity: float = 0
    authenticity: float = 0
    overall: float = 0
    reasoning: str = ""
    raw: dict | None = None

    def to_dict(self) -> dict:
        return {
            "accuracy": self.accuracy,
            "relevance": self.relevance,
            "completeness": self.completeness,
            "specificity": self.specificity,
            "authenticity": self.authenticity,
            "overall": self.overall,
            "reasoning": self.reasoning,
        }


@dataclass
class StableJudgeResult:
    """多次采样后的稳定评分（取中位数）。"""
    accuracy: float = 0
    relevance: float = 0
    completeness: float = 0
    specificity: float = 0
    authenticity: float = 0
    overall: float = 0
    reasoning: str = ""
    stability: dict = field(default_factory=dict)  # 各维度标准差
    samples: list[JudgeResult] = field(default_factory=list)
    reliable: bool = True

    def to_dict(self) -> dict:
        return {
            "accuracy": self.accuracy,
            "relevance": self.relevance,
            "completeness": self.completeness,
            "specificity": self.specificity,
            "authenticity": self.authenticity,
            "overall": self.overall,
            "reasoning": self.reasoning,
            "stability": self.stability,
            "samples": len(self.samples),
            "reliable": self.reliable,
        }


def _call_judge_once(system_output: str, reference: str) -> JudgeResult | None:
    """调用一次 LLM Judge。"""
    prompt = _JUDGE_PROMPT.format(
        system_output=system_output[:3000],
        reference=reference[:2000],
    )
    try:
        raw = invoke_llm(prompt)
        # 清理可能的 markdown 包裹
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        data = json.loads(cleaned.strip())
        return JudgeResult(
            accuracy=int(data.get("accuracy", 3)),
            relevance=int(data.get("relevance", 3)),
            completeness=int(data.get("completeness", 3)),
            specificity=int(data.get("specificity", 3)),
            authenticity=int(data.get("authenticity", 3)),
            overall=int(data.get("overall", 3)),
            reasoning=str(data.get("reasoning", "")),
            raw=data,
        )
    except Exception as exc:
        logger.warning("LLM Judge call failed: %s", exc)
        return None


def llm_judge(
    system_output: str,
    reference: str,
    samples: int = 3,
) -> StableJudgeResult:
    """LLM-as-Judge 评分（多次采样取中位数，评估稳定性）。"""
    results: list[JudgeResult] = []
    for _ in range(samples):
        result = _call_judge_once(system_output, reference)
        if result:
            results.append(result)
        time.sleep(0.3)  # 避免 API 限流

    if not results:
        return StableJudgeResult(samples=[], reliable=False, reasoning="LLM Judge 全部调用失败")

    # 取中位数
    dims = ["accuracy", "relevance", "completeness", "specificity", "authenticity", "overall"]
    medians: dict = {}
    stabilities: dict = {}
    for dim in dims:
        values = [getattr(r, dim) for r in results]
        medians[dim] = statistics.median(values)
        if len(values) >= 2:
            stabilities[dim] = round(statistics.stdev(values), 2)

    # 取 reasoning 用的是中位数最接近的那次
    best = min(results, key=lambda r: abs(r.overall - medians["overall"]))

    # 可靠性判断：overall 的 std 超过 1.5 标记为不可靠
    reliable = stabilities.get("overall", 0) <= 1.5

    return StableJudgeResult(
        accuracy=medians["accuracy"],
        relevance=medians["relevance"],
        completeness=medians["completeness"],
        specificity=medians["specificity"],
        authenticity=medians["authenticity"],
        overall=medians["overall"],
        reasoning=best.reasoning,
        stability=stabilities,
        samples=results,
        reliable=reliable,
    )


# ── 规则 + LLM Judge 统一评分 ──


@dataclass
class CaseScore:
    """单条用例的完整评分。"""
    case_name: str
    # 规则层
    structure: dict = field(default_factory=dict)
    themes: dict = field(default_factory=dict)
    forbidden: dict = field(default_factory=dict)
    empty: dict = field(default_factory=dict)
    latency_ms: float = 0
    rule_score: float = 0
    # LLM Judge
    judge: StableJudgeResult | None = None
    # 综合
    final_score: float = 0
    passed: bool = True
    errors: list[str] = field(default_factory=list)


def score_case(
    case_name: str,
    output: dict | str | None,
    raw_output: str,
    checks: dict,
    reference: str,
    latency_ms: float,
    enable_llm_judge: bool = True,
    judge_samples: int = 3,
) -> CaseScore:
    """对一条用例执行完整评分（规则 + LLM Judge）。"""
    result = CaseScore(case_name=case_name, latency_ms=latency_ms)
    output_str = raw_output if raw_output else json.dumps(output or {}, ensure_ascii=False)

    # 规则层
    if "required_fields" in checks:
        result.structure = check_structure(output if isinstance(output, dict) else {}, checks["required_fields"])

    if "required_themes" in checks:
        result.themes = check_themes(output_str, checks["required_themes"])

    if "forbidden_claims" in checks:
        result.forbidden = check_forbidden(output_str, checks["forbidden_claims"])

    result.empty = check_empty(output)

    # 规则综合分
    rule_components = [result.structure, result.themes, result.forbidden, result.empty]
    rule_scores = [c.get("score", 1.0) for c in rule_components if c]
    result.rule_score = sum(rule_scores) / len(rule_scores) if rule_scores else 1.0

    # LLM Judge
    if enable_llm_judge and reference:
        result.judge = llm_judge(output_str, reference, samples=judge_samples)

    # 综合分 = 规则 * 0.4 + Judge * 0.6（如果 Judge 可用）
    if result.judge and result.judge.reliable:
        result.final_score = round(result.rule_score * 0.4 + (result.judge.overall / 5.0) * 0.6, 2)
    else:
        result.final_score = round(result.rule_score, 2)

    # 不及格判定：综合分 < 0.5
    result.passed = result.final_score >= 0.5

    # 收集错误
    errors = []
    if not result.structure.get("passed", True):
        errors.append(f"结构缺失: {result.structure.get('missing', [])}")
    if result.empty.get("is_empty"):
        errors.append("空回答")
    if result.forbidden.get("hits"):
        errors.append(f"禁区命中: {result.forbidden['hits']}")
    if result.judge and not result.judge.reliable:
        errors.append(f"Judge 不稳定 (σ={result.judge.stability.get('overall', 'N/A')})")
    result.errors = errors

    return result
