"""Agent Skill 系统 — YAML 可配置技能，前后端共用。"""
from app.ai.skills.intent import (
    FIXED_INTENT_TYPES,
    OPEN_INTENT_TYPES,
    IntentResult,
    classify_intent,
)
from app.ai.skills.registry import SkillRegistry

__all__ = [
    "SkillRegistry",
    "IntentResult",
    "classify_intent",
    "FIXED_INTENT_TYPES",
    "OPEN_INTENT_TYPES",
]
