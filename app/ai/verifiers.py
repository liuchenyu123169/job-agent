"""验收器 — 对编排器执行的每个步骤进行质量验证。

每个 Verifier 使用 fast 模型（低成本）做结构化判断，输出 VerificationResult。
打分的 Verifier（Match/Resume/Interview）调 LLM 生成评分和建议；
纯规则 Verifier（Recommend）不调 LLM，只检查基本结构。
"""

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.shared.state import PipelineContext
from app.shared.text_utils import min_relevance_signal
from app.ai.llm import invoke_llm
from app.ai.prompt_engine import PromptManager

logger = logging.getLogger(__name__)

_prompt_manager = PromptManager(version="v1")


@dataclass
class VerificationResult:
    """单次验收结果。"""
    passed: bool
    score: float          # 0.0–100.0
    detail: str           # 人类可读的验收说明
    suggested_fix: str | None = None  # 未通过时的改进建议
    step_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "passed": self.passed,
            "score": self.score,
            "detail": self.detail,
            "suggested_fix": self.suggested_fix,
        }


class BaseVerifier(ABC):
    """验收器基类 — 子类实现 _build_prompt 和 _parse_response。"""

    model_key: str = "fast"
    PASS_THRESHOLD: float = 60.0  # score >= 60 才算通过

    @property
    @abstractmethod
    def template_name(self) -> str:
        """Jinja2 模板文件名（不含 .j2 后缀）。"""
        ...

    @abstractmethod
    def _build_prompt(
        self, step_result: dict, criteria: list[str], context: PipelineContext
    ) -> str:
        """构建验收 prompt。"""
        ...

    @abstractmethod
    def _parse_response(self, response: str) -> VerificationResult:
        """解析 LLM 返回的 JSON。"""
        ...

    async def verify(
        self,
        step_id: str,
        step_result: dict[str, Any],
        criteria: list[str],
        context: PipelineContext | None = None,
    ) -> VerificationResult:
        """执行验收：构建 prompt → 调 LLM → 解析结果。

        Args:
            step_id: 被验收的步骤 ID
            step_result: 步骤输出（来自 tool.execute() 的 ToolResult.data）
            criteria: 当前 task 的验收标准列表
            context: PipelineContext（可选，用于注入更多上下文）

        Returns:
            VerificationResult，包含 passed/score/detail/suggested_fix
        """
        try:
            prompt = self._build_prompt(step_result, criteria, context or PipelineContext())

            response: str = await asyncio.to_thread(
                invoke_llm, prompt, model_key=self.model_key
            )

            vr = self._parse_response(response)
            vr.step_id = step_id
            return vr

        except Exception as exc:
            logger.error("[%s] verification failed for step=%s: %s", type(self).__name__, step_id, exc)
            return VerificationResult(
                passed=False,
                score=0.0,
                detail=f"验收过程出错: {exc}",
                suggested_fix="请人工检查步骤输出是否有效",
                step_id=step_id,
            )

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """从 LLM 输出中提取 JSON 对象。支持 ```json ... ``` 包裹。"""
        if not text:
            return None
        # 尝试直接解析
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        # 尝试提取 ```json ... ``` 代码块
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        # 尝试找到第一个 { 到最后一个 }
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return None


# ═══════════════════════════════════════════════════════════════
# MatchVerifier — 匹配分析结果验收
# ═══════════════════════════════════════════════════════════════

