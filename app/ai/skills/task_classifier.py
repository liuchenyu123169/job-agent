"""任务分类器 — 将用户 goal 映射为以"答案结构"为中心的任务类型。

Phase 2 Round A: 8 类任务分类 + expected_output_shape 定义。

两级分类：
  L1 — 规则锚点匹配（<1ms，覆盖 ~60% 请求）
  L2 — fast 模型 few-shot 分类（~200ms，覆盖剩余 ~40%）

设计约束：
  - 不依赖 Skill 系统（独立于 intent.py 的 keyword matching）
  - fact_lookup 是默认兜底（最安全：搜信息总比瞎分析强）
  - 误分到相邻类型（如 comparison→analysis）的伤害远小于误分到错误大类
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 任务类型常量
# ═══════════════════════════════════════════════════════════════

TASK_TYPE_FACT_LOOKUP = "fact_lookup"
TASK_TYPE_COMPARISON = "comparison"
TASK_TYPE_PLANNING = "planning"
TASK_TYPE_ANALYSIS = "analysis"
TASK_TYPE_RECOMMENDATION = "recommendation"
TASK_TYPE_REWRITE = "rewrite"
TASK_TYPE_EXTRACTION = "extraction"
TASK_TYPE_DECISION_SUPPORT = "decision_support"

TaskType = Literal[
    "fact_lookup",
    "comparison",
    "planning",
    "analysis",
    "recommendation",
    "rewrite",
    "extraction",
    "decision_support",
]

ALL_TASK_TYPES: list[TaskType] = [
    TASK_TYPE_FACT_LOOKUP,
    TASK_TYPE_COMPARISON,
    TASK_TYPE_PLANNING,
    TASK_TYPE_ANALYSIS,
    TASK_TYPE_RECOMMENDATION,
    TASK_TYPE_REWRITE,
    TASK_TYPE_EXTRACTION,
    TASK_TYPE_DECISION_SUPPORT,
]

# Round A 高频类型（有专属 plan 模板的类型）
HIGH_FREQ_TYPES: frozenset = frozenset({
    TASK_TYPE_FACT_LOOKUP,
    TASK_TYPE_COMPARISON,
    TASK_TYPE_PLANNING,
    TASK_TYPE_ANALYSIS,
})

# ═══════════════════════════════════════════════════════════════
# Expected Output Shapes — Round A 用于注入 planner / Round B 用于 finalizer
# ═══════════════════════════════════════════════════════════════

EXPECTED_OUTPUT_SHAPES: dict[str, str] = {
    TASK_TYPE_FACT_LOOKUP: (
        "自然语言摘要（3-5句）直接回答用户的具体问题 + 关键信息列表（≥2条）+ "
        "来源引用（标题+URL）。禁止输出纯链接列表。"
    ),
    TASK_TYPE_COMPARISON: (
        "对比结论（一句话推荐）+ 多维对比表（≥3个维度）+ "
        "每选项详细分析 + 最终建议。必须有明确结论，禁止平铺链接。"
    ),
    TASK_TYPE_PLANNING: (
        "计划名称 + 目标概述 + 分阶段时间线（≥2个阶段）+ "
        "每阶段具体任务（≥3条）+ 检查点/里程碑（≥2个）+ 时间节点。"
    ),
    TASK_TYPE_ANALYSIS: (
        "综合评分/等级 + 维度拆解分析（≥3个维度）+ "
        "具体差距描述（引用原文/数据）+ 可执行改进建议（≥3条）。"
    ),
    TASK_TYPE_RECOMMENDATION: (
        "排名列表（≥3个候选项）+ 每项推荐理由 + 匹配度评分 + "
        "综合建议。排序必须有区分度。"
    ),
    TASK_TYPE_REWRITE: (
        "原文 vs 改写对照 + 改动说明（每处改动配理由）+ "
        "优化效果说明（量化/具体化）。"
    ),
    TASK_TYPE_EXTRACTION: (
        "结构化列表（≥8项）+ 每项有标题+内容+难度/类别标记 + "
        "分类分组（≥3类）。"
    ),
    TASK_TYPE_DECISION_SUPPORT: (
        "多模块报告（≥2个模块）+ 模块间逻辑衔接 + "
        "综合建议（基于所有模块的结论）。"
    ),
}

# ═══════════════════════════════════════════════════════════════
# L1 规则锚点
# ═══════════════════════════════════════════════════════════════

# 顺序敏感：先匹配到的优先。decision_support 放最前面防止被子类型截胡。
_ANCHOR_RULES: list[tuple[str, list[str]]] = [
    (TASK_TYPE_DECISION_SUPPORT, [
        "全面备战", "一条龙", "完整准备", "全套", "全方位",
    ]),
    (TASK_TYPE_COMPARISON, [
        "对比", "比较", "vs", "versus", "哪个好", "哪个更", "区别",
        "选哪个", "怎么选", "二选一", "三选一",
    ]),
    (TASK_TYPE_PLANNING, [
        "计划", "安排", "路线图", "时间表", "日程", "规划", "路线",
        "提升路线", "学习路径",
    ]),
    (TASK_TYPE_ANALYSIS, [
        "分析", "匹配度", "打分", "评估", "诊断", "复盘",
        "我适合", "适合我吗", "怎么样",
    ]),
    (TASK_TYPE_REWRITE, [
        "优化简历", "改写", "修改简历", "润色", "完善简历",
        "生成简历", "定制简历", "做简历", "制作简历",
        "帮我改", "帮我写",
    ]),
    (TASK_TYPE_EXTRACTION, [
        "面试题", "出题", "题目", "问题列表", "考题", "面试准备",
        "给我.*题", "生成.*题",
    ]),
    (TASK_TYPE_RECOMMENDATION, [
        "推荐", "适合我的岗位", "筛选", "找岗位", "哪些岗位",
        "有没有.*岗位", "帮我找", "帮我选",
    ]),
]


def _match_anchor_rules(goal: str) -> tuple[str | None, float]:
    """L1 规则锚点匹配。返回 (task_type, confidence)。"""
    import re
    for task_type, patterns in _ANCHOR_RULES:
        for pattern in patterns:
            if re.search(pattern, goal):
                # 多个模式命中同一类型 → 更高置信度
                hit_count = sum(1 for p in patterns if re.search(p, goal))
                confidence = min(0.95, 0.7 + hit_count * 0.08)
                return task_type, confidence
    return None, 0.0


# ═══════════════════════════════════════════════════════════════
# L2 fast 模型分类
# ═══════════════════════════════════════════════════════════════

_CLASSIFY_PROMPT = """你是任务类型分类器。根据用户输入，判断它属于以下 8 类中的哪一类。

