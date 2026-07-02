"""Pipeline 状态定义 — LangGraph 用的 TypedDict + 累积上下文数据类。"""

import logging
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """Pipeline 执行期间的累积上下文。

    在工具调用链中不断积累信息：用户选定了哪个简历、哪个岗位、
    中间步骤的分析结果、最终任务 ID 列表等。
    """
    # 用户选定的资源
    resume_id: int | None = None
    job_id: int | None = None
    personal_info: str | None = None

    # 用户意图
    goal: str | None = None

    # Phase 2 任务分类（Round A）
    task_type: str = ""              # 8 类之一：fact_lookup / comparison / planning / analysis / ...
    expected_output_shape: str = ""  # 自然语言描述期望输出结构
    execution_mode: str = ""         # 执行模式：comparison_search | comparison_structured | ""

    # 外部输入（URL、额外文本等）
    external_urls: list[str] = field(default_factory=list)
    extra_context_text: str = ""

    # 会话相关
    session_id: int | None = None
    messages_summary: str | None = None

    # 各步骤的执行结果（按工具名存储）
    tool_results: dict[str, dict[str, Any]] = field(default_factory=dict)

    # 已完成的工具调用顺序记录
    executed_tools: list[str] = field(default_factory=list)

    # 产生的任务 ID 列表
    task_ids: list[int] = field(default_factory=list)

    def record_result(self, tool_name: str, result: dict[str, Any]) -> None:
        """记录一个工具的执行结果。"""
        self.executed_tools.append(tool_name)
        if not isinstance(result, dict):
            logger.error(
                "[PipelineContext] record_result: expected dict, got %s for tool=%s, converting",
                type(result).__name__, tool_name,
            )
            result = {"_raw": str(result)}
        self.tool_results[tool_name] = result
        task_id = result.get("task_id")
        if task_id is not None:
            self.task_ids.append(int(task_id))

    def to_summary(self) -> dict[str, Any]:
        """将上下文导出为可供汇总的结构。"""
        return {
            "resume_id": self.resume_id,
            "job_id": self.job_id,
            "personal_info_length": len(self.personal_info or ""),
            "extra_context_text_length": len(self.extra_context_text or ""),
            "external_urls": list(self.external_urls),
            "executed_tools": list(self.executed_tools),
            "task_ids": list(self.task_ids),
            "task_type": self.task_type,
            "expected_output_shape": self.expected_output_shape,
            "execution_mode": self.execution_mode,
            "tool_results": dict(self.tool_results),
        }


class PipelineState(TypedDict):
    """LangGraph StateGraph 使用的状态类型。

    核心字段 messages 是 LangChain 消息列表，
    LangGraph 的 ToolNode 依赖这个字段自动拼接工具调用和结果。
    """
    messages: list[BaseMessage]
    context: PipelineContext
    user_id: int