class MatchVerifier(BaseVerifier):
    """验收匹配分析输出 — 打分维度: 完整性 40% + 具体性 30% + 可操作性 30%"""

    template_name = "verify_match"

    def _build_prompt(self, step_result: dict, criteria: list[str], context: PipelineContext) -> str:
        result_json = json.dumps(step_result, ensure_ascii=False, indent=2)
        criteria_text = "\n".join(f"- {c}" for c in criteria) if criteria else "(无)"
        return _prompt_manager.render(
            self.template_name,
            step_result=result_json,
            criteria=criteria_text,
        )

    def _parse_response(self, response: str) -> VerificationResult:
        data = self._extract_json(response)
        if data is None:
            return VerificationResult(
                passed=False, score=0.0,
                detail="无法解析验证结果 — LLM 未返回有效 JSON",
                suggested_fix="请检查匹配分析输出是否完整",
            )
        score = max(0.0, min(100.0, float(data.get("score", 0))))
        llm_passed = bool(data.get("passed", False))
        passed = llm_passed and score >= self.PASS_THRESHOLD
        return VerificationResult(
            passed=passed,
            score=score,
            detail=str(data.get("detail", "")),
            suggested_fix=(data.get("suggested_fix") or "请人工检查步骤输出是否完整") if not passed else None,
        )

# ═══════════════════════════════════════════════════════════════
# ResumeVerifier — 简历优化/生成结果验收
# ═══════════════════════════════════════════════════════════════

class ResumeVerifier(BaseVerifier):
    """验收简历优化/生成输出 — 打分维度: 覆盖度 50% + 可执行性 50%"""

    template_name = "verify_resume"

    def _build_prompt(self, step_result: dict, criteria: list[str], context: PipelineContext) -> str:
        result_json = json.dumps(step_result, ensure_ascii=False, indent=2)
        criteria_text = "\n".join(f"- {c}" for c in criteria) if criteria else "(无)"
        return _prompt_manager.render(
            self.template_name,
            step_result=result_json,
            criteria=criteria_text,
        )

    def _parse_response(self, response: str) -> VerificationResult:
        data = self._extract_json(response)
        if data is None:
            return VerificationResult(
                passed=False, score=0.0,
                detail="无法解析验证结果 — LLM 未返回有效 JSON",
                suggested_fix="请检查简历优化输出是否完整",
            )
        score = max(0.0, min(100.0, float(data.get("score", 0))))
        llm_passed = bool(data.get("passed", False))
        passed = llm_passed and score >= self.PASS_THRESHOLD
        return VerificationResult(
            passed=passed,
            score=score,
            detail=str(data.get("detail", "")),
            suggested_fix=(data.get("suggested_fix") or "请人工检查步骤输出是否完整") if not passed else None,
        )


# ═══════════════════════════════════════════════════════════════
# InterviewVerifier — 面试题验收
# ═══════════════════════════════════════════════════════════════

class InterviewVerifier(BaseVerifier):
    """验收面试题输出 — 打分维度: 覆盖面 40% + 针对性 30% + 难度梯度 30%"""

    template_name = "verify_interview"

    def _build_prompt(self, step_result: dict, criteria: list[str], context: PipelineContext) -> str:
        result_json = json.dumps(step_result, ensure_ascii=False, indent=2)
        criteria_text = "\n".join(f"- {c}" for c in criteria) if criteria else "(无)"
        return _prompt_manager.render(
            self.template_name,
            step_result=result_json,
            criteria=criteria_text,
        )

    def _parse_response(self, response: str) -> VerificationResult:
        data = self._extract_json(response)
        if data is None:
            return VerificationResult(
                passed=False, score=0.0,
                detail="无法解析验证结果 — LLM 未返回有效 JSON",
                suggested_fix="请检查面试题输出是否完整",
            )
        score = max(0.0, min(100.0, float(data.get("score", 0))))
        llm_passed = bool(data.get("passed", False))
        passed = llm_passed and score >= self.PASS_THRESHOLD
        return VerificationResult(
            passed=passed,
            score=score,
            detail=str(data.get("detail", "")),
            suggested_fix=(data.get("suggested_fix") or "请人工检查步骤输出是否完整") if not passed else None,
        )


# ═══════════════════════════════════════════════════════════════
# RecommendVerifier — 岗位推荐验收（纯规则，不调 LLM）
# ═══════════════════════════════════════════════════════════════

