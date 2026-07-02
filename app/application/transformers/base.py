"""证据层基类 — StructuredEvidence 模型 + BaseTransformer 抽象。

职责边界（铁律）：
  Transformer 只做三件事：抽取、对齐、归纳。
  不做：任务规划、多轮推理、最终话术生成。

设计约束：
  - extract() 规则优先提取 raw_evidence → LLM 可选增强 derived_conclusion
  - raw_evidence 可信、可复现、不依赖 LLM
  - derived_conclusion 标注 used_llm / based_on / confidence
  - degraded=True 时调用方必须回退到 render_from_outputs
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Evidence 模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class FactItem:
    """一条提取出的关键事实。"""
    fact: str                            # 事实文本
    source_index: int = -1               # 指向 sources 列表的索引（-1 = 无来源）
    confidence: float = 1.0              # 置信度（规则提取 = 1.0，LLM 提取 = 0.5-0.9）


@dataclass
class SourceRef:
    """一个信息来源引用。"""
    title: str
    url: str = ""
    snippet: str = ""
    relevance: float = 1.0               # 与 goal 的相关性 0-1


@dataclass
class DimensionRow:
    """对比维度中的一行：维度名 + 每对象的值。"""
    dimension: str
    values: dict[str, str] = field(default_factory=dict)  # {subject_name: value}
    confidence: float = 1.0


@dataclass
class ScoreDimension:
    """分析维度：维度名 + 评分 + 差距 + 证据原文。"""
    name: str
    score: float = 0.0
    max_score: float = 100.0
    gap_description: str = ""
    evidence: str = ""                   # 引用原文


@dataclass
class PlanPhase:
    """计划阶段。"""
    name: str
    duration: str = ""
    tasks: list[str] = field(default_factory=list)
    checkpoints: list[str] = field(default_factory=list)


@dataclass
class RawEvidence:
    """规则提取的事实 — 可信、可复现、不依赖 LLM。

    字段按 task_type 有选择地填充：
      fact_lookup: facts + sources
      comparison:  subjects + dimensions
      analysis:    scores (dimensions) + gaps + suggestions
      planning:    phases + milestones
    """
    subjects: list[str] = field(default_factory=list)
    dimensions: list[DimensionRow] = field(default_factory=list)
    facts: list[FactItem] = field(default_factory=list)
    sources: list[SourceRef] = field(default_factory=list)
    scores: list[ScoreDimension] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    phases: list[PlanPhase] = field(default_factory=list)
    milestones: list[str] = field(default_factory=list)
    total_timeline: str = ""

    def is_empty(self) -> bool:
        """检查是否完全没有提取到有效证据。"""
        return not any([
            self.subjects, self.dimensions, self.facts, self.sources,
            self.scores, self.gaps, self.suggestions, self.phases,
        ])

    def summary(self) -> str:
        """可观测摘要 — 用于日志输出。"""
        parts = []
        if self.subjects:
            parts.append(f"subjects={self.subjects}")
        if self.dimensions:
            parts.append(f"dimensions={[d.dimension for d in self.dimensions]}")
        if self.facts:
            parts.append(f"facts={len(self.facts)} items")
        if self.sources:
            parts.append(f"sources={len(self.sources)} refs")
        if self.scores:
            parts.append(f"scores={len(self.scores)} dims")
        if self.phases:
            parts.append(f"phases={len(self.phases)}")
        return " | ".join(parts) if parts else "(empty)"


@dataclass
class DerivedConclusion:
    """LLM 归纳的结论 — 可选增强，必须标注来源。"""
    summary: str = ""
    recommendation: str = ""
    confidence: float = 1.0
    used_llm: bool = False
    based_on: list[str] = field(default_factory=list)


@dataclass
class StructuredEvidence:
    """完整的结构化证据 = 规则提取 + 可选 LLM 归纳。"""
    task_type: str
    raw: RawEvidence = field(default_factory=RawEvidence)
    derived: DerivedConclusion | None = None
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False

    def log_summary(self) -> None:
        """输出可观测日志。"""
        logger.info(
            "[Transformer] task_type=%s raw=[%s] derived=%s degraded=%s warnings=%d",
            self.task_type,
            self.raw.summary(),
            f"used_llm={self.derived.used_llm}" if self.derived else "none",
            self.degraded,
            len(self.warnings),
        )
        for w in self.warnings:
            logger.warning("[Transformer] warning: %s", w)


# ═══════════════════════════════════════════════════════════════
# BaseTransformer
# ═══════════════════════════════════════════════════════════════

class BaseTransformer(ABC):
    """证据提取器基类。

    生命周期：
      1. extract(goal, outputs, context) → StructuredEvidence
      2. 调用方检查 evidence.degraded：True → 回退 render_from_outputs
      3. 调用方调 to_context(evidence) → 注入 AnswerTemplate
    """

    task_type: str = ""

    @abstractmethod
    async def extract(
        self,
        goal: str,
        outputs: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> StructuredEvidence:
        """从工具输出中提取结构化证据。

        实现规范：
          1. 规则提取 raw_evidence（必须先做，不依赖 LLM）
          2. 如果 raw_evidence 非空 → 可选调 fast LLM 生成 derived_conclusion
          3. 如果 fast LLM 不可用 → degraded=True, derived=None
          4. 如果 raw_evidence 为空 → degraded=True（回退到 Phase 2 逻辑）
        """
        ...

    def to_context(self, evidence: StructuredEvidence) -> dict[str, Any]:
        """将 evidence 转为可注入 AnswerTemplate 的 context 字典。

        调用方将此 dict merge 到 context 中传给模板。
        """
        ctx: dict[str, Any] = {
            "evidence": evidence,
            "evidence_degraded": evidence.degraded,
        }
        if evidence.derived and evidence.derived.summary:
            ctx["evidence_summary"] = evidence.derived.summary
        if evidence.derived and evidence.derived.recommendation:
            ctx["evidence_recommendation"] = evidence.derived.recommendation
        return ctx


# ═══════════════════════════════════════════════════════════════
# GenericTransformer — pass-through 兜底
# ═══════════════════════════════════════════════════════════════

class GenericTransformer(BaseTransformer):
    """通用 pass-through transformer — 不做提取，保留 Phase 2 行为。

    用于所有低频任务类型（recommendation / rewrite / extraction / decision_support）
    以及未实现专用 transformer 的类型。
    """

    task_type = "__generic__"

    async def extract(
        self,
        goal: str,
        outputs: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> StructuredEvidence:
        # 从 outputs 中做最低限度的规则提取（只提取 sources 和基础事实）
        raw = RawEvidence()
        for out in outputs:
            items = out.get("content", {}).get("items", [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        title = str(item.get("title", ""))
                        url = str(item.get("url", ""))
                        snippet = str(item.get("snippet", ""))
                        if title:
                            raw.sources.append(SourceRef(
                                title=title[:200], url=url,
                                snippet=snippet[:300],
                            ))
                            if snippet:
                                raw.facts.append(FactItem(
                                    fact=snippet[:200],
                                    source_index=len(raw.sources) - 1,
                                ))

        return StructuredEvidence(
            task_type=context.get("task_type", "") if context else "",
            raw=raw,
            degraded=True,  # generic 不做归纳 → 调用方走 render_from_outputs
            warnings=["GenericTransformer: pass-through mode, no extraction performed"],
        )