@dataclass
class TaskState:
    """任务推进状态 — 记录"任务做到哪了、为什么没完成、下一步干什么"。

    与 PipelineContext 的区别：
      - PipelineContext: 执行上下文（选了哪个简历、调了哪些工具）
      - TaskState: 任务状态机（目标、计划、进度、阻塞、验收）
    """

    # ── 目标 ──
    goal: str = ""
    goal_type: str = ""  # task_type: info_gathering / match_analysis / resume_optimization / interview_prep / full_prep / comparison / review / planning
    goal_status: str = "created"  # created → planning → running → blocked → verifying → completed → failed

    # ── 计划 ──
    plan_steps: list[dict] = field(default_factory=list)
    # 每步: {id, name, description, depends_on:[], status:pending|running|done|skipped|failed,
    #        acceptance_criteria, verification_result, assigned_agent}

    current_step: str = ""       # 当前正在执行的 step id
    completed_steps: list[str] = field(default_factory=list)
    pending_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)    # blocked 类失败（工具崩溃/缺输入/外部不可用）
    blocked_steps: list[str] = field(default_factory=list)   # 同上，语义别名

    # ── 等待用户 ──
    waiting_for_user_input: bool = False
    user_prompt: str = ""        # 展示给用户: "请先上传简历" / "请先创建目标岗位"

    # ── 阻塞 ──
    blockers: list[dict] = field(default_factory=list)
    # 每项: {type: missing_input|low_quality|external|user_action,
    #        description, resolution_hint, resolved:bool}

    # ── 下一步 ──
    next_action: str = ""        # 面向用户的下一步行动描述

    # ── 验收 ──
    acceptance_criteria: list[str] = field(default_factory=list)
    verification_results: list[dict] = field(default_factory=list)
    # 每项: {step_id, criteria, passed:bool, score, detail, suggested_fix}

    # ── 重规划 ──
    replan_count: int = 0
    max_replan: int = 3

    # ── 最终输出 ──
    final_report: str = ""
    next_suggestions: list[str] = field(default_factory=list)

    def is_blocked(self) -> bool:
        """检查是否有未解决的阻塞项。"""
        return len(self.blockers) > 0 and all(not b.get("resolved") for b in self.blockers)

    def all_verified(self) -> bool:
        """检查所有验收项是否通过。"""
        if not self.verification_results:
            return False
        return all(v.get("passed") for v in self.verification_results)

    def needs_replan(self) -> bool:
        """判断是否需要重规划。"""
        return (not self.all_verified() and self.replan_count < self.max_replan)

    def to_dict(self) -> dict:
        """序列化为扁平字典（调用方负责 json.dumps 列表/字典字段）。"""
        return {
            "goal": self.goal,
            "goal_type": self.goal_type,
            "goal_status": self.goal_status,
            "plan_steps": self.plan_steps,
            "current_step": self.current_step,
            "completed_steps": self.completed_steps,
            "pending_steps": self.pending_steps,
            "failed_steps": self.failed_steps,
            "blocked_steps": self.blocked_steps,
            "blockers": self.blockers,
            "next_action": self.next_action,
            "acceptance_criteria": self.acceptance_criteria,
            "verification_results": self.verification_results,
            "replan_count": self.replan_count,
            "max_replan": self.max_replan,
            "final_report": self.final_report,
            "next_suggestions": self.next_suggestions,
            "waiting_for_user_input": self.waiting_for_user_input,
            "user_prompt": self.user_prompt,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TaskState":
        """从扁平字典重建（调用方已反序列化 JSON 字段）。

        兼容：
          - DB 列名 `status` → `goal_status`
          - DB 列名 `plan_json` → `plan_steps`（以及所有 `_json` 后缀列）
          - NULL 值（DB 中 NULL 在 dict 中为 None → 使用默认值）
        """
        def _list(val, fallback=None):
            """安全获取 list，None → []。"""
            if fallback is None:
                fallback = []
            return val if isinstance(val, list) else fallback

        def _str(val, fallback=""):
            """安全获取 str，None → ''。"""
            return val if isinstance(val, str) else fallback

        return cls(
            goal=_str(d.get("goal")),
            goal_type=_str(d.get("goal_type")),
            goal_status=_str(d.get("goal_status", d.get("status")), "created"),
            plan_steps=_list(d.get("plan_steps", d.get("plan_json"))),
            current_step=_str(d.get("current_step")),
            completed_steps=_list(d.get("completed_steps", d.get("completed_steps_json"))),
            pending_steps=_list(d.get("pending_steps", d.get("pending_steps_json"))),
            failed_steps=_list(d.get("failed_steps", d.get("failed_steps_json"))),
            blocked_steps=_list(d.get("blocked_steps", d.get("blocked_steps_json"))),
            blockers=_list(d.get("blockers", d.get("blockers_json"))),
            next_action=_str(d.get("next_action")),
            acceptance_criteria=_list(d.get("acceptance_criteria", d.get("acceptance_criteria_json"))),
            verification_results=_list(d.get("verification_results", d.get("verification_results_json"))),
            replan_count=d.get("replan_count") if isinstance(d.get("replan_count"), int) else 0,
            max_replan=d.get("max_replan") if isinstance(d.get("max_replan"), int) else 3,
            final_report=_str(d.get("final_report")),
            next_suggestions=_list(d.get("next_suggestions", d.get("next_suggestions_json"))),
            waiting_for_user_input=bool(d.get("waiting_for_user_input", False)),
            user_prompt=_str(d.get("user_prompt")),
        )