class RecommendVerifier(BaseVerifier):
    """验收岗位推荐输出 — 纯规则打分，不调 LLM。

    检查项：
      - 推荐结果非空
      - 每项有 match_reason
      - 分数有区分度（标准差 > 0）
    """

    template_name = "verify_recommend"  # 不使用模板，但不实现会报错

    def _build_prompt(self, step_result: dict, criteria: list[str], context: PipelineContext) -> str:
        # 纯规则，不调 LLM，此方法不会被调用
        return ""

    def _parse_response(self, response: str) -> VerificationResult:
        # 不会被调用
        return VerificationResult(passed=False, score=0, detail="")

    async def verify(
        self,
        step_id: str,
        step_result: dict[str, Any],
        criteria: list[str],
        context: PipelineContext | None = None,
    ) -> VerificationResult:
        """纯规则验收 — 不调 LLM。"""
        try:
            items = step_result.get("items", [])
            if not isinstance(items, list) or len(items) == 0:
                return VerificationResult(
                    passed=False, score=0, detail="推荐结果为空",
                    suggested_fix="请确保至少推荐 1 个岗位", step_id=step_id,
                )

            # 检查每项的 match_reason
            has_reasons = all(
                isinstance(item, dict) and item.get("match_reason", "").strip()
                for item in items
            )
            if not has_reasons:
                return VerificationResult(
                    passed=False, score=30, detail="部分推荐缺少匹配理由",
                    suggested_fix="每个推荐岗位都应包含明确的 match_reason",
                    step_id=step_id,
                )

            # 检查分数区分度
            scores = [
                float(item.get("match_score", 0))
                for item in items
                if isinstance(item, dict)
            ]
            if len(scores) >= 2:
                mean_score = sum(scores) / len(scores)
                variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
                std_dev = variance ** 0.5
                if std_dev < 1.0:
                    return VerificationResult(
                        passed=False, score=50,
                        detail=f"推荐分数无区分度（标准差={std_dev:.1f}），所有岗位分数接近",
                        suggested_fix="建议增强评分区分度，体现岗位间的显著差异",
                        step_id=step_id,
                    )
                score = min(100.0, 60.0 + std_dev * 5)  # 区分度越大分越高
            else:
                score = 70.0  # 单条推荐，合理即过

            return VerificationResult(
                passed=True, score=score,
                detail=f"推荐验收通过: {len(items)} 个岗位, 均有匹配理由",
                step_id=step_id,
            )
        except Exception as exc:
            logger.error("[RecommendVerifier] error: %s", exc)
            return VerificationResult(
                passed=False, score=0, detail=f"验收出错: {exc}",
                suggested_fix="请人工检查", step_id=step_id,
            )


# ═══════════════════════════════════════════════════════════════
# InfoGatheringVerifier — 信息搜集结果验收（第二级 LLM）
# ═══════════════════════════════════════════════════════════════

class InfoGatheringVerifier(BaseVerifier):
    """验收信息搜集/搜索类结果 — 调 fast 模型做 3 个判断题。

    这是 Phase 1 唯一新增的 LLM verifier。只在 task_type=="info_gathering"
    且第一级 UtilityVerifier 通过后才触发，作为第二级质量把关。

    3 个判断题：
    1. does_answer_goal — 搜集到的信息是否实际回答了用户问题？
    2. has_concrete_info — 结果中是否有具体信息（技术名/数字/公司/时间等）？
    3. from_credible_source — 主要来源是否可信？

    评分: 3/3 = 90, 2/3 = 65, 1/3 = 35, 0/3 = 10
    passed: ≥2/3 (即 65 分)
    """

    template_name = "verify_infogathering"

    def _build_prompt(
        self, step_result: dict, criteria: list[str], context: PipelineContext
    ) -> str:
        result_json = json.dumps(step_result, ensure_ascii=False, indent=2)
        goal = context.goal if context else ""
        return _prompt_manager.render(
            self.template_name,
            goal=goal,
            step_result=result_json,
        )

    def _parse_response(self, response: str) -> VerificationResult:
        data = self._extract_json(response)
        if data is None:
            return VerificationResult(
                passed=False, score=0.0,
                detail="无法解析验证结果 — LLM 未返回有效 JSON",
                suggested_fix="请检查搜索输出是否完整",
            )

        yes_count = sum(
            1 for key in ("does_answer_goal", "has_concrete_info", "from_credible_source")
            if data.get(key, False)
        )
        score_map = {3: 90.0, 2: 65.0, 1: 35.0, 0: 10.0}
        score = score_map.get(yes_count, 0.0)
        passed = yes_count >= 2

        return VerificationResult(
            passed=passed,
            score=score,
            detail=str(data.get("detail", "")),
            suggested_fix=(data.get("suggested_fix") or "搜索结果未能充分回应用户问题")
            if not passed else None,
        )