## 任务类型定义

1. **fact_lookup** — 查事实/信息。
   用户想知道某个具体事实、数据、资料。
   示例："腾讯后端用什么技术栈"、"字节企业文化怎么样"、"Go 语言最新版本特性"

2. **comparison** — 对比多个选项。
   用户想比较两个或多个对象，做出选择。
   示例："对比腾讯和字节的后端岗位"、"Go 和 Rust 哪个更适合微服务"

3. **planning** — 制定计划/路线。
   用户想要一个分步骤的行动计划、学习路线、时间安排。
   示例："给我一个两周的 Go 学习计划"、"面试冲刺安排"

4. **analysis** — 分析/评估/复盘。
   用户想深入了解某事物的优劣、匹配度、原因。
   示例："分析我和这个岗位的匹配度"、"复盘昨天的面试表现"

5. **recommendation** — 推荐/筛选。
   用户想从多个候选中得到推荐。
   示例："推荐适合我的岗位"、"有哪些值得关注的开源项目"

6. **rewrite** — 改写/优化/生成文本。
   用户想改进、重写、生成一份文档或文本。
   示例："帮我优化简历"、"生成一份求职信"

7. **extraction** — 抽取/生成结构化内容。
   用户想从某个主题中抽取或生成结构化列表。
   示例："给我出 10 道 Python 面试题"、"列出这个岗位的核心要求"

8. **decision_support** — 综合决策支持。
   用户想要多步骤、多模块的完整分析链路。
   示例："全面备战这个岗位"、"帮我从零准备腾讯面试"

## 用户输入
{{ goal }}

