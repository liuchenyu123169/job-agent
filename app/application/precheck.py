"""Precheck — 按任务类型动态判断前置条件，而非扫 step 工具需求。

与 orchestrator._precheck 的区别：
  - 旧: 遍历 plan_steps → 看每步工具的 input_requirements → 汇总需要什么
  - 新: 按 task_type 直接判定（任务级 + 场景级）

用法:
    from app.application.precheck import precheck

    ok, blockers = await precheck(task_type, context, user_id)
    if not ok:
        for b in blockers:
            print(b["user_prompt"])  # 直接展示给用户
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.shared.state import PipelineContext

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 任务类型 → 前置条件规则
# ═══════════════════════════════════════════════════════════════

PRECHECK_RULES: dict[str, dict] = {
    "info_gathering": {
        "resume": False,
        "job": False,
        "description": "公开信息搜索，不依赖简历或岗位",
    },
    "match_analysis": {
        "resume": True,
        "job": True,
        "description": "匹配分析需要简历和岗位才能对比",
    },
    "resume_optimization": {
        "resume": True,
        "job": True,
        "description": "简历优化需要目标岗位和现有简历",
    },
    "interview_prep": {
        "resume": True,
        "job": True,
        "description": "面试题生成需要简历和岗位作为出题依据",
    },
    "full_prep": {
        "resume": True,
        "job": True,
        "description": "全面备战需要简历和岗位走完整链路",
    },
    "comparison": {
        # 至少需要"可比较对象"：job_id 或 external_urls 或 extra_context
        "resume": False,
        "job": "optional",       # 有 job 时走结构化对比；无 job 时可用 URL/公开信息对比
        "needs_comparable": True,  # 自定义字段：必须有至少一个可比较对象
        "description": "对比分析需要至少一个可比较对象（岗位/URL/文本）",
    },
    "review": {
        "resume": False,
        "job": False,
        "description": "面试复盘不强制要求简历或岗位",
    },
    "planning": {
        "resume": False,
        "job": False,
        "description": "学习/准备计划不强制要求简历或岗位",
    },
    "general_open": {
        "resume": False,
        "job": False,
        "description": "通用开放任务，无强制前置条件",
    },
}


# ═══════════════════════════════════════════════════════════════

async def precheck(
    task_type: str,
    context: "PipelineContext",
    user_id: int,
    execution_mode: str = "",
) -> tuple[bool, list[dict]]:
    """按任务类型（+ execution_mode）动态判断前置条件。

    Args:
        task_type: 来自 classify_intent() 的 task_type（新 8 类）或 intent_type（旧）
        context: PipelineContext（含 resume_id / job_id / external_urls 等）
        user_id: 当前用户 ID
        execution_mode: comparison_search | comparison_structured | ""

    Returns:
        (ok, blockers):
          - ok=True  → 所有条件满足，可以执行
          - ok=False → blockers 列表，每项含 type/description/resolution_hint/user_prompt
    """
    rules = PRECHECK_RULES.get(task_type)
    if rules is None:
        logger.warning("[Precheck] unknown task_type='%s', falling back to permissive", task_type)
        return True, []

    # ── comparison 按 execution_mode 分流 ──
    if task_type == "comparison" and execution_mode:
        return _precheck_comparison(context, execution_mode)

    blockers: list[dict] = []

    # ── resume 检查 ──
    need_resume = rules.get("resume", False)
    if need_resume and not context.resume_id:
        blockers.append({
            "type": "missing_input",
            "field": "resume",
            "description": f"{task_type} 需要简历才能执行",
            "resolution_hint": "请先在左侧[简历管理]中上传简历",
            "user_prompt": "请先上传简历",
            "resolved": False,
        })

    # ── job 检查 ──
    need_job = rules.get("job", False)
    needs_comparable = rules.get("needs_comparable", False)

    if need_job == "optional" and needs_comparable:
        # comparison: 至少要有"可比较对象"
        has_alternative = bool(
            context.job_id
            or context.external_urls
            or (context.extra_context_text and len(context.extra_context_text) > 50)
        )
        if not has_alternative:
            blockers.append({
                "type": "missing_input",
                "field": "comparable",
                "description": "对比分析需要至少一个可比较对象（岗位/链接/文本）",
                "resolution_hint": "请创建目标岗位、提供岗位链接、或在补充说明中粘贴 JD 文本",
                "user_prompt": "请提供要对比的岗位（可创建岗位、粘贴链接或 JD 文本）",
                "resolved": False,
            })
    elif need_job is True and not context.job_id:
        blockers.append({
            "type": "missing_input",
            "field": "job",
            "description": f"{task_type} 需要目标岗位才能执行",
            "resolution_hint": "请先在左侧[岗位管理]中创建或选择目标岗位",
            "user_prompt": "请先创建目标岗位",
            "resolved": False,
        })

    # ── 数据库验证：resume_id/job_id 存在但记录可能已被删除 ──
    if not blockers and context.resume_id:
        from app.infrastructure.db.crud import get_resume_by_id
        resume = await asyncio.to_thread(get_resume_by_id, context.resume_id, user_id)
        if resume is None:
            blockers.append({
                "type": "missing_input",
                "field": "resume",
                "description": f"简历 id={context.resume_id} 未找到（可能已被删除）",
                "resolution_hint": "请重新上传简历",
                "user_prompt": "当前简历已失效，请重新上传",
                "resolved": False,
            })

    if not blockers and context.job_id and need_job not in (False, "optional"):
        from app.infrastructure.db.crud import get_job_by_id
        job = await asyncio.to_thread(get_job_by_id, context.job_id, user_id)
        if job is None:
            blockers.append({
                "type": "missing_input",
                "field": "job",
                "description": f"岗位 id={context.job_id} 未找到（可能已被删除）",
                "resolution_hint": "请重新创建岗位",
                "user_prompt": "当前岗位已失效，请重新创建",
                "resolved": False,
            })

    if blockers:
        logger.info("[Precheck] task_type=%s BLOCKED: %s", task_type,
                     [b["field"] for b in blockers])
    else:
        logger.info("[Precheck] task_type=%s OK", task_type)

    return len(blockers) == 0, blockers


def _precheck_comparison(
    context: "PipelineContext",
    execution_mode: str,
) -> tuple[bool, list[dict]]:
    """按 execution_mode 判断 comparison 的前置条件。

    comparison_search:
      - 不要求 job_id / external_urls / extra_context_text
      - 比较对象已在 goal 中，后续由 public_search 自己补证据

    comparison_structured:
      - 至少需要一个可比较对象：job_id / external_urls / JD 长文本
    """
    blockers: list[dict] = []

    if execution_mode == "comparison_search":
        logger.info("[Precheck] comparison_search: no prerequisites required")
        return True, []

    if execution_mode == "comparison_structured":
        has_comparable = bool(
            context.job_id
            or context.external_urls
            or (context.extra_context_text and len(context.extra_context_text) > 50)
        )
        if not has_comparable:
            blockers.append({
                "type": "missing_input",
                "field": "comparable",
                "description": "结构化对比需要至少一个可比较对象",
                "resolution_hint": "请创建目标岗位、提供岗位链接、或粘贴 JD 文本",
                "user_prompt": "请提供要对比的岗位链接、JD 文本或选择已有岗位",
                "resolved": False,
            })

    if blockers:
        logger.info("[Precheck] comparison_structured BLOCKED: %s",
                     [b["field"] for b in blockers])
    else:
        logger.info("[Precheck] comparison_structured OK")

    return len(blockers) == 0, blockers