# ── Verifier 路由表 ──

_VERIFIER_MAP: dict[str, BaseVerifier] = {}

_match_v = MatchVerifier()
_resume_v = ResumeVerifier()
_interview_v = InterviewVerifier()
_recommend_v = RecommendVerifier()

# ═══════════════════════════════════════════════════════════════
# UtilityVerifier — 实用工具验收（纯规则，不调 LLM）
# ═══════════════════════════════════════════════════════════════

class UtilityVerifier(BaseVerifier):
    """验收实用工具输出 — 纯规则检查，不调 LLM。

    适用工具: search_knowledge, list_resumes, list_jobs, get_task
    检查项:
      - search_knowledge: items 非空、每项有文本内容
      - list_resumes / list_jobs: 有 resumes/jobs 字段且 count >= 0
      - get_task: 有 task 对象、包含 status 字段
    """

    template_name = "verify_utility"  # 不实际使用

    def __init__(self, tool_name: str):
        self._tool_name = tool_name

    def _build_prompt(self, step_result: dict, criteria: list[str], context: PipelineContext) -> str:
        return ""  # 纯规则，不调 LLM

    def _parse_response(self, response: str) -> VerificationResult:
        return VerificationResult(passed=False, score=0, detail="")

    async def verify(
        self,
        step_id: str,
        step_result: dict[str, Any],
        criteria: list[str],
        context: PipelineContext | None = None,
    ) -> VerificationResult:
        """纯规则验收 — 不调 LLM。"""
        try:
            if self._tool_name == "search_knowledge":
                items = step_result.get("items", [])
                if not isinstance(items, list) or len(items) == 0:
                    return VerificationResult(
                        passed=False, score=0, detail="搜索结果为空",
                        suggested_fix="请使用不同的关键词重新搜索", step_id=step_id,
                    )
                # 检查每项有文本内容
                has_content = all(
                    isinstance(item, dict) and item.get("content", "").strip()
                    for item in items
                )
                if not has_content:
                    return VerificationResult(
                        passed=False, score=40, detail="部分搜索结果缺少内容",
                        suggested_fix="知识库数据可能不完整", step_id=step_id,
                    )
                return VerificationResult(
                    passed=True, score=90, detail=f"搜索返回 {len(items)} 条结果",
                    step_id=step_id,
                )

            elif self._tool_name in ("list_resumes", "list_jobs"):
                field = "resumes" if self._tool_name == "list_resumes" else "jobs"
                items = step_result.get(field)
                count = step_result.get("count", -1)
                if not isinstance(items, list):
                    return VerificationResult(
                        passed=False, score=0, detail=f"缺少 {field} 字段或格式错误",
                        suggested_fix="请检查数据库连接", step_id=step_id,
                    )
                if count < 0:
                    return VerificationResult(
                        passed=False, score=30, detail="count 字段异常",
                        suggested_fix="请检查工具实现", step_id=step_id,
                    )
                return VerificationResult(
                    passed=True, score=95, detail=f"列出 {count} 条{field}",
                    step_id=step_id,
                )

            elif self._tool_name == "get_task":
                task = step_result.get("task")
                if not isinstance(task, dict):
                    return VerificationResult(
                        passed=False, score=0, detail="缺少 task 对象或格式错误",
                        suggested_fix="请检查任务 ID 是否正确", step_id=step_id,
                    )
                if "status" not in task:
                    return VerificationResult(
                        passed=False, score=30, detail="task 对象缺少 status 字段",
                        suggested_fix="请检查数据库记录完整性", step_id=step_id,
                    )
                return VerificationResult(
                    passed=True, score=90, detail=f"任务状态: {task.get('status')}",
                    step_id=step_id,
                )

            elif self._tool_name == "public_search":
                items = step_result.get("items", [])
                query = str(step_result.get("query", ""))
                if not isinstance(items, list) or len(items) == 0:
                    return VerificationResult(
                        passed=False, score=0, detail="公开搜索未返回结果",
                        suggested_fix="请使用不同的查询词重新搜索", step_id=step_id,
                    )

                # ── 1. 结构完整性 (权重 40%) ──
                structure_score = 100.0
                struct_issues: list[str] = []
                for i, item in enumerate(items):
                    if not isinstance(item, dict):
                        struct_issues.append(f"#{i+1} 格式错误")
                        structure_score -= 30
                        continue
                    if not item.get("title"):
                        struct_issues.append(f"#{i+1} 缺少标题")
                        structure_score -= 20
                    if not item.get("url"):
                        struct_issues.append(f"#{i+1} 缺少 URL")
                        structure_score -= 15
                structure_score = max(0.0, structure_score)
                if struct_issues and structure_score <= 0:
                    return VerificationResult(
                        passed=False, score=structure_score,
                        detail=f"搜索结果结构不全: {'; '.join(struct_issues)}",
                        suggested_fix="搜索源返回数据不完整", step_id=step_id,
                    )

                # ── 2. 相关性信号 (权重 35%) ──
                relevance_score = 100.0
                if query:
                    relevant_count = sum(
                        1 for item in items
                        if isinstance(item, dict)
                        and min_relevance_signal(
                            query,
                            str(item.get("title", "")),
                            str(item.get("snippet", "")),
                        )
                    )
                    relevant_ratio = relevant_count / len(items) if items else 0
                    relevance_score = relevant_ratio * 100.0
                    if relevant_ratio < 0.3:
                        relevance_score = max(0.0, relevant_ratio * 100.0)
                else:
                    relevance_score = 50.0  # 无 query 时跳过相关性检查，给中性分

                # ── 3. 信息密度 (权重 25%) ──
                snippet_lengths = [
                    len(str(item.get("snippet", "")))
                    for item in items
                    if isinstance(item, dict)
                ]
                avg_snippet_len = sum(snippet_lengths) / len(snippet_lengths) if snippet_lengths else 0
                # avg >= 80 chars 为满分，< 20 为 0 分
                density_score = min(100.0, max(0.0, (avg_snippet_len - 20) / 60 * 100.0))

                # 综合评分
                total_score = structure_score * 0.4 + relevance_score * 0.35 + density_score * 0.25
                passed = total_score >= 60.0 and relevance_score >= 30.0

                detail_parts = [f"搜索返回 {len(items)} 条结果"]
                if relevant_count > 0:
                    detail_parts.append(f"相关 {relevant_count}/{len(items)}")
                if avg_snippet_len > 0:
                    detail_parts.append(f"平均摘要 {avg_snippet_len:.0f} 字符")
                detail = "；".join(detail_parts)

                suggestion = None
                if not passed:
                    if relevance_score < 30.0:
                        suggestion = f"搜索结果与查询「{query[:60]}」相关性极低，建议更换更具体的搜索词"
                    elif density_score < 40.0:
                        suggestion = "搜索结果摘要过短，可能未抓取到有效网页内容"
                    else:
                        suggestion = "搜索质量不足，请尝试添加更具体的限定词重新搜索"

                return VerificationResult(
                    passed=passed, score=round(total_score, 1),
                    detail=detail, suggested_fix=suggestion, step_id=step_id,
                )

            elif self._tool_name == "fetch_job_page":
                raw_text = str(step_result.get("raw_text") or "")
                source_url = str(step_result.get("source_url") or "")
                if not source_url:
                    return VerificationResult(
                        passed=False, score=0, detail="缺少 source_url",
                        suggested_fix="请提供有效的岗位页面 URL", step_id=step_id,
                    )
                if len(raw_text) < 50:
                    return VerificationResult(
                        passed=False, score=20,
                        detail=f"抓取内容过短 ({len(raw_text)} 字符)，可能页面解析失败",
                        suggested_fix="请检查 URL 是否有效，或尝试其他采集方式",
                        step_id=step_id,
                    )
                has_job_info = bool(
                    step_result.get("job_title") or step_result.get("company")
                )
                score = 85 if has_job_info else 60
                return VerificationResult(
                    passed=True, score=score,
                    detail=f"抓取成功: {len(raw_text)} 字符"
                           + (f"，已识别岗位信息" if has_job_info else "，未识别具体岗位字段"),
                    step_id=step_id,
                )

            else:
                return VerificationResult(
                    passed=True, score=100, detail="无针对此实用工具的验收规则，跳过",
                    step_id=step_id,
                )

        except Exception as exc:
            logger.error("[UtilityVerifier] error for tool=%s: %s", self._tool_name, exc)
            return VerificationResult(
                passed=False, score=0, detail=f"验收出错: {exc}",
                suggested_fix="请人工检查", step_id=step_id,
            )


