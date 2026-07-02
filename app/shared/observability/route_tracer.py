"""路由追踪 — 输出结构化 JSON 日志，回答"为什么走这条路"。

用法:
    from app.shared.observability.route_tracer import trace_route

    trace_route(session_id=42, user_id=7, goal="全面备战",
                intent_result=classify_intent(...), duration_ms=1.5)
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

from app.shared.observability.tracer import get_request_id, get_trace_id

if TYPE_CHECKING:
    from app.ai.skills.intent import IntentResult

logger = logging.getLogger("route_tracer")


def trace_route(
    session_id: int,
    user_id: int,
    goal: str,
    intent_result: "IntentResult",
    duration_ms: float,
) -> None:
    """输出单行 JSON 路由决策日志。

    字段说明:
      - decision_source: no_skill_match | fixed_skill_match | open_skill_match
                        | mixed_skill_match | task_classifier (Phase 2: 分类器决定路由)
      - route: direct_tools | orchestrator
      - rationale: 人类可读的决策说明
    """
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "event": "route_decision",
        "request_id": get_request_id(),
        "trace_id": get_trace_id(),
        "session_id": session_id,
        "user_id": user_id,
        "goal_preview": (goal or "")[:120],
        "intent_type": intent_result.intent_type,
        "task_type": intent_result.task_type,
        "execution_mode": intent_result.execution_mode,
        "route": intent_result.route,
        "decision_source": intent_result.decision_source,
        "is_fixed": intent_result.is_fixed,
        "tools": intent_result.tools,
        "matched_skills": intent_result.matched_skills,
        "rationale": intent_result.rationale,
        "route_duration_ms": round(duration_ms, 2),
    }
    logger.info(json.dumps(record, ensure_ascii=False))
