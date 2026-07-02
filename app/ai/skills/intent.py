"""意图分类器 — 将用户 goal + 匹配的 Skill + 任务分类器映射为结构化的路由决策。

Phase 2 Round A: 集成 task_classifier，新增 task_type / expected_output_shape 字段。

设计考量：
  - 集中管理 Skill 名称常量和 Intent 类型常量，避免中文 YAML 改名后映射静默失效
  - classify_intent() 是 copilot_run 路由前的唯一决策点
  - decision_source 字段提供结构化路由来源（方便日志聚合）
  - resume_generation 是特殊的 fixed intent：允许 personal_info 替代 resume_id
  - Phase 2: task_classifier.classify_task() 提供以"答案结构"为中心的分类，
    与旧的 Skill 关键词匹配并行，优先使用新分类器决定路由

开发约束：
  新增 Skill 时必须同步更新两处：
  1. app/skills/<name>.yaml — 关键词 + 工具链 + mode
  2. 本文件的 SKILL_* 常量 + SKILL_INTENT_MAP 映射
  漏掉第 2 步 → 新 skill 被分类为 open intent（安全降级到 orchestrator，不会崩溃）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ai.skills.registry import Skill

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Skill 名称常量（集中定义，YAML name 字段必须与此一致）
# ═══════════════════════════════════════════════════════════════

SKILL_MATCH_ANALYZE = "匹配分析"
SKILL_RESUME_OPTIMIZE = "简历优化"
SKILL_INTERVIEW_PREP = "面试题生成"
SKILL_FULL_PREP = "全面备战"
SKILL_CUSTOM_RESUME = "定制简历"
SKILL_FIND_JOBS = "岗位推荐"
SKILL_PUBLIC_SEARCH = "公开搜索"
SKILL_FETCH_JOB_PAGE = "岗位页面抓取"

# ═══════════════════════════════════════════════════════════════
# Intent 类型常量
# ═══════════════════════════════════════════════════════════════

INTENT_MATCH_ANALYSIS = "match_analysis"
INTENT_RESUME_OPTIMIZATION = "resume_optimization"
INTENT_INTERVIEW_PREP = "interview_prep"
INTENT_FULL_PREP = "full_prep"
INTENT_RESUME_GENERATION = "resume_generation"
INTENT_INFO_GATHERING = "info_gathering"
INTENT_COMPARISON = "comparison"
INTENT_REVIEW = "review"
INTENT_PLANNING = "planning"
INTENT_JOB_RECOMMENDATION = "job_recommendation"
INTENT_GENERAL_OPEN = "general_open"  # 无 skill 命中时的开放任务

# ═══════════════════════════════════════════════════════════════
# Intent 分组
# ═══════════════════════════════════════════════════════════════

FIXED_INTENT_TYPES = frozenset({
    INTENT_MATCH_ANALYSIS,
    INTENT_RESUME_OPTIMIZATION,
    INTENT_INTERVIEW_PREP,
    INTENT_FULL_PREP,
    INTENT_RESUME_GENERATION,
    INTENT_INFO_GATHERING,  # public_search / fetch_job_page 是单工具确定性链路
})

OPEN_INTENT_TYPES = frozenset({
    INTENT_COMPARISON,
    INTENT_REVIEW,
    INTENT_PLANNING,
    INTENT_JOB_RECOMMENDATION,
    INTENT_GENERAL_OPEN,
})

# ═══════════════════════════════════════════════════════════════
# Skill → Intent 映射（新增 Skill 时此处必须同步更新）
# ═══════════════════════════════════════════════════════════════

SKILL_INTENT_MAP: dict[str, str] = {
    SKILL_MATCH_ANALYZE:   INTENT_MATCH_ANALYSIS,
    SKILL_RESUME_OPTIMIZE: INTENT_RESUME_OPTIMIZATION,
    SKILL_INTERVIEW_PREP:  INTENT_INTERVIEW_PREP,
    SKILL_FULL_PREP:       INTENT_FULL_PREP,
    SKILL_CUSTOM_RESUME:   INTENT_RESUME_GENERATION,
    SKILL_FIND_JOBS:       INTENT_JOB_RECOMMENDATION,
    SKILL_PUBLIC_SEARCH:   INTENT_INFO_GATHERING,
    SKILL_FETCH_JOB_PAGE:  INTENT_INFO_GATHERING,
}

# ── 哪些 fixed intent 允许 personal_info 替代 resume_id ──
_FIXED_ALLOWS_PERSONAL_INFO: frozenset = frozenset({
    INTENT_RESUME_GENERATION,
})


# ═══════════════════════════════════════════════════════════════
# Decision source 常量
# ═══════════════════════════════════════════════════════════════

SOURCE_NO_SKILL_MATCH = "no_skill_match"
SOURCE_FIXED_SKILL_MATCH = "fixed_skill_match"
SOURCE_OPEN_SKILL_MATCH = "open_skill_match"
SOURCE_MIXED_SKILL_MATCH = "mixed_skill_match"
SOURCE_TASK_CLASSIFIER = "task_classifier"  # Phase 2: 路由由 task_classifier 决定，非 Skill 匹配


# ═══════════════════════════════════════════════════════════════
# IntentResult
# ═══════════════════════════════════════════════════════════════

@dataclass
class IntentResult:
    """路由决策结果。"""
    intent_type: str              # INTENT_* 常量（Phase 2: 保留兼容，新代码优先用 task_type）
    route: str                    # "direct_tools" | "orchestrator"
    is_fixed: bool
    decision_source: str          # SOURCE_* 常量
    tools: list[str] = field(default_factory=list)
    matched_skills: list[str] = field(default_factory=list)
    skill_hints: list[dict] = field(default_factory=list)
    rationale: str = ""
    allows_personal_info: bool = False
    # Phase 2 Round A: 任务类型分类
    task_type: str = ""                      # 8 类之一：fact_lookup / comparison / ...
    expected_output_shape: str = ""          # 期望输出结构（自然语言描述）
    execution_mode: str = ""                 # comparison_search | comparison_structured | ""


# ═══════════════════════════════════════════════════════════════
# 分类函数
# ═══════════════════════════════════════════════════════════════

async def classify_intent(
    goal: str,
    matched_skills: "list[Skill]",
    external_urls: list[str] | None = None,
    job_id: int | None = None,
    extra_context_text: str = "",
) -> IntentResult:
    """将用户意图分类为固定/开放任务，决定路由路径。

    Phase 2 Round A 流程：
    1. task_classifier.classify_task(goal) → 获取 task_type + expected_output_shape
    2. 按 task_type 决定 route（rewrite/extraction → direct_tools，其余 → orchestrator）
    3. 对于 direct_tools 路径，从 matched_skills 中提取工具链
    4. 对于 orchestrator 路径，将 matched_skills 转为 skill_hints
    5. 旧 intent_type 字段保留（向后兼容），从 task_type 映射得到
    6. Phase 3: 根据上下文判定 execution_mode（comparison_search / comparison_structured）

    Args:
        goal: 用户输入文本
        matched_skills: skill_registry.match_all() 返回的 Skill 列表
        external_urls: 用户提供的外部 URL 列表
        job_id: 已选定的岗位 ID
        extra_context_text: 额外上下文文本（如 JD 长文本）

    Returns:
        IntentResult，其中 task_type 和 expected_output_shape 已填充
    """
    from app.ai.skills.task_classifier import (
        classify_task, get_route_for_task_type,
        TASK_TYPE_REWRITE, TASK_TYPE_EXTRACTION,
    )

    # ── Step 1: 任务类型分类（含 execution_mode 判定）──
    tc = await classify_task(
        goal,
        external_urls=external_urls,
        job_id=job_id,
        extra_context_text=extra_context_text,
    )
    task_type = tc.task_type
    output_shape = tc.expected_output_shape
    execution_mode = tc.execution_mode

    # ── Step 2: 决定路由 ──
    route = get_route_for_task_type(task_type)

    # ── Step 3: 旧 intent_type 映射（向后兼容）──
    intent_type = _task_type_to_intent(task_type)

    # ── Step 4: 工具链 & skill_hints ──
    tools: list[str] = []
    skill_hints: list[dict] = []
    matched_names: list[str] = []
    is_fixed: bool

    if route == "direct_tools":
        # rewrite / extraction → 从 matched_skills 提取工具链
        tools = _collect_fixed_tools(matched_skills)
        matched_names = [s.name for s in matched_skills]
        for s in matched_skills:
            skill_hints.append(_skill_to_hint(s))

        # ── 防御：工具链为空时降级到 orchestrator ──
        if not tools:
            logger.warning(
                "[IntentClassifier] task_type=%s → direct_tools but no tools extracted "
                "(matched_skills=%s). Falling back to orchestrator.",
                task_type, matched_names,
            )
            route = "orchestrator"
            is_fixed = False
            decision_source = SOURCE_NO_SKILL_MATCH
            rationale = (
                f"任务类型 {task_type}（置信度 {tc.confidence:.0%}）→ "
                f"本应 direct_tools，但无可用工具（Skill 未命中），降级到 orchestrator。"
                f"来源: {tc.source}"
            )
        else:
            is_fixed = True
            decision_source = SOURCE_TASK_CLASSIFIER
            rationale = (
                f"任务类型 {task_type}（置信度 {tc.confidence:.0%}）→ direct_tools，"
                f"工具链 {tools}，分类来源: {tc.source}，Skill: {matched_names}"
            )
    else:
        # orchestrator 路径 → matched_skills 转为 skill_hints
        if not matched_skills:
            decision_source = SOURCE_NO_SKILL_MATCH
            is_fixed = False
            rationale = (
                f"任务类型 {task_type}（置信度 {tc.confidence:.0%}）→ orchestrator，"
                f"无匹配 Skill，分类来源: {tc.source}"
            )
        else:
            # Phase 2: 路由由 task_classifier 决定，Skill 只提供 hints
            decision_source = SOURCE_TASK_CLASSIFIER
            is_fixed = False
            for s in matched_skills:
                matched_names.append(s.name)
                skill_hints.append(_skill_to_hint(s))

            rationale = (
                f"任务类型 {task_type}（置信度 {tc.confidence:.0%}）→ orchestrator，"
                f"匹配 Skill（仅作 hints）: {matched_names}，分类来源: {tc.source}，"
                f"分类理由: {tc.rationale}"
            )

    return IntentResult(
        intent_type=intent_type,
        route=route,
        is_fixed=is_fixed,
        decision_source=decision_source,
        tools=tools,
        matched_skills=matched_names,
        skill_hints=skill_hints,
        rationale=rationale,
        allows_personal_info=(intent_type in _FIXED_ALLOWS_PERSONAL_INFO),
        task_type=task_type,
        expected_output_shape=output_shape,
        execution_mode=execution_mode,
    )


# ═══════════════════════════════════════════════════════════════
# task_type ↔ intent_type 映射（过渡期双向桥接）
# ═══════════════════════════════════════════════════════════════

_TASK_TYPE_TO_INTENT: dict[str, str] = {
    "fact_lookup":       INTENT_INFO_GATHERING,
    "comparison":        INTENT_COMPARISON,
    "planning":          INTENT_PLANNING,
    "analysis":          INTENT_MATCH_ANALYSIS,
    "recommendation":    INTENT_JOB_RECOMMENDATION,
    "rewrite":           INTENT_RESUME_OPTIMIZATION,
    "extraction":        INTENT_INTERVIEW_PREP,
    "decision_support":  INTENT_FULL_PREP,
}


def _task_type_to_intent(task_type: str) -> str:
    """将新 task_type 映射回旧 intent_type（向后兼容）。"""
    return _TASK_TYPE_TO_INTENT.get(task_type, INTENT_GENERAL_OPEN)


# ═══════════════════════════════════════════════════════════════
# 内部辅助
# ═══════════════════════════════════════════════════════════════

def _skill_to_hint(skill: "Skill") -> dict:
    """将 Skill 转为 orchestrator Planner 可用的提示。"""
    hint = {"name": skill.name, "description": skill.description}
    steps = (skill.hints or {}).get("preferred_steps", [])
    if steps:
        tool_names = [st.get("tool", "?") for st in steps]
        hint["description"] = (
            f"{skill.description}（推荐工具链: {' → '.join(tool_names)}）"
        )
    return hint


def _collect_fixed_tools(skills: "list[Skill]") -> list[str]:
    """从固定意图 Skill 中提取 tools，去重保序。"""
    seen = set()
    result = []
    for s in skills:
        for name in (s.tools or []):
            if name not in seen:
                seen.add(name)
                result.append(name)
    return result