# ═══════════════════════════════════════════════════════════════
# TaskCompletionVerifier — 最终答案结构验收（纯规则，不调 LLM）
# ═══════════════════════════════════════════════════════════════

class TaskCompletionVerifier(BaseVerifier):
    """验收最终报告的结构是否匹配 task_type 的 expected_output_shape。

    职责边界：
      - 只检查：输出结构是否达标（是否有必要的标题/段落/元素）
      - 不检查：事实正确性、内容质量、LLM 幻觉
      - 决定：是否需要 replan（passed=False 时触发）

    输入（完整上下文）：
      - task_type: 任务类型
      - expected_output_shape: 期望输出结构（来自 EXPECTED_OUTPUT_SHAPES）
      - final_report: 最终生成的 Markdown 报告
      - normalized_outputs: 原始标准化工具输出（供参考，不直接判断）

    检查项（按 task_type 不同）：
      fact_lookup: 有关键信息段落 + 来源引用（或明确的"无结果"说明）
      comparison: 有对比结论段落 + 详细分析段落
      planning: 有阶段标记（## 或 阶段/Phase 关键词）
      analysis: 有评分/等级标记 + 建议段落
      其他: 最低限度 — 非纯链接列表 + 长度 ≥ 60 字符
    """

    template_name = "verify_task_completion"  # 不使用模板

    # 每种 task_type 的必须结构元素
    _STRUCTURAL_REQUIREMENTS: dict[str, list[str]] = {
        "fact_lookup": ["关键信息", "来源"],
        "comparison": ["对比结论", "详细分析", "|"],  # | 表示 Markdown 表格分隔符
        "planning": ["阶段", "任务"],
        "analysis": ["维度", "建议"],
        "recommendation": [],
        "rewrite": [],
        "extraction": [],
        "decision_support": [],
    }

    def _build_prompt(self, step_result, criteria, context):
        return ""  # 纯规则，不调 LLM

    def _parse_response(self, response):
        return VerificationResult(passed=False, score=0, detail="")

    async def verify(
        self,
        step_id: str,
        step_result: dict[str, Any],
        criteria: list[str],
        context: PipelineContext | None = None,
    ) -> VerificationResult:
        """纯规则结构验收。

        step_result 预期包含：
          - task_type: str
          - expected_output_shape: str
          - final_report: str
          - outputs: list[dict]（可选）
        """
        try:
            task_type = str(step_result.get("task_type", ""))
            final_report = str(step_result.get("final_report", ""))
            expected_shape = str(step_result.get("expected_output_shape", ""))

            if not final_report.strip():
                return VerificationResult(
                    passed=False, score=0,
                    detail="最终报告为空",
                    suggested_fix="所有步骤均未产生有效输出，请检查工具执行是否正常",
                    step_id=step_id,
                )

            # ── 通用检查：非纯链接列表 ──
            link_only = self._is_link_list_only(final_report)
            if link_only:
                return VerificationResult(
                    passed=False, score=20,
                    detail="最终报告为纯链接列表，未整合为自然语言答案",
                    suggested_fix="请确保 _finalizer 步骤正确执行了信息整合",
                    step_id=step_id,
                )

            # ── 通用检查：最小长度 ──
            if len(final_report.strip()) < 60:
                return VerificationResult(
                    passed=False, score=30,
                    detail=f"最终报告过短（{len(final_report.strip())} 字符）",
                    suggested_fix="报告内容不足，请检查是否所有步骤都成功执行",
                    step_id=step_id,
                )

            # ── 按 task_type 的结构检查 ──
            requirements = self._STRUCTURAL_REQUIREMENTS.get(task_type, [])
            if not requirements:
                # 无特殊结构要求的类型（recommendation/rewrite/extraction/decision_support）
                # 只做通用检查即可
                return VerificationResult(
                    passed=True, score=80,
                    detail=f"任务类型 {task_type} 无硬性结构要求，通用检查通过",
                    step_id=step_id,
                )

            missing = []
            missing_labels = []
            for req in requirements:
                if req == "|":
                    # 表格检查：至少有一个 Markdown 表格行
                    if "|" not in final_report:
                        missing.append(req)
                        missing_labels.append("对比表格")
                elif req not in final_report:
                    missing.append(req)
                    missing_labels.append(req)

            if missing:
                return VerificationResult(
                    passed=False, score=40,
                    detail=f"报告缺少必要结构元素: {', '.join(missing_labels)}。"
                           f"期望结构: {expected_shape[:80]}",
                    suggested_fix=(
                        f"最终报告未包含 {'/'.join(missing_labels)} 等关键段落。"
                        f"请确保 _finalizer 按 {task_type} 类型的标准结构生成答案。"
                    ),
                    step_id=step_id,
                )

            return VerificationResult(
                passed=True, score=85,
                detail=f"结构验收通过: 包含全部必要元素 {requirements}",
                step_id=step_id,
            )

        except Exception as exc:
            logger.error("[TaskCompletionVerifier] error: %s", exc)
            return VerificationResult(
                passed=False, score=0,
                detail=f"结构验收出错: {exc}",
                suggested_fix="请人工检查最终报告",
                step_id=step_id,
            )

    @staticmethod
    def _is_link_list_only(report: str) -> bool:
        """检查报告是否基本只由 Markdown 链接组成。"""
        import re
        # 去掉所有 Markdown 链接
        no_links = re.sub(r"\[([^\]]*)\]\([^)]*\)", "", report)
        # 去掉标题和空行
        cleaned = re.sub(r"^#+\s.*$", "", no_links, flags=re.MULTILINE).strip()
        cleaned = re.sub(r"\n\s*\n", "\n", cleaned).strip()
        # 如果清理后几乎没有实质性文字，判定为纯链接列表
        meaningful = re.sub(r"[\s\-\*>`|#]", "", cleaned)
        # 阈值 12：约 4-5 个中文汉字，只拦真正全是链接的报告
        return len(meaningful) < 12


