"""意图分类器 — 将用户 goal + 匹配的 Skill 映射为结构化的路由决策。

设计考量：
  - 集中管理 Skill 名称常量和 Intent 类型常量，避免中文 YAML 改名后映射静默失效
  - classify_intent() 是 copilot_run 路由前的唯一决策点
  - decision_source 字段提供结构化路由来源（方便日志聚合）
  - resume_generation 是特殊的 fixed intent：允许 personal_info 替代 resume_id

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


# ═══════════════════════════════════════════════════════════════
# IntentResult
# ═══════════════════════════════════════════════════════════════

@dataclass
class IntentResult:
    """路由决策结果。"""
    intent_type: str              # INTENT_* 常量
    route: str                    # "direct_tools" | "orchestrator"
    is_fixed: bool
    decision_source: str          # SOURCE_* 常量
    tools: list[str] = field(default_factory=list)
    matched_skills: list[str] = field(default_factory=list)
    skill_hints: list[dict] = field(default_factory=list)
    rationale: str = ""
    allows_personal_info: bool = False


# ═══════════════════════════════════════════════════════════════
# 分类函数
# ═══════════════════════════════════════════════════════════════

def classify_intent(goal: str, matched_skills: "list[Skill]") -> IntentResult:
    """将用户意图分类为固定/开放任务，决定路由路径。

    Args:
        goal: 用户输入文本
        matched_skills: skill_registry.match_all() 返回的 Skill 列表

    Returns:
        IntentResult，其中 route 字段指示走 _direct_tools 还是 orchestrator
    """
    if not matched_skills:
        return IntentResult(
            intent_type=INTENT_GENERAL_OPEN,
            route="orchestrator",
            is_fixed=False,
            decision_source=SOURCE_NO_SKILL_MATCH,
            matched_skills=[],
            rationale=f"无匹配 Skill，goal='{goal[:60]}' 作为开放任务交 orchestrator 处理",
        )

    # 按 Skill 名查找 intent type
    fixed_skills: list[dict] = []
    open_skills: list[dict] = []
    unknown_skills: list[str] = []

    for s in matched_skills:
        intent_type = SKILL_INTENT_MAP.get(s.name)
        if intent_type is None:
            unknown_skills.append(s.name)
            # 未知 skill → 安全降级为 open
            open_skills.append(_skill_to_hint(s))
        elif intent_type in FIXED_INTENT_TYPES:
            fixed_skills.append(_skill_to_hint(s))
        else:
            open_skills.append(_skill_to_hint(s))

    if unknown_skills:
        logger.warning(
            "[IntentClassifier] unknown skills not in SKILL_INTENT_MAP: %s",
            unknown_skills,
        )

    # ── 决策 ──
    has_fixed = bool(fixed_skills)
    has_open = bool(open_skills)

    if has_fixed and not has_open:
        # 纯固定意图 → direct_tools
        tools = _collect_fixed_tools(matched_skills)
        intent_types = list(dict.fromkeys(
            SKILL_INTENT_MAP.get(s.name, INTENT_INFO_GATHERING)
            for s in matched_skills
        ))
        return IntentResult(
            intent_type=intent_types[0],
            route="direct_tools",
            is_fixed=True,
            decision_source=SOURCE_FIXED_SKILL_MATCH,
            tools=tools,
            matched_skills=[s.name for s in matched_skills],
            rationale=(
                f"固定意图: 匹配 Skill {[s.name for s in matched_skills]}，"
                f"工具链 {tools}"
            ),
            allows_personal_info=(
                intent_types[0] in _FIXED_ALLOWS_PERSONAL_INFO
            ),
        )

    # 有 open skill 参与 → orchestrator 统一规划
    all_hints = fixed_skills + open_skills
    intent_types = list(dict.fromkeys(
        SKILL_INTENT_MAP.get(s.name, INTENT_INFO_GATHERING)
        for s in matched_skills
    ))
    # 取第一个非 fixed 的 intent type 作为主类型
    primary = next(
        (t for t in intent_types if t not in FIXED_INTENT_TYPES),
        intent_types[0],
    )

    if has_fixed and has_open:
        source = SOURCE_MIXED_SKILL_MATCH
        rationale = (
            f"混合意图: fixed={[h['name'] for h in fixed_skills]}, "
            f"open={[h['name'] for h in open_skills]}，交 orchestrator 统一规划"
        )
    else:
        source = SOURCE_OPEN_SKILL_MATCH
        rationale = (
            f"开放意图: 匹配 Skill {[s.name for s in matched_skills]}，"
            f"需要 Planner 动态生成步骤"
        )

    return IntentResult(
        intent_type=primary,
        route="orchestrator",
        is_fixed=False,
        decision_source=source,
        matched_skills=[s.name for s in matched_skills],
        skill_hints=all_hints,
        rationale=rationale,
    )


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
