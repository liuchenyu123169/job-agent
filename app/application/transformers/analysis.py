"""AnalysisTransformer — 从匹配分析输出中解析评分/维度/差距。

规则提取（raw_evidence）：
  1. 从 outputs 的 meta/score 提取综合评分
  2. 从 text 中用正则解析维度评分、差距描述、建议
  3. 如果 match_analyze 输出本就是 Markdown 段落，按标题拆分解析

LLM 增强（derived_conclusion）：
  可选 fast 模型基于解析结果归纳改进建议。
  失败时 degraded=True，规则提取的 scores 仍然有效。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.application.transformers.base import (
    BaseTransformer,
    DerivedConclusion,
    RawEvidence,
    ScoreDimension,
    StructuredEvidence,
)

logger = logging.getLogger(__name__)


class AnalysisTransformer(BaseTransformer):
    """分析/评估证据提取器。"""

    task_type = "analysis"

    async def extract(
        self,
        goal: str,
        outputs: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> StructuredEvidence:
        warnings: list[str] = []
        raw = RawEvidence()

        # ── Step 1: 提取综合评分 ──
        overall_score = self._extract_overall_score(outputs)
        if overall_score is not None:
            # 创建一个维度来承载综合评分
            raw.scores.append(ScoreDimension(
                name="综合匹配度",
                score=overall_score,
                evidence=f"来自工具输出: {outputs[0].get('meta', {}).get('match_score', 'N/A')}" if outputs else "",
            ))

        # ── Step 2: 从文本中解析维度 ──
        for out in outputs:
            text = out.get("text", "")
            if not text:
                continue
            parsed = self._parse_dimensions_from_text(text)
            raw.scores.extend(parsed["scores"])
            raw.gaps.extend(parsed["gaps"])
            raw.suggestions.extend(parsed["suggestions"])

        if not raw.scores and not raw.gaps:
            warnings.append("未能从分析输出中解析到评分或差距")
            return StructuredEvidence(
                task_type=self.task_type, raw=raw,
                warnings=warnings, degraded=True,
            )

        logger.info(
            "[AnalysisTransformer] parsed: scores=%d gaps=%d suggestions=%d",
            len(raw.scores), len(raw.gaps), len(raw.suggestions),
        )

        # ── Step 3: 可选 LLM 归纳建议 ──
        derived = await self._try_summarize_suggestions(goal, raw, warnings)

        # degraded 只反映 raw_evidence 是否为空
        evidence = StructuredEvidence(
            task_type=self.task_type,
            raw=raw,
            derived=derived,
            warnings=warnings,
            degraded=raw.is_empty(),
        )
        evidence.log_summary()
        return evidence

    # ── 内部方法 ──

    @staticmethod
    def _extract_overall_score(outputs: list[dict]) -> float | None:
        """从 outputs 中提取综合评分（数值）。"""
        for out in outputs:
            # meta.match_score
            score = out.get("meta", {}).get("match_score")
            if isinstance(score, (int, float)):
                return float(score)
            # 从 text 中搜索 "XX 分"
            text = out.get("text", "")
            match = re.search(r"(\d{1,3})\s*分", text)
            if match:
                return float(match.group(1))
        return None

    @staticmethod
    def _parse_dimensions_from_text(text: str) -> dict:
        """从 Markdown 文本中解析维度评分、差距、建议。"""
        scores: list[ScoreDimension] = []
        gaps: list[str] = []
        suggestions: list[str] = []

        # 按 ## 标题分块（兼容 ### 子标题）
        sections = re.split(r"\n#{2,3}\s+", text)
        for section in sections:
            section = section.strip()
            if not section:
                continue

            # 尝试提取维度名和评分（仅第一行）
            first_line = section.split("\n")[0].strip()
            dim_match = re.match(r"([^\n]+?)[：:]\s*(\d{1,3})\s*分?", first_line)
            if dim_match:
                name = dim_match.group(1).strip().lstrip("#").strip()
                score = float(dim_match.group(2))
                body = section[len(first_line):].strip()[:200]
                if name and name not in ("综合评分", "总分"):
                    scores.append(ScoreDimension(name=name, score=score, evidence=body))

            # 提取"差距"相关行
            for line in section.split("\n"):
                line = line.strip().lstrip("- *#0123456789. ").strip()
                if any(kw in line for kw in ("差距", "不足", "缺少", "短板", "薄弱")) and len(line) > 10:
                    gaps.append(line[:150])

            # 提取"建议"相关行
            for line in section.split("\n"):
                line = line.strip().lstrip("- *#0123456789. ").strip()
                if any(kw in line for kw in ("建议", "改进", "提升", "优化", "加强", "补充", "学习")) and len(line) > 10:
                    suggestions.append(line[:150])

        return {"scores": scores, "gaps": gaps, "suggestions": suggestions}

    async def _try_summarize_suggestions(
        self, goal: str, raw: RawEvidence, warnings: list[str],
    ) -> DerivedConclusion | None:
        """用 fast 模型归纳改进建议。"""
        import asyncio

        if not raw.suggestions and not raw.gaps:
            return None

        summary_parts = []
        if raw.gaps:
            summary_parts.append(f"主要差距：{'；'.join(raw.gaps[:3])}")
        if raw.suggestions:
            summary_parts.append(f"已有建议：{'；'.join(raw.suggestions[:3])}")
        summary_text = "\n".join(summary_parts)

        prompt = (
            f"用户目标：{goal}\n\n"
            f"分析发现的差距和建议：\n{summary_text}\n\n"
            f"请基于上述信息，用 2-3 句话归纳出最重要的改进方向和优先级建议。"
            f"不要编造新信息。输出纯文本。"
        )

        try:
            from app.ai.llm import invoke_llm
            result: str = await asyncio.to_thread(
                invoke_llm, prompt, model_key="fast",
            )
            result = result.strip()
            if not result or len(result) < 10:
                warnings.append("LLM 建议归纳过短，跳过")
                return None

            logger.info("[AnalysisTransformer] LLM summary (%d chars)", len(result))
            return DerivedConclusion(
                summary=result,
                confidence=0.75,
                used_llm=True,
                based_on=["raw.gaps", "raw.suggestions"],
            )
        except Exception as exc:
            warnings.append(f"LLM 建议归纳失败（{exc}），降级")
            logger.warning("[AnalysisTransformer] LLM failed: %s", exc)
            return None