# ═══════════════════════════════════════════════════════════════
# TaskGoalVerifier — 任务目标达成验收（LLM，仅 fact_lookup + comparison）
# ═══════════════════════════════════════════════════════════════

class TaskGoalVerifier(BaseVerifier):
    """验收最终答案是否真正完成了任务目标。

    与 TaskCompletionVerifier 的区别：
      - TCV 检查"结构是否达标"（纯规则，所有 task_type）
      - TGV 检查"目标是否达成"（LLM，仅 fact_lookup + comparison）

    Phase 3 Step 3: 先只覆盖这两个高频且最容易出现"结构对但答案差"的类型。
    """

    template_name = "verify_task_goal"
    # 仅支持这两种类型
    _SUPPORTED_TYPES: frozenset = frozenset({"fact_lookup", "comparison"})

    @classmethod
    def supports_type(cls, task_type: str) -> bool:
        return task_type in cls._SUPPORTED_TYPES

    def _build_prompt(
        self, step_result: dict, criteria: list[str], context: PipelineContext
    ) -> str:
        task_type = str(step_result.get("task_type", ""))
        final_report = str(step_result.get("final_report", ""))
        expected_shape = str(step_result.get("expected_output_shape", ""))
        goal = context.goal if context else str(step_result.get("goal", ""))

        return _prompt_manager.render(
            self.template_name,
            goal=goal,
            task_type=task_type,
            expected_output_shape=expected_shape,
            final_report=final_report,
        )

    def _parse_response(self, response: str) -> VerificationResult:
        data = self._extract_json(response)
        if data is None:
            return VerificationResult(
                passed=False, score=0,
                detail="无法解析目标验收结果 — LLM 未返回有效 JSON",
                suggested_fix="请人工检查最终答案是否达成了目标",
            )

        overall_passed = bool(data.get("overall_passed", False))
        score = max(0.0, min(100.0, float(data.get("overall_score", 0))))
        detail = str(data.get("detail", ""))
        dim_results = data.get("dimension_results", [])

        # 任何维度失败 → 不通过
        if dim_results:
            failed = [d for d in dim_results if not d.get("passed", False)]
            if failed:
                overall_passed = False

        return VerificationResult(
            passed=overall_passed,
            score=score,
            detail=detail,
            suggested_fix=data.get("suggested_fix") if not overall_passed else None,
        )


