"""答案模板系统 — 按任务类型生成结构化最终回答。

职责边界：
  - 只负责：按任务类型渲染答案 + 模板级质量门
  - 不负责：选模板（report_formatter 负责）、结构验收（TaskCompletionVerifier 负责）

设计约束：
  - 所有模板继承 AnswerTemplate，实现 render / quality_gate / supports / fallback_reason
  - render() 在原料不足时必须返回 fallback_reason() 生成的结构化失败说明，不能退化成原始链接堆砌
  - quality_gate() 继承 Phase 1 的质量门（verifier_score < 50 拒止等）
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# GateResult — 质量门检查结果
# ═══════════════════════════════════════════════════════════════

@dataclass
class GateResult:
    """模板级质量门检查结果。"""
    passed: bool
    reason: str = ""                        # 通过/不通过的原因
    fallback_message: str = ""              # 不通过时给用户的降级说明
    blocked_items: list[str] = field(default_factory=list)  # 导致不通过的具体项


# ═══════════════════════════════════════════════════════════════
# AnswerTemplate 抽象基类
# ═══════════════════════════════════════════════════════════════

class AnswerTemplate(ABC):
    """答案模板基类。

    Phase 3 分层接口：
      - render() → 调度器：有 evidence 走新路径，否则走旧路径
      - render_from_evidence(goal, evidence, context) → Phase 3 新路径
      - render_from_outputs(goal, outputs, context) → Phase 2 兜底路径

    生命周期：
      1. report_formatter 调 quality_gate() → 不通过则返回 fallback_reason()
      2. quality_gate 通过 → 调 render() → 内部路由到 render_from_evidence 或 render_from_outputs
      3. TaskCompletionVerifier 对输出做结构验收
    """

    # 子类必须覆盖
    task_type: str = ""
    # 子类可选覆盖：此模板支持的 task_type 列表（支持多对一映射）
    supported_types: tuple[str, ...] = ()

    # ── 公开接口 ──

    def render(
        self,
        goal: str,
        outputs: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> str:
        """渲染最终答案 — 调度器。

        Phase 3: raw_evidence 非空时走新路径（即使 LLM 增强不可用），
        raw_evidence 为空时回退到 outputs 路径。
        """
        ctx = context or {}
        evidence = ctx.get("evidence")
        if evidence is not None:
            raw = getattr(evidence, "raw", None)
            if raw is not None and not raw.is_empty():
                # 有规则证据 → 走新路径（LLM 摘要可选）
                return self.render_from_evidence(goal, evidence, ctx)
        # 兜底路径：无证据或证据为空
        return self.render_from_outputs(goal, outputs, ctx)

    def render_from_evidence(
        self,
        goal: str,
        evidence: Any,  # StructuredEvidence
        context: dict[str, Any] | None = None,
    ) -> str:
        """Phase 3 新路径：使用结构化证据渲染。子类覆盖。"""
        ctx = context or {}
        return self.render_from_outputs(goal, [], ctx)

    @abstractmethod
    def render_from_outputs(
        self,
        goal: str,
        outputs: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> str:
        """Phase 2 兜底路径：从原始 outputs 渲染。子类必须实现。

        Args:
            goal: 用户原始目标
            outputs: 标准化工具输出列表（normalize_tool_output 产物）
            context: 额外上下文

        Returns:
            格式化的 Markdown 答案字符串。原料不足时不得返回原始链接堆砌，
            应调用 self.fallback_reason() 生成结构化失败说明。
        """
        ...

    @abstractmethod
    def quality_gate(
        self,
        outputs: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> GateResult:
        """模板级质量门 — 在 render() 之前调用。

        检查项（继承自 Phase 1）：
          - 原料是否存在且非空
          - verifier_score 是否 ≥ 50（如果 applicable）
          - outputs 中是否至少有一条包含实质性内容

        不通过时，report_formatter 应使用 fallback_reason() 而非 render()。
        """
        ...

    @classmethod
    def supports(cls, task_type: str) -> bool:
        """判断此模板是否支持给定 task_type。"""
        if cls.task_type == task_type:
            return True
        if task_type in cls.supported_types:
            return True
        return False

    def fallback_reason(
        self,
        outputs: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> str:
        """生成结构化失败说明 — 当 quality_gate 不通过或原料不足时使用。

        格式是固定的 Markdown 结构，不是原始输出的拼接。
        子类可覆盖以提供更具体的降级消息。
        """
        goal = (context or {}).get("goal", "用户目标")
        task_type_label = _TASK_TYPE_LABELS.get(self.task_type, self.task_type)
        return (
            f"# {goal}\n\n"
            f"## {task_type_label}\n\n"
            f"未能生成完整的{task_type_label}报告。\n\n"
            f"**原因**：当前步骤的产出物不足以构成结构化答案。\n\n"
            f"**建议**：\n"
            f"- 尝试提供更具体的信息（如指定公司名、岗位名、技术方向）\n"
            f"- 重新描述需求，让系统能更准确地理解您的意图\n"
        )


# ═══════════════════════════════════════════════════════════════
# 公共辅助
# ═══════════════════════════════════════════════════════════════

_TASK_TYPE_LABELS: dict[str, str] = {
    "fact_lookup": "信息查询",
    "comparison": "对比分析",
    "planning": "行动计划",
    "analysis": "深度分析",
    "recommendation": "推荐结果",
    "rewrite": "文本改写",
    "extraction": "内容抽取",
    "decision_support": "综合备战报告",
}


def _check_phase1_quality_gate(outputs: list[dict[str, Any]]) -> GateResult:
    """Phase 1 质量门：检查 verifier_score < 50 的输出。

    此函数被各模板的 quality_gate() 调用，确保 Phase 1 规则不被绕过。
    """
    blocked: list[str] = []
    for out in outputs:
        vs = out.get("meta", {}).get("verifier_score")
        if vs is not None and vs < 50:
            artifact = out.get("artifact_type", "unknown")
            blocked.append(f"{artifact}（验证分数 {vs:.0f}）")
    if blocked:
        return GateResult(
            passed=False,
            reason=f"以下产出物未通过 Phase 1 质量验收：{'; '.join(blocked)}",
            fallback_message="",
            blocked_items=blocked,
        )
    return GateResult(passed=True, reason="Phase 1 质量门通过")


def _has_substantive_content(outputs: list[dict[str, Any]], min_chars: int = 80) -> bool:
    """检查 outputs 中是否有实质性文本内容（非纯链接、非空壳）。"""
    total_text = ""
    for out in outputs:
        total_text += out.get("text", "") + " "
    # 去掉 Markdown 链接和格式符后的纯文本长度
    import re
    clean = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", total_text)  # 链接 → 只保留文字
    clean = re.sub(r"[#*>`\-|]", "", clean).strip()
    return len(clean) >= min_chars


def _extract_all_text(outputs: list[dict[str, Any]]) -> str:
    """从 outputs 中提取所有文本字段拼接。"""
    parts = []
    for out in outputs:
        text = out.get("text", "")
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _extract_items(outputs: list[dict[str, Any]]) -> list[dict]:
    """从 outputs 中提取所有 items 列表。"""
    all_items: list[dict] = []
    for out in outputs:
        items = out.get("content", {}).get("items", [])
        if isinstance(items, list):
            all_items.extend(items)
    return all_items


# ═══════════════════════════════════════════════════════════════
# 高频模板 1: FactLookupTemplate
# ═══════════════════════════════════════════════════════════════

class FactLookupTemplate(AnswerTemplate):
    """事实查询 — 一句话结论 + 关键信息 + 来源引用。

    期望输出结构（来自 EXPECTED_OUTPUT_SHAPES）：
      自然语言摘要（3-5句）直接回答用户问题 + 关键信息列表（≥2条）+ 来源引用
    """

    task_type = "fact_lookup"

    def quality_gate(self, outputs, context=None):
        # Phase 1 质量门
        phase1 = _check_phase1_quality_gate(outputs)
        if not phase1.passed:
            return phase1

        # 必须有实质性内容
        if not _has_substantive_content(outputs, min_chars=60):
            items = _extract_items(outputs)
            if not items:
                return GateResult(
                    passed=False,
                    reason="搜索结果为空，无法生成信息摘要",
                    fallback_message=self.fallback_reason(outputs, context),
                )

        return GateResult(passed=True, reason="原料充足")

    def render_from_evidence(self, goal, evidence, context=None):
        """Phase 3 新路径：从 StructuredEvidence 渲染答案。"""
        lines = [f"# {goal}", ""]

        if evidence.derived and evidence.derived.summary:
            lines.append(evidence.derived.summary)
            lines.append("")

        lines.append("## 关键信息")
        for i, fact in enumerate(evidence.raw.facts[:6]):
            si = fact.source_index
            src = ""
            if si >= 0 and si < len(evidence.raw.sources):
                src = f"（{evidence.raw.sources[si].title}）"
            lines.append(f"- {fact.fact} {src}")
        if not evidence.raw.facts:
            lines.append("（暂无详细信息）")
        lines.append("")

        if evidence.raw.sources:
            lines.append("## 来源")
            seen = set()
            for s in evidence.raw.sources[:5]:
                if s.url and s.url not in seen:
                    seen.add(s.url)
                    lines.append(f"- [{s.title}]({s.url})")
            lines.append("")

        return "\n".join(lines)

    def render_from_outputs(self, goal, outputs, context=None):
        # 先跑质量门
        gate = self.quality_gate(outputs, context)
        if not gate.passed:
            return gate.fallback_message or self.fallback_reason(outputs, context)

        full_text = _extract_all_text(outputs)
        items = _extract_items(outputs)

        lines = [f"# {goal}", ""]

        first_sentence = full_text.strip().split("\n")[0][:200] if full_text else ""
        lines.append(first_sentence if first_sentence else "未能提取到核心信息。")
        lines.append("")

        lines.append("## 关键信息")
        if items:
            for item in items[:6]:
                title = item.get("title", "")
                snippet = item.get("snippet", "")
                if snippet:
                    lines.append(f"- **{title}**：{snippet[:150]}")
                elif title:
                    lines.append(f"- {title}")
        elif full_text:
            for line in full_text.split("\n")[:8]:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    lines.append(f"- {stripped[:150]}")
        else:
            lines.append("（暂无详细信息）")
        lines.append("")

        if items:
            lines.append("## 来源")
            seen = set()
            for item in items[:5]:
                url = item.get("url", "")
                title = item.get("title", "来源链接")
                if url and url not in seen:
                    seen.add(url)
                    lines.append(f"- [{title}]({url})")
            lines.append("")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 高频模板 2: ComparisonTemplate
# ═══════════════════════════════════════════════════════════════

class ComparisonTemplate(AnswerTemplate):
    """对比分析 — 结论 + 多维对比表 + 每对象分析 + 最终建议。

    期望输出结构：
      对比结论（一句话推荐）+ 多维对比表（≥3维度）+ 每选项详细分析 + 最终建议
    """

    task_type = "comparison"

    def quality_gate(self, outputs, context=None):
        phase1 = _check_phase1_quality_gate(outputs)
        if not phase1.passed:
            return phase1

        # comparison 至少需要 2 个对象的输出
        if len(outputs) < 2 and not _has_substantive_content(outputs, min_chars=120):
            return GateResult(
                passed=False,
                reason="对比分析需要至少两个比较对象的素材，当前产出物不足以支撑对比",
                fallback_message=self.fallback_reason(outputs, context),
            )

        return GateResult(passed=True, reason="原料充足")

    def render_from_evidence(self, goal, evidence, context=None):
        """Phase 3 新路径：从 ComparisonEvidence 渲染结构化对比报告。"""
        lines = [f"# {goal}", ""]

        # ── LLM 结论 ──
        if evidence.derived and evidence.derived.recommendation:
            lines.append("## 对比结论")
            lines.append(evidence.derived.recommendation)
            lines.append("")

        # ── 对比维度表 ──
        if evidence.raw.dimensions:
            lines.append("## 对比维度")
            lines.append("")
            subjects = evidence.raw.subjects or [f"选项{i+1}" for i in range(2)]
            header = "| 维度 | " + " | ".join(subjects) + " |"
            lines.append(header)
            lines.append("|------|" + "|".join(["------" for _ in subjects]) + "|")
            for row in evidence.raw.dimensions:
                vals = [row.values.get(s, "—") for s in subjects]
                lines.append(f"| {row.dimension} | " + " | ".join(vals) + " |")
            lines.append("")

        # ── 详细分析 ──
        if evidence.raw.subjects:
            lines.append("## 详细分析")
            for i, subject in enumerate(evidence.raw.subjects):
                lines.append(f"### {subject}")
                # 汇总该对象在各维度的值
                for row in evidence.raw.dimensions:
                    val = row.values.get(subject, "")
                    if val and val != "—":
                        lines.append(f"- **{row.dimension}**：{val}")
                lines.append("")

        # ── 建议 ──
        lines.append("## 建议")
        if evidence.derived and evidence.derived.recommendation:
            lines.append("基于以上对比，结合自身优先级做出最终选择。")
        else:
            lines.append("基于以上对比维度，请结合自身优先级做出最终选择。")

        return "\n".join(lines)

    def render_from_outputs(self, goal, outputs, context=None):
        gate = self.quality_gate(outputs, context)
        if not gate.passed:
            return gate.fallback_message or self.fallback_reason(outputs, context)

        full_text = _extract_all_text(outputs)
        lines = [f"# {goal}", ""]

        lines.append("## 对比结论")
        conclusion = ""
        for line in full_text.split("\n"):
            stripped = line.strip()
            if any(kw in stripped for kw in ("推荐", "建议选择", "更优", "更适合", "结论")):
                conclusion = stripped[:200]
                break
        lines.append(conclusion if conclusion else full_text[:200].strip())
        lines.append("")

        # ── 2. 对比维度表 ──
        lines.append("## 对比维度")
        table = self._build_comparison_table(outputs, full_text)
        if table:
            lines.extend(table)
        else:
            lines.append("（无法从当前素材中自动提取对比维度，请参见下方详细分析）")
        lines.append("")

        # ── 3. 详细分析（按 output 分块）──
        lines.append("## 详细分析")
        for i, out in enumerate(outputs, 1):
            text = out.get("text", "")
            if text:
                label = self._extract_option_label(out, i)
                preview = text.strip()[:300]
                if len(text) > 300:
                    preview += "..."
                lines.append(f"### {label}")
                lines.append(preview)
                lines.append("")

        # ── 4. 建议 ──
        lines.append("## 建议")
        lines.append(
            "基于以上对比，请结合自身优先级（技术栈匹配度、发展空间、薪资水平、文化契合度）"
            "做出最终选择。如需更深入的单项分析，可单独查询。"
        )

        return "\n".join(lines)

    @staticmethod
    def _build_comparison_table(
        outputs: list[dict], full_text: str,
    ) -> list[str] | None:
        """从 outputs 和 text 中提取维度并构建 Markdown 对比表。

        返回 None 表示无法提取足够维度。
        """
        # 尝试从 output meta 或 text 中提取维度
        dimensions: list[tuple[str, list[str]]] = []
        common_dims = ["技术栈", "薪资", "发展", "文化", "要求", "难度", "规模", "地点", "福利"]

        # 方案 A: 从 outputs 的 meta 中提取
        for dim in common_dims:
            values: list[str] = []
            for out in outputs:
                text = out.get("text", "")
                meta = out.get("meta", {})
                # 从 text 中搜索维度关键词所在行
                for line in text.split("\n"):
                    if dim in line:
                        values.append(line.strip()[:80])
                        break
                else:
                    values.append("—")
            # 至少有一个非占位值才加入
            if any(v != "—" for v in values):
                dimensions.append((dim, values))

        if len(dimensions) < 2:
            # 方案 B: 从 full_text 分块提取
            return None

        # 构建表格
        table_lines = [""]
        header = "| 维度 | " + " | ".join(
            ComparisonTemplate._extract_option_label(out, i + 1)
            for i, out in enumerate(outputs)
        ) + " |"
        table_lines.append(header)
        table_lines.append("|------|" + "|".join(["------" for _ in outputs]) + "|")
        for dim, values in dimensions:
            row = f"| {dim} | " + " | ".join(values) + " |"
            table_lines.append(row)

        return table_lines

    @staticmethod
    def _extract_option_label(out: dict, index: int) -> str:
        """从 output 中提取比较对象的标签名。"""
        # 尝试从 content 的 query 或 title 提取
        content = out.get("content", {})
        query = content.get("query", "")
        items = content.get("items", [])
        if items and isinstance(items[0], dict):
            title = items[0].get("title", "")
            if title:
                return title[:30]
        if query:
            return query[:30]
        return f"选项 {index}"


# ═══════════════════════════════════════════════════════════════
# 高频模板 3: PlanningTemplate
# ═══════════════════════════════════════════════════════════════

class PlanningTemplate(AnswerTemplate):
    """行动计划 — 分阶段时间线 + 每阶段任务 + 里程碑。

    期望输出结构：
      计划名称 + 目标概述 + 分阶段时间线（≥2阶段）+ 每阶段任务（≥3条）+ 里程碑 + 时间节点
    """

    task_type = "planning"

    def quality_gate(self, outputs, context=None):
        # Phase 1 质量门（与所有模板一致）
        phase1 = _check_phase1_quality_gate(outputs)
        if not phase1.passed:
            return phase1

        # planning 模板对原料要求最低 — _finalizer 直接生成文本即可
        if not _has_substantive_content(outputs, min_chars=40):
            return GateResult(
                passed=False,
                reason="未能生成计划内容，请重新描述目标",
                fallback_message=self.fallback_reason(outputs, context),
            )
        return GateResult(passed=True, reason="有可用计划内容")

    def render_from_outputs(self, goal, outputs, context=None):
        gate = self.quality_gate(outputs, context)
        if not gate.passed:
            return gate.fallback_message or self.fallback_reason(outputs, context)

        full_text = _extract_all_text(outputs)
        lines = [f"# {goal}", ""]

        # planning 的输出通常由 _finalizer 直接生成，保持其结构
        # 只做格式化修正：确保有阶段标记
        has_phases = any(
            marker in full_text
            for marker in ("阶段", "阶段一", "第一阶段", "第1", "Day ", "Week ", "第 1", "## ")
        )

        if has_phases:
            lines.append(full_text)
        else:
            # 尝试重新组织
            lines.append("## 目标")
            lines.append(full_text[:200].strip() if full_text else "待补充")
            lines.append("")
            lines.append("## 执行计划")
            lines.append(full_text)
            lines.append("")
            lines.append("> 提示：您可以通过更具体地描述目标和时间限制来获得更详细的计划。")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 高频模板 4: AnalysisTemplate
# ═══════════════════════════════════════════════════════════════

class AnalysisTemplate(AnswerTemplate):
    """深度分析 — 综合评分 + 维度拆解 + 差距描述 + 改进建议。

    期望输出结构：
      综合评分/等级 + 维度拆解分析（≥3维度）+ 具体差距描述 + 可执行改进建议（≥3条）
    """

    task_type = "analysis"

    def quality_gate(self, outputs, context=None):
        phase1 = _check_phase1_quality_gate(outputs)
        if not phase1.passed:
            return phase1

        if not _has_substantive_content(outputs, min_chars=80):
            return GateResult(
                passed=False,
                reason="分析素材不足，无法生成有深度的分析报告",
                fallback_message=self.fallback_reason(outputs, context),
            )
        return GateResult(passed=True, reason="分析素材充足")

    def render_from_evidence(self, goal, evidence, context=None):
        """Phase 3 新路径：从 AnalysisEvidence 渲染结构化分析报告。"""
        lines = [f"# {goal}", ""]

        if evidence.raw.scores:
            main = evidence.raw.scores[0]
            level = "优秀" if main.score >= 85 else ("良好" if main.score >= 70 else ("一般" if main.score >= 50 else "需提升"))
            lines.append(f"**综合评分: {main.score:.0f} 分（{level}）**")
            lines.append("")

        if evidence.derived and evidence.derived.summary:
            lines.append(evidence.derived.summary)
            lines.append("")

        if evidence.raw.scores:
            lines.append("## 维度分析")
            for dim in evidence.raw.scores:
                lines.append(f"- **{dim.name}**: {dim.score:.0f} 分 — {dim.gap_description or dim.evidence[:80]}")
            lines.append("")

        if evidence.raw.gaps:
            lines.append("## 主要差距")
            for gap in evidence.raw.gaps[:5]:
                lines.append(f"- {gap}")
            lines.append("")

        if evidence.raw.suggestions:
            lines.append("## 改进建议")
            for sug in evidence.raw.suggestions[:5]:
                lines.append(f"- {sug}")
            lines.append("")

        return "\n".join(lines)

    def render_from_outputs(self, goal, outputs, context=None):
        gate = self.quality_gate(outputs, context)
        if not gate.passed:
            return gate.fallback_message or self.fallback_reason(outputs, context)

        full_text = _extract_all_text(outputs)
        lines = [f"# {goal}", ""]

        # ── 综合评分 ──
        score = None
        for out in outputs:
            s = out.get("meta", {}).get("match_score")
            if s is not None:
                score = s
                break
        if score is not None:
            level = "优秀" if score >= 85 else ("良好" if score >= 70 else ("一般" if score >= 50 else "需提升"))
            lines.append(f"**综合评分: {score} 分（{level}）**")
            lines.append("")

        # ── 维度拆解 ──
        lines.append("## 维度分析")
        sections = _split_markdown_sections(full_text)
        key_sections = [
            (t, b) for t, b in sections
            if any(kw in (t + b) for kw in ("优势", "差距", "不足", "匹配", "建议", "改进", "维度"))
        ]
        if key_sections:
            for title, body in key_sections[:6]:
                if title:
                    lines.append(f"### {title}")
                lines.append(body.strip()[:300])
                lines.append("")
        else:
            lines.append(full_text[:600] if full_text else "暂无详细分析")

        # ── 改进建议 ──
        lines.append("## 改进建议")
        suggestion_lines = [
            ln.strip("- *") for ln in full_text.split("\n")
            if any(kw in ln for kw in ("建议", "改进", "提升", "优化", "加强", "补充"))
        ]
        if suggestion_lines:
            for sl in suggestion_lines[:5]:
                lines.append(f"- {sl[:150]}")
        else:
            lines.append("请基于维度分析中的差距点，制定针对性的提升计划。")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 兜底: GenericTemplate
# ═══════════════════════════════════════════════════════════════

class GenericTemplate(AnswerTemplate):
    """通用兜底模板 — 用于 recommendation / rewrite / extraction / decision_support。

    不做复杂结构化，但必须经过 Phase 1 质量门。
    失败时不退化为原始链接堆砌，返回 fallback_reason()。
    """

    task_type = "__generic__"
    supported_types = (
        "recommendation", "rewrite", "extraction", "decision_support",
    )

    def quality_gate(self, outputs, context=None):
        phase1 = _check_phase1_quality_gate(outputs)
        if not phase1.passed:
            return phase1

        if not _has_substantive_content(outputs, min_chars=40) and not _extract_items(outputs):
            return GateResult(
                passed=False,
                reason="无可用产出物",
                fallback_message=self.fallback_reason(outputs, context),
            )
        return GateResult(passed=True, reason="有可用产出物（通用模板）")

    def render_from_outputs(self, goal, outputs, context=None):
        gate = self.quality_gate(outputs, context)
        if not gate.passed:
            return gate.fallback_message or self.fallback_reason(outputs, context)

        ct = context or {}
        task_type = ct.get("task_type", "")
        task_label = _TASK_TYPE_LABELS.get(task_type, "结果")
        full_text = _extract_all_text(outputs)
        items = _extract_items(outputs)

        lines = [f"# {goal}", "", f"## {task_label}", ""]

        if full_text:
            lines.append(full_text[:800])
        elif items:
            for item in items[:5]:
                title = item.get("title", "")
                snippet = item.get("snippet", "")
                if title:
                    lines.append(f"- **{title}**")
                    if snippet:
                        lines.append(f"  {snippet[:200]}")
        else:
            lines.append(self.fallback_reason(outputs, context))

        return "\n".join(lines)

    def fallback_reason(self, outputs, context=None):
        ct = context or {}
        goal = ct.get("goal", "用户目标")
        task_type = ct.get("task_type", "")
        task_label = _TASK_TYPE_LABELS.get(task_type, "任务")
        return (
            f"# {goal}\n\n"
            f"## {task_label}\n\n"
            f"当前步骤的产出物不足以构成完整的{task_label}报告。\n\n"
            f"**建议**：\n"
            f"- 尝试更具体地描述需求\n"
            f"- 提供更多上下文信息（如公司名、岗位名、具体方向）\n"
        )


# ═══════════════════════════════════════════════════════════════
# 模板注册表
# ═══════════════════════════════════════════════════════════════

# 按优先级排列：高频专用模板在前，Generic 兜底在后
_TEMPLATES: list[AnswerTemplate] = [
    FactLookupTemplate(),
    ComparisonTemplate(),
    PlanningTemplate(),
    AnalysisTemplate(),
    GenericTemplate(),
]


def get_template(task_type: str) -> AnswerTemplate:
    """根据 task_type 返回对应的 AnswerTemplate。

    匹配顺序：专用模板 → GenericTemplate（通过 supported_types）→ GenericTemplate（兜底）
    """
    for tmpl in _TEMPLATES:
        if tmpl.supports(task_type):
            logger.debug("[AnswerTemplates] matched %s → %s", task_type, type(tmpl).__name__)
            return tmpl
    # 最终兜底
    logger.warning("[AnswerTemplates] no template for task_type=%s, using GenericTemplate", task_type)
    return _TEMPLATES[-1]


# ── Markdown 辅助（与 report_formatter._split_markdown_sections 同逻辑，避免循环导入）──


def _split_markdown_sections(text: str) -> list[tuple[str, str]]:
    """将 Markdown 按 ## / ### 标题拆分为 (标题, 正文) 对。"""
    sections: list[tuple[str, str]] = []
    current_title = ""
    current_body: list[str] = []

    for line in text.split("\n"):
        if line.startswith("## "):
            if current_body or current_title:
                sections.append((current_title, "\n".join(current_body)))
            current_title = line.strip("# ").strip()
            current_body = []
        elif line.startswith("# "):
            if current_body or current_title:
                sections.append((current_title, "\n".join(current_body)))
            current_title = ""
            current_body = []
        else:
            current_body.append(line)

    if current_body or current_title:
        sections.append((current_title, "\n".join(current_body)))

    return sections
