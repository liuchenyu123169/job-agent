"""FactLookupTransformer — 从搜索结果提取关键事实。

规则提取（raw_evidence）：从 items 去重提取 facts + sources
LLM 增强（derived_conclusion）：用 fast 模型生成自然语言摘要（可选）
降级：fast LLM 不可用时 degraded=True，调用方回退 render_from_outputs
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.transformers.base import (
    BaseTransformer,
    DerivedConclusion,
    FactItem,
    RawEvidence,
    SourceRef,
    StructuredEvidence,
)

logger = logging.getLogger(__name__)


class FactLookupTransformer(BaseTransformer):
    """事实查询证据提取器。

    提取流程：
      1. 规则：从 outputs 的 items 中抽取 title/snippet/url → facts + sources
      2. 可选 LLM：如果 facts 非空 → fast 模型生成 3-5 句自然语言摘要
      3. 降级：LLM 不可用 → degraded=True，facts/sources 仍然有效
    """

    task_type = "fact_lookup"

    async def extract(
        self,
        goal: str,
        outputs: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> StructuredEvidence:
        warnings: list[str] = []
        raw = RawEvidence()

        # ── Step 1: 规则提取 facts + sources ──
        seen_urls: set[str] = set()
        for out in outputs:
            items = out.get("content", {}).get("items", [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", "")).strip()
                url = str(item.get("url", "")).strip()
                snippet = str(item.get("snippet", "")).strip()

                if not title:
                    continue

                # URL 去重
                norm_url = url.lower().rstrip("/") if url else ""
                if norm_url and norm_url in seen_urls:
                    continue
                if norm_url:
                    seen_urls.add(norm_url)

                si = len(raw.sources)
                raw.sources.append(SourceRef(
                    title=title[:200],
                    url=url,
                    snippet=snippet[:300],
                    relevance=1.0,
                ))

                # 每条 source 生成一条 fact
                if snippet:
                    raw.facts.append(FactItem(
                        fact=snippet[:200],
                        source_index=si,
                        confidence=1.0,  # 规则提取 = 直接引用原文
                    ))

        if not raw.facts:
            warnings.append("未从搜索结果中提取到任何事实")
            return StructuredEvidence(
                task_type=self.task_type,
                raw=raw,
                warnings=warnings,
                degraded=True,
            )

        logger.info(
            "[FactLookupTransformer] extracted %d facts from %d sources",
            len(raw.facts), len(raw.sources),
        )

        # ── Step 2: 可选 LLM 摘要 ──
        derived = await self._try_generate_summary(goal, raw, warnings)

        # degraded 只反映 raw_evidence 是否为空（规则提取失败）
        # derived=None（LLM 不可用）不触发 degraded
        evidence = StructuredEvidence(
            task_type=self.task_type,
            raw=raw,
            derived=derived,
            warnings=warnings,
            degraded=raw.is_empty(),
        )
        evidence.log_summary()
        return evidence

    async def _try_generate_summary(
        self, goal: str, raw: RawEvidence, warnings: list[str],
    ) -> DerivedConclusion | None:
        """尝试用 fast 模型生成自然语言摘要。失败时返回 None。"""
        import asyncio

        # 构建事实文本
        facts_text = "\n".join(
            f"{i+1}. [{raw.sources[f.source_index].title if f.source_index >= 0 else '?'}] "
            f"{f.fact}"
            for i, f in enumerate(raw.facts[:5])
        )
        prompt = (
            f"用户问题：{goal}\n\n"
            f"以下是从搜索结果中提取的事实：\n{facts_text}\n\n"
            f"请用 3-5 句话直接回答用户问题。不要编造新信息，只基于上述事实。\n"
            f"输出纯文本，不要使用 Markdown。"
        )

        try:
            from app.ai.llm import invoke_llm
            summary: str = await asyncio.to_thread(
                invoke_llm, prompt, model_key="fast"
            )
            summary = summary.strip()
            if not summary or len(summary) < 10:
                warnings.append("LLM 摘要生成结果过短，跳过")
                return None

            logger.info("[FactLookupTransformer] LLM summary generated (%d chars)", len(summary))
            return DerivedConclusion(
                summary=summary,
                confidence=0.8,
                used_llm=True,
                based_on=["raw.facts", "raw.sources"],
            )
        except Exception as exc:
            warnings.append(f"LLM 摘要生成失败（{exc}），降级到纯规则模式")
            logger.warning("[FactLookupTransformer] LLM summary failed: %s", exc)
            return None
