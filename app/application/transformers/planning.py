"""PlanningTransformer — 解析已有计划文本为结构化证据（parse-only）。

Phase 3 约束：PlanningTransformer 只做解析，不生成新计划。
计划内容由 _finalizer 生成，transformer 只负责将其结构化以便模板渲染。

规则提取：
  1. 从 outputs text 中按 ##/阶段/Phase/Day/Week 分块解析阶段
  2. 提取每阶段的任务列表和检查点
  3. 提取里程碑和时间线
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.application.transformers.base import (
    BaseTransformer,
    PlanPhase,
    RawEvidence,
    StructuredEvidence,
)

logger = logging.getLogger(__name__)

# 阶段识别模式
_PHASE_MARKERS = [
    r"(?:阶段|Phase)\s*[一二三四五六七八1-9]",
    r"第[一二三四五六七八1-9]\s*(?:阶段|周|步|部分)",
    r"Day\s*\d+",
    r"Week\s*\d+",
    r"##\s+",
]


class PlanningTransformer(BaseTransformer):
    """计划解析器 — 只解析，不生成。"""

    task_type = "planning"

    async def extract(
        self,
        goal: str,
        outputs: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> StructuredEvidence:
        warnings: list[str] = []
        raw = RawEvidence()

        full_text = ""
        for out in outputs:
            full_text += out.get("text", "") + "\n"

        if not full_text.strip():
            warnings.append("计划文本为空")
            return StructuredEvidence(
                task_type=self.task_type, raw=raw,
                warnings=warnings, degraded=True,
            )

        # ── 解析阶段 ──
        raw.phases = self._parse_phases(full_text)
        if not raw.phases:
            # 没有识别到阶段 → 尝试将全文作为一个阶段
            tasks = [l.strip().lstrip("- *").strip() for l in full_text.split("\n")
                     if l.strip() and not l.strip().startswith("#")]
            tasks = [t for t in tasks if len(t) > 5][:10]
            if tasks:
                raw.phases.append(PlanPhase(
                    name="执行计划",
                    tasks=tasks,
                ))
                warnings.append("未识别到明确的阶段划分，将全文作为一个阶段处理")

        # ── 提取里程碑 ──
        raw.milestones = self._extract_milestones(full_text)

        # ── 提取总时间线 ──
        raw.total_timeline = self._extract_timeline(full_text, goal)

        logger.info(
            "[PlanningTransformer] parsed: phases=%d milestones=%d",
            len(raw.phases), len(raw.milestones),
        )

        evidence = StructuredEvidence(
            task_type=self.task_type,
            raw=raw,
            degraded=not raw.phases,
            warnings=warnings,
        )
        evidence.log_summary()
        return evidence

    # ── 内部方法 ──

    @staticmethod
    def _parse_phases(text: str) -> list[PlanPhase]:
        """从 Markdown 文本中解析阶段。"""
        phases: list[PlanPhase] = []

        # 按 ## 标题分块（每个 ## 标题可能是一个阶段）
        sections = re.split(r"\n(?=##\s+)", text)
        if len(sections) <= 1:
            # 没有 ## 标题，尝试按其他模式分块
            sections = re.split(r"\n(?=(?:阶段|Phase|第[一二三四五六七八1-9]))", text)

        for section in sections:
            section = section.strip()
            if not section:
                continue

            lines = section.split("\n")
            header = lines[0].strip().lstrip("#").strip()

            # 检查是否像阶段标题
            is_phase = any(re.search(p, header) for p in _PHASE_MARKERS)
            if not is_phase and len(sections) == 1:
                is_phase = True  # 只有一个 section 时直接作为阶段

            if not is_phase:
                continue

            tasks: list[str] = []
            checkpoints: list[str] = []
            for line in lines[1:]:
                stripped = line.strip().lstrip("- *1234567890. ").strip()
                if not stripped or len(stripped) < 5:
                    continue
                if any(kw in stripped for kw in ("检查点", "验收标准", "里程碑", "目标：")):
                    checkpoints.append(stripped[:150])
                else:
                    tasks.append(stripped[:150])

            if tasks or checkpoints:
                phases.append(PlanPhase(
                    name=header[:80],
                    duration="",
                    tasks=tasks[:8],
                    checkpoints=checkpoints[:3],
                ))

        return phases

    @staticmethod
    def _extract_milestones(text: str) -> list[str]:
        """提取里程碑描述。"""
        milestones: list[str] = []
        for line in text.split("\n"):
            stripped = line.strip().lstrip("- *").strip()
            if any(kw in stripped for kw in ("里程碑", "检查点", "目标", "到第", "完成")):
                if len(stripped) > 8:
                    milestones.append(stripped[:150])
        return milestones[:5]

    @staticmethod
    def _extract_timeline(text: str, goal: str) -> str:
        """提取总时间线描述。"""
        patterns = [
            r"(?:总|整个|全部).{0,10}(?:周期|时间|时长|计划).{0,20}",
            r"\d+\s*(?:天|周|月|日)",
        ]
        for p in patterns:
            match = re.search(p, text)
            if match:
                return match.group(0)[:80]
        return ""
