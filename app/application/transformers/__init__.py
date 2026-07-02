"""Transformer 层 — 证据提取与归纳。

注册表 get_transformer(task_type) → BaseTransformer
Phase 3 Step 1: fact_lookup + GenericTransformer
Phase 3 Step 2: + comparison + analysis
"""

from app.application.transformers.base import (
    BaseTransformer,
    GenericTransformer,
    StructuredEvidence,
    RawEvidence,
    DerivedConclusion,
    FactItem,
    SourceRef,
    DimensionRow,
    ScoreDimension,
    PlanPhase,
)

# 延迟导入专用 transformer（避免循环）
_fact_lookup_transformer = None
_comparison_transformer = None
_analysis_transformer = None
_planning_transformer = None
_generic = GenericTransformer()


def get_transformer(task_type: str) -> BaseTransformer:
    """根据 task_type 返回对应的 Transformer。"""
    global _fact_lookup_transformer, _comparison_transformer
    global _analysis_transformer, _planning_transformer

    if task_type == "fact_lookup":
        if _fact_lookup_transformer is None:
            from app.application.transformers.fact_lookup import FactLookupTransformer
            _fact_lookup_transformer = FactLookupTransformer()
        return _fact_lookup_transformer

    if task_type == "comparison":
        if _comparison_transformer is None:
            from app.application.transformers.comparison import ComparisonTransformer
            _comparison_transformer = ComparisonTransformer()
        return _comparison_transformer

    if task_type == "analysis":
        if _analysis_transformer is None:
            from app.application.transformers.analysis import AnalysisTransformer
            _analysis_transformer = AnalysisTransformer()
        return _analysis_transformer

    if task_type == "planning":
        if _planning_transformer is None:
            from app.application.transformers.planning import PlanningTransformer
            _planning_transformer = PlanningTransformer()
        return _planning_transformer

    return _generic


__all__ = [
    "get_transformer",
    "BaseTransformer",
    "GenericTransformer",
    "StructuredEvidence",
    "RawEvidence",
    "DerivedConclusion",
    "FactItem",
    "SourceRef",
    "DimensionRow",
    "ScoreDimension",
    "PlanPhase",
]
