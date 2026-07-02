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
                if not isinstance(items, list) or len(items) == 0:
                    return VerificationResult(
                        passed=False, score=0, detail="公开搜索未返回结果",
                        suggested_fix="请使用不同的查询词重新搜索", step_id=step_id,
                    )
                # 检查每项至少有 title 和 url
                for i, item in enumerate(items):
                    if not isinstance(item, dict) or not item.get("title") or not item.get("url"):
                        return VerificationResult(
                            passed=False, score=30,
                            detail=f"搜索结果 #{i+1} 缺少 title 或 url",
                            suggested_fix="搜索源返回数据不完整", step_id=step_id,
                        )
                return VerificationResult(
                    passed=True, score=85, detail=f"搜索返回 {len(items)} 条结果",
                    step_id=step_id,
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


# ── Verifier 单例 ──

_utility_v_search = UtilityVerifier("search_knowledge")
_utility_v_list_resumes = UtilityVerifier("list_resumes")
_utility_v_list_jobs = UtilityVerifier("list_jobs")
_utility_v_get_task = UtilityVerifier("get_task")
_utility_v_public_search = UtilityVerifier("public_search")
_utility_v_fetch_job = UtilityVerifier("fetch_job_page")


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
    """根据工具名返回对应的 Verifier。未找到时返回 None（跳过验收）。"""
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