# ── Verifier 单例 ──

_utility_v_search = UtilityVerifier("search_knowledge")
_utility_v_list_resumes = UtilityVerifier("list_resumes")
_utility_v_list_jobs = UtilityVerifier("list_jobs")
_utility_v_get_task = UtilityVerifier("get_task")
_utility_v_public_search = UtilityVerifier("public_search")
_utility_v_fetch_job = UtilityVerifier("fetch_job_page")

# 第二级 LLM verifier — 仅 info_gathering 路径使用
_info_gathering_v = InfoGatheringVerifier()

# Level 2 verifier 触发条件映射
_SECOND_LEVEL_MAP: dict[str, BaseVerifier] = {
    "public_search": _info_gathering_v,
    "fetch_job_page": _info_gathering_v,
}


_VERIFIER_MAP = {
    "match_analyze": _match_v,
    "optimize_resume": _resume_v,
    "generate_resume": _resume_v,
    "generate_interview_questions": _interview_v,
    "recommend_jobs": _recommend_v,
    "search_knowledge": _utility_v_search,
    "list_resumes": _utility_v_list_resumes,
    "list_jobs": _utility_v_list_jobs,
    "get_task": _utility_v_get_task,
    "public_search": _utility_v_public_search,
    "fetch_job_page": _utility_v_fetch_job,
}


def get_verifier(tool_name: str) -> BaseVerifier | None:
    """根据工具名返回对应的第一级 Verifier。未找到时返回 None（跳过验收）。"""
    # 精确匹配
    if tool_name in _VERIFIER_MAP:
        return _VERIFIER_MAP[tool_name]
    # 子串匹配
    for key, v in _VERIFIER_MAP.items():
        if tool_name in key or key in tool_name:
            logger.info("get_verifier: fuzzy match '%s' → %s", tool_name, type(v).__name__)
            return v
    logger.info("get_verifier: no verifier for tool '%s', skipping verification", tool_name)
    return None


def get_second_level_verifier(tool_name: str, goal_type: str) -> BaseVerifier | None:
    """返回第二级 Verifier（LLM 质量把关）。

    仅在以下条件同时满足时返回非 None：
    - tool_name 在 _SECOND_LEVEL_MAP 中（public_search / fetch_job_page）
    - goal_type == "info_gathering"

    Args:
        tool_name: 已解析的工具名
        goal_type: 当前 task 的 goal_type（来自 TaskState）

    Returns:
        BaseVerifier 或 None（不触发第二级验收）
    """
    if goal_type != "info_gathering":
        return None
    return _SECOND_LEVEL_MAP.get(tool_name)
