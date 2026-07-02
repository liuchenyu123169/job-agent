"""ComparisonTransformer — 跨搜索结果维度对齐 + 可选 LLM 结论。

规则提取（raw_evidence）：
  1. 从 outputs 中识别比较对象（subjects）
  2. 在每个对象的文本中搜索常见维度关键词 → 对齐为统一维度列表
  3. 每维度每对象填充提取到的值

LLM 增强（derived_conclusion）：
  可选 fast 模型基于维度表生成对比结论和推荐。
  失败时 degraded=True，维度表仍然有效。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.application.transformers.base import (
    BaseTransformer,
    DerivedConclusion,
    DimensionRow,
    RawEvidence,
    StructuredEvidence,
)

logger = logging.getLogger(__name__)

# 常见对比维度关键词（中文）
_COMMON_DIMENSIONS = [
    ("技术栈", ["技术栈", "语言", "框架", "技术", "Go", "Java", "Python", "C\\+\\+", "Rust"]),
    ("薪资", ["薪资", "工资", "薪酬", "月薪", "年薪", "K", "万"]),
    ("地点", ["地点", "城市", "北京", "上海", "深圳", "杭州", "广州", "成都"]),
    ("要求", ["要求", "经验", "年限", "学历", "本科", "硕士"]),
    ("发展", ["发展", "成长", "晋升", "前景", "空间"]),
    ("文化", ["文化", "氛围", "环境", "福利", "加班"]),
    ("规模", ["规模", "人数", "团队"]),
]


class ComparisonTransformer(BaseTransformer):
    """对比分析证据提取器。

    提取流程：
      1. 规则识别 subjects + 对齐 dimensions
      2. 可选 LLM 生成结论
    """

    task_type = "comparison"

    async def extract(
        self,
        goal: str,
        outputs: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> StructuredEvidence:
        warnings: list[str] = []
        raw = RawEvidence()

        if len(outputs) < 2:
            warnings.append("对比分析需要至少两个数据源，当前不足")
            return StructuredEvidence(
                task_type=self.task_type, raw=raw,
                warnings=warnings, degraded=True,
            )

        # ── Step 1: 识别比较对象 (subjects) ──
        raw.subjects = self._extract_subjects(outputs, goal)
        if len(raw.subjects) < 2:
            warnings.append(f"仅识别到 {len(raw.subjects)} 个比较对象，不足 2 个")
            return StructuredEvidence(
                task_type=self.task_type, raw=raw,
                warnings=warnings, degraded=True,
            )

        logger.info(
            "[ComparisonTransformer] subjects=%s, outputs=%d",
            raw.subjects, len(outputs),
        )

        # ── Step 2: 对齐维度 ──
        raw.dimensions = self._align_dimensions(outputs, raw.subjects)
        if len(raw.dimensions) < 2:
            warnings.append(f"仅对齐到 {len(raw.dimensions)} 个维度，不足以为对比提供结构")
            # dimensions 不足 → 仍然给出，但标记 degraded
            evidence = StructuredEvidence(
                task_type=self.task_type, raw=raw,
                warnings=warnings, degraded=True,
            )
            evidence.log_summary()
            return evidence

        logger.info(
            "[ComparisonTransformer] aligned %d dimensions across %d subjects",
            len(raw.dimensions), len(raw.subjects),
        )

        # ── Step 3: 可选 LLM 结论 ──
        derived = await self._try_generate_conclusion(goal, raw, warnings)

        # degraded 只反映 raw_evidence 是否为空
        evidence = StructuredEvidence(
            task_type=self.task_type,
            raw=raw,
            derived=derived,
            warnings=warnings,
            degraded=raw.is_empty() or len(raw.dimensions) < 2,
        )
        evidence.log_summary()
        return evidence

    # ── 内部方法 ──

    @staticmethod
    def _extract_subjects(outputs: list[dict], goal: str) -> list[str]:
        """从 outputs 和 goal 中提取比较对象名称。"""
        subjects: list[str] = []
        for out in outputs:
            # 优先从 meta/content 中的原始 query 提取（step 级记录）
            meta = out.get("meta", {})
            query = meta.get("query", "") or out.get("content", {}).get("query", "")
            if query:
                subjects.append(query[:40])
                continue
            # 尝试从第一个 item 的 title 提取
            items = out.get("content", {}).get("items", [])
            if items and isinstance(items[0], dict):
                title = items[0].get("title", "")
                if title:
                    subjects.append(title[:40])
                    continue
            # 从 text 第一行提取
            text = out.get("text", "")
            first_line = text.strip().split("\n")[0][:40] if text else ""
            if first_line:
                subjects.append(first_line)
        # 去重保序
        seen = set()
        unique = []
        for s in subjects:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        return unique[:4]  # 最多 4 个比较对象

    @staticmethod
    def _align_dimensions(
        outputs: list[dict], subjects: list[str],
    ) -> list[DimensionRow]:
        """跨 outputs 对齐对比维度 — 按句子/片段提取，避免字符窗口带入相邻维度。"""
        rows: list[DimensionRow] = []

        for dim_name, patterns in _COMMON_DIMENSIONS:
            values: dict[str, str] = {}
            for i, out in enumerate(outputs):
                subject = subjects[i] if i < len(subjects) else f"选项{i+1}"
                text = out.get("text", "")
                values[subject] = ComparisonTransformer._extract_dimension_value(
                    text, patterns,
                )

            # 至少有一个非占位值才保留此维度
            if any(v != "—" for v in values.values()):
                rows.append(DimensionRow(
                    dimension=dim_name,
                    values=values,
                    confidence=0.8 if all(v != "—" for v in values.values()) else 0.5,
                ))

        return rows

    @staticmethod
    def _extract_dimension_value(text: str, patterns: list[str]) -> str:
        """从文本中提取某个维度的值 — 按片段精确定位。

        策略：
          1. 按句子分隔符（。；\n）将文本拆为片段
          2. 在包含维度关键词的片段及紧随其后的 1-2 个片段中取摘要
          3. 如果没有匹配 → 返回 "—"
        """
        # 拆分为语义片段
        segments = re.split(r"[。；\n]+", text)
        segments = [s.strip() for s in segments if s.strip()]

        for pattern in patterns:
            for idx, seg in enumerate(segments):
                if re.search(pattern, seg):
                    # 取当前片段 + 后面紧邻的短片段（可能是续行），不超过 80 字符
                    value = seg
                    # 如果当前片段较短且后面有内容，拼接后续片段
                    j = idx + 1
                    while len(value) < 30 and j < len(segments) and j <= idx + 2:
                        next_seg = segments[j].strip()
                        if next_seg and not any(
                            re.search(p, next_seg) for p, _ in _COMMON_DIMENSIONS
                        ):
                            value += "；" + next_seg
                        j += 1
                    return value[:80]

        return "—"

    async def _try_generate_conclusion(
        self, goal: str, raw: RawEvidence, warnings: list[str],
    ) -> DerivedConclusion | None:
        """用 fast 模型基于维度表生成对比结论。"""
        import asyncio

        if not raw.dimensions:
            return None

        # 构建维度表文本
        table_lines = ["对比维度："]
        for row in raw.dimensions:
            vals = " | ".join(f"{subj}: {val}" for subj, val in row.values.items())
            table_lines.append(f"  {row.dimension}: {vals}")
        table_text = "\n".join(table_lines)

        prompt = (
            f"用户想对比：{goal}\n\n"
            f"已提取的对比维度：\n{table_text}\n\n"
            f"请基于上述维度，用 2-3 句话给出对比结论和推荐。"
            f"不要编造未在维度中出现的信息。输出纯文本。"
        )

        try:
            from app.ai.llm import invoke_llm
            conclusion: str = await asyncio.to_thread(
                invoke_llm, prompt, model_key="fast",
            )
            conclusion = conclusion.strip()
            if not conclusion or len(conclusion) < 10:
                warnings.append("LLM 结论过短，跳过")
                return None

            logger.info("[ComparisonTransformer] LLM conclusion (%d chars)", len(conclusion))
            return DerivedConclusion(
                summary=conclusion,
                recommendation=conclusion,
                confidence=0.75,
                used_llm=True,
                based_on=["raw.subjects", "raw.dimensions"],
            )
        except Exception as exc:
            warnings.append(f"LLM 结论生成失败（{exc}），降级")
            logger.warning("[ComparisonTransformer] LLM conclusion failed: %s", exc)
            return None
