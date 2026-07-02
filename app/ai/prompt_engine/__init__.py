"""Prompt 引擎 — Jinja2 模板管理、Few-shot 注入、效果评估。

架构：
  PromptManager   — 加载 .j2 模板 → 注入 few-shot → 渲染为最终 prompt
  FewShotStore    — YAML 示例库管理（按场景检索、选择策略）
  PromptEvaluator — 测试用例管理、批量评分、v1/v2 AB 对比
"""

from app.ai.prompt_engine.manager import PromptManager
from app.ai.prompt_engine.few_shot import FewShotStore
from app.ai.prompt_engine.evaluator import PromptEvaluator

__all__ = ["PromptManager", "FewShotStore", "PromptEvaluator"]