## 输出要求
只输出一个 JSON 对象，不要输出解释：
```json
{
  "task_type": "fact_lookup",
  "rationale": "用户想查询腾讯的技术栈信息，属于事实查询"
}
```"""


async def _classify_with_llm(goal: str) -> tuple[str, float, str]:
    """L2 fast 模型分类。返回 (task_type, confidence, rationale)。"""
    from app.ai.prompt_engine import PromptManager
    import asyncio

    pm = PromptManager(version="v1")
    # 手动渲染（此模板不是 jinja2 文件，直接用字符串替换）
    prompt = _CLASSIFY_PROMPT.replace("{{ goal }}", goal)

    try:
        from app.ai.llm import invoke_llm
        response: str = await asyncio.to_thread(
            invoke_llm, prompt, model_key="fast"
        )
    except Exception as exc:
        logger.warning("[TaskClassifier] L2 LLM call failed: %s, fallback to fact_lookup", exc)
        return TASK_TYPE_FACT_LOOKUP, 0.3, f"LLM 调用失败，兜底: {exc}"

    import json
    import re
    try:
        data = json.loads(response.strip())
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                logger.warning("[TaskClassifier] L2 JSON parse failed, fallback to fact_lookup")
                return TASK_TYPE_FACT_LOOKUP, 0.3, "LLM 输出无法解析，兜底"
        else:
            logger.warning("[TaskClassifier] L2 no JSON found, fallback to fact_lookup")
            return TASK_TYPE_FACT_LOOKUP, 0.3, "LLM 输出无 JSON，兜底"

    task_type = data.get("task_type", TASK_TYPE_FACT_LOOKUP)
    rationale = data.get("rationale", "")
    if task_type not in EXPECTED_OUTPUT_SHAPES:
        task_type = TASK_TYPE_FACT_LOOKUP
        rationale = f"未知类型兜底: {rationale}"

    return task_type, 0.80, rationale


# ═══════════════════════════════════════════════════════════════
# 主分类函数
# ═══════════════════════════════════════════════════════════════

@dataclass
class TaskClassification:
    """任务分类结果。"""
    task_type: str             # 8 类之一
    confidence: float          # 0.0–1.0
    rationale: str             # 为什么分到这类
    expected_output_shape: str # 期望输出结构描述
    source: str                # "anchor_rule" | "llm_fast" | "fallback"
    is_high_freq: bool         # Round A 是否有专属 plan 模板
    execution_mode: str = ""   # comparison_search | comparison_structured | ""


async def classify_task(
    goal: str,
    external_urls: list[str] | None = None,
    job_id: int | None = None,
    extra_context_text: str = "",
) -> TaskClassification:
    """将用户 goal 分类为 8 种任务类型之一。

    L1 规则锚点匹配 → L2 fast 模型分类 → fact_lookup 兜底。
    同时根据上下文判定 execution_mode。

    Args:
        goal: 用户输入文本
        external_urls: 用户提供的外部 URL 列表
        job_id: 已选定的岗位 ID
        extra_context_text: 额外上下文文本

    Returns:
        TaskClassification（含 execution_mode）
    """
    # ── L1: 规则锚点 ──
    task_type, confidence = _match_anchor_rules(goal)
    if task_type is not None and confidence >= 0.75:
        logger.info(
            "[TaskClassifier] L1 anchor match: type=%s confidence=%.2f goal='%s'",
            task_type, confidence, goal[:60],
        )
        execution_mode = determine_execution_mode(
            task_type,
            external_urls=external_urls,
            job_id=job_id,
            extra_context_text=extra_context_text,
        )
        return TaskClassification(
            task_type=task_type,
            confidence=confidence,
            rationale=f"关键词锚点匹配: {task_type}",
            expected_output_shape=EXPECTED_OUTPUT_SHAPES[task_type],
            source="anchor_rule",
            is_high_freq=task_type in HIGH_FREQ_TYPES,
            execution_mode=execution_mode,
        )

    # ── L2: fast 模型分类 ──
    if task_type is not None:
        logger.info(
            "[TaskClassifier] L1 low confidence (%.2f), escalating to L2 LLM", confidence,
        )

    task_type, confidence, rationale = await _classify_with_llm(goal)
    logger.info(
        "[TaskClassifier] L2 result: type=%s confidence=%.2f goal='%s' rationale='%s'",
        task_type, confidence, goal[:60], rationale[:60],
    )

    execution_mode = determine_execution_mode(
        task_type,
        external_urls=external_urls,
        job_id=job_id,
        extra_context_text=extra_context_text,
    )
    return TaskClassification(
        task_type=task_type,
        confidence=confidence,
        rationale=rationale,
        expected_output_shape=EXPECTED_OUTPUT_SHAPES[task_type],
        source="llm_fast" if confidence >= 0.5 else "fallback",
        is_high_freq=task_type in HIGH_FREQ_TYPES,
        execution_mode=execution_mode,
    )


# ═══════════════════════════════════════════════════════════════
# Route 映射（哪些 task_type 走 direct_tools）
# ═══════════════════════════════════════════════════════════════

# rewrite 和 extraction 有确定性工具链，不需要 planner 编排
DIRECT_TOOLS_TASK_TYPES: frozenset = frozenset({
    TASK_TYPE_REWRITE,
    TASK_TYPE_EXTRACTION,
})


def get_route_for_task_type(task_type: str) -> str:
    """根据 task_type 返回路由路径。"""
    if task_type in DIRECT_TOOLS_TASK_TYPES:
        return "direct_tools"
    return "orchestrator"


def determine_execution_mode(
    task_type: str,
    external_urls: list[str] | None = None,
    job_id: int | None = None,
    extra_context_text: str = "",
) -> str:
    """根据任务类型和可用上下文判定 execution_mode。

    规则：
      comparison + 有 URL / job_id / JD 长文本 → comparison_structured
      comparison + 只有自然语言目标 → comparison_search
      其他 task_type → ""（不适用）
    """
    if task_type != TASK_TYPE_COMPARISON:
        return ""

    has_structured_input = bool(
        (external_urls and len(external_urls) > 0)
        or (job_id is not None)
        or (len(extra_context_text) > 100)
    )

    if has_structured_input:
        return "comparison_structured"
    return "comparison_search"
