"""ClosedLoopOrchestrator - Agent orchestration core.

State machine: plan -> precheck -> execute -> verify -> (replan) -> finalize
"""

import asyncio
import json
import logging
import re
import time
from typing import Any, AsyncGenerator

from app.shared.stream_utils import (
    error_event,
    final_event,
    sse_event,
    step_complete_event,
    step_start_event,
    step_token_event,
)
from app.shared.state import PipelineContext, TaskState
from app.ai.llm import invoke_llm
from app.infrastructure.db.crud import create_agent_run, get_agent_run, update_agent_run
from app.application.step_mapping import resolve as resolve_step_tool
from app.ai.verifiers import VerificationResult, get_verifier
from app.ai.prompt_engine import PromptManager
from app.tools.registry import tool_registry

logger = logging.getLogger(__name__)

_prompt_manager = PromptManager(version="v1")

PLAN_MODEL = "primary"
VERIFY_MODEL = "fast"


def _make_short_summary(task_state, context) -> str:
    """Generate a one-line status summary."""
    count = len(context.executed_tools)
    verified = sum(1 for v in task_state.verification_results if v.get("passed"))
    failed = len(task_state.failed_steps)
    parts = [f"{count} steps executed"]
    if verified:
        parts.append(f"{verified} verified")
    if failed:
        parts.append(f"{failed} failed")
    return ", ".join(parts)


class ClosedLoopOrchestrator:
    """Orchestrator: goal -> plan -> execute -> verify -> (replan) -> finalize."""

    def __init__(self, max_replan: int = 3):
        self.max_replan = max_replan

    # ============================================================
    # Main entry points
    # ============================================================

    async def run(self, goal, context, user_id, run_id=None, skill_hints=None):
        """Full state machine (non-streaming)."""
        task_state, run_id = await self._init_task_state(goal, context, user_id, run_id)

        if task_state.goal_status in ("created", "planning"):
            task_state = await self._plan(goal, task_state, context, skill_hints=skill_hints)
            await self._persist(task_state, run_id, user_id)
            if task_state.is_blocked():
                return task_state

        if task_state.goal_status in ("planning", "running"):
            task_state = await self._precheck(goal, task_state, context, user_id)
            await self._persist(task_state, run_id, user_id)
            if task_state.is_blocked():
                return task_state

        if task_state.goal_status in ("running",):
            task_state = await self._execute_verify_loop(goal, task_state, context, user_id, run_id)
            await self._persist(task_state, run_id, user_id)

        while task_state.needs_replan() and task_state.goal_status != "blocked":
            task_state = await self._replan(goal, task_state, context)
            await self._persist(task_state, run_id, user_id)
            if task_state.is_blocked():
                return task_state
            task_state = await self._execute_verify_loop(goal, task_state, context, user_id, run_id)
            await self._persist(task_state, run_id, user_id)

        if task_state.all_verified() and task_state.goal_status != "completed":
            task_state = await self._finalize(goal, task_state, context)
            await self._persist(task_state, run_id, user_id)

        return task_state

    async def run_stream(self, goal, context, user_id, run_id=None, skill_hints=None, intent_type=""):
        """SSE streaming version."""
        task_state, run_id = await self._init_task_state(goal, context, user_id, run_id)

        # Phase 1: Plan
        if task_state.goal_status in ("created", "planning"):
            yield step_start_event("orchestrator.plan", {"goal": goal[:80]}, label="Plan")
            task_state = await self._plan(goal, task_state, context, skill_hints=skill_hints, intent_type=intent_type)
            await self._persist(task_state, run_id, user_id)
            if task_state.is_blocked():
                yield error_event("orchestrator.plan", "Planning failed")
                return
            plan_text = self._format_plan_for_display(task_state)
            if plan_text:
                yield step_token_event("orchestrator.plan", plan_text)
            yield step_complete_event("orchestrator.plan", {
                "plan_steps": task_state.plan_steps,
                "acceptance_criteria": task_state.acceptance_criteria,
            })

        # Phase 2: Precheck
        if task_state.goal_status in ("planning", "running"):
            yield step_start_event("orchestrator.precheck", {}, label="Precheck")
            task_state = await self._precheck(goal, task_state, context, user_id)
            await self._persist(task_state, run_id, user_id)
            if task_state.is_blocked():
                yield step_complete_event("orchestrator.precheck", {"ok": False, "blockers": task_state.blockers})
                yield final_event(f"Precheck failed: {len(task_state.blockers)} blockers", [], None)
                return
            yield step_complete_event("orchestrator.precheck", {"ok": True, "blockers": []})

        # Phase 3: Execute + Verify
        if task_state.goal_status in ("running",):
            async for event_str in self._execute_verify_loop_stream(goal, task_state, context, user_id, run_id):
                yield event_str
            await self._persist(task_state, run_id, user_id)

            if task_state.failed_steps:
                task_state.goal_status = "blocked"
                task_state.next_action = f"Steps failed: {task_state.failed_steps}"
                await self._persist(task_state, run_id, user_id)
                yield error_event("orchestrator", f"Critical step failure: {task_state.failed_steps}")
                yield final_event(f"Failed - {len(task_state.failed_steps)} steps", context.task_ids, context.session_id)
                return

        # Phase 4: Replan loop
        while task_state.needs_replan() and task_state.goal_status != "blocked":
            yield step_start_event("orchestrator.replan", {"attempt": task_state.replan_count + 1}, label="Replan")
            prev_pending = set(task_state.pending_steps)
            task_state = await self._replan(goal, task_state, context)
            await self._persist(task_state, run_id, user_id)

            new_pending = set(task_state.pending_steps)
            if not new_pending or new_pending == prev_pending:
                logger.warning("[Orchestrator] replan produced same steps, breaking loop")
                task_state.goal_status = "blocked"
                task_state.next_action = "No alternative approach available"
                await self._persist(task_state, run_id, user_id)
                yield error_event("orchestrator.replan", "Replan produced no new steps")
                break

            yield step_complete_event("orchestrator.replan", {
                "new_steps": [s["id"] for s in task_state.plan_steps if s["id"] not in task_state.completed_steps],
            })
            if task_state.is_blocked():
                break
            async for event_str in self._execute_verify_loop_stream(goal, task_state, context, user_id, run_id):
                yield event_str
            await self._persist(task_state, run_id, user_id)

            if task_state.failed_steps:
                task_state.goal_status = "blocked"
                await self._persist(task_state, run_id, user_id)
                yield error_event("orchestrator", f"Step failure: {task_state.failed_steps}")
                break

        # Phase 5: Finalize
        if task_state.all_verified() and task_state.goal_status != "completed":
            yield step_start_event("orchestrator.finalize", {}, label="Finalize")
            task_state = await self._finalize(goal, task_state, context)
            await self._persist(task_state, run_id, user_id)
            if task_state.final_report:
                yield step_token_event("orchestrator.finalize", task_state.final_report)
            yield step_complete_event("orchestrator.finalize", {
                "report_length": len(task_state.final_report),
                "next_suggestions": task_state.next_suggestions,
            })
            yield final_event(_make_short_summary(task_state, context), context.task_ids, context.session_id)
        elif task_state.goal_status == "blocked":
            msg = task_state.next_action or task_state.user_prompt or "任务被阻塞，请检查前置条件后重试"
            yield final_event(msg, context.task_ids, context.session_id)
        elif task_state.replan_count >= task_state.max_replan and not task_state.all_verified():
            # 重规划次数耗尽
            task_state.goal_status = "blocked"
            task_state.next_action = "重规划次数已用完，建议简化需求后重试"
            task_state.waiting_for_user_input = True
            failed_vr = [v for v in task_state.verification_results if not v.get("passed")]
            yield final_event(
                f"重规划已用尽 ({task_state.replan_count}/{task_state.max_replan})，"
                f"{len(failed_vr)} 个步骤验收未通过。建议简化需求或补充更多信息后重试。",
                context.task_ids, context.session_id,
            )
        else:
            failed_vr = [v for v in task_state.verification_results if not v.get("passed")]
            yield final_event(
                f"未完成 - {len(failed_vr)} 个验收未通过",
                context.task_ids, context.session_id,
            )

    # ============================================================
    # Phase 1: Precheck
    # ============================================================

    async def _precheck(self, goal, task_state, context, user_id):
        """按任务类型动态预检（委托给 precheck 模块）。"""
        from app.application.precheck import precheck as run_precheck

        task_type = task_state.goal_type or self._infer_goal_type(goal)
        ok, blockers = await run_precheck(task_type, context, user_id)

        task_state.blockers = blockers
        if blockers:
            task_state.goal_status = "blocked"
            task_state.waiting_for_user_input = True
            task_state.user_prompt = blockers[0].get("user_prompt", "请补充必要信息后重试")
            task_state.next_action = blockers[0].get("resolution_hint", "Missing prerequisites")
        else:
            task_state.goal_status = "running"
        return task_state

    # ============================================================
    # Phase 2: Plan
    # ============================================================

    async def _plan(self, goal, task_state, context, skill_hints=None, intent_type=""):
        """Generate plan steps + acceptance criteria using primary model."""
        tool_list = tool_registry.list_all()
        available_tools = [{"name": t.name, "description": t.description} for t in tool_list]

        # intent_type 从 classify_intent() 传入（强提示）；无值时用 _infer_goal_type 兜底
        goal_type = intent_type or task_state.goal_type or self._infer_goal_type(goal)

        prompt = _prompt_manager.render("orchestrate_plan", goal=goal, goal_type=goal_type,
                                         intent_type=goal_type,
                                         resume_id=context.resume_id, job_id=context.job_id,
                                         available_tools=available_tools, skill_hints=skill_hints,
                                         extra_context_text=context.extra_context_text,
                                         external_urls=context.external_urls)

        try:
            response = await asyncio.to_thread(invoke_llm, prompt, model_key=PLAN_MODEL)
            data = self._extract_json(response)
        except Exception as exc:
            logger.error("[Planner] LLM call failed: %s", exc)
            task_state.blockers.append({"type": "low_quality", "description": f"Planner LLM failed: {exc}", "resolution_hint": "Retry", "resolved": False})
            task_state.goal_status = "blocked"
            return task_state

        if data is None:
            logger.warning("[Planner] JSON parse failed, retrying...")
            try:
                retry_prompt = prompt + "\n\nYour previous response was not valid JSON. Output only a JSON object."
                response = await asyncio.to_thread(invoke_llm, retry_prompt, model_key=PLAN_MODEL)
                data = self._extract_json(response)
            except Exception as exc:
                logger.error("[Planner] retry failed: %s", exc)

        if data is None:
            task_state.blockers.append({"type": "low_quality", "description": "Planner did not return valid JSON", "resolution_hint": "Simplify goal and retry", "resolved": False})
            task_state.goal_status = "blocked"
            return task_state

        plan_steps = data.get("plan_steps", [])
        for step in plan_steps:
            step.setdefault("status", "pending")
            step.setdefault("depends_on", [])

        task_state.goal_type = goal_type
        task_state.plan_steps = plan_steps
        task_state.acceptance_criteria = data.get("acceptance_criteria", [])
        task_state.pending_steps = [s["id"] for s in plan_steps if s.get("status") == "pending"]
        task_state.goal_status = "running"

        logger.info("[Planner] generated %d steps, %d criteria", len(plan_steps), len(task_state.acceptance_criteria))
        return task_state

    # ============================================================
    # Phase 3: Execute + Verify
    # ============================================================

    async def _execute_verify_loop(self, goal, task_state, context, user_id, run_id):
        """Execute all pending steps, verify each."""
        task_state.goal_status = "running"
        while task_state.pending_steps:
            step = self._next_ready_step(task_state)
            if step is None:
                logger.warning("[Executor] no ready step but %d pending", len(task_state.pending_steps))
                break

            step_id = step.get("id", "")
            task_state.current_step = step_id
            step["status"] = "running"
            await self._persist(task_state, run_id, user_id)

            step_result = await self._execute_step(step, context, user_id)

            if step_result.get("error"):
                err_msg = step_result["error"]
                err_cat = step_result.get("error_category", "")
                is_blocked = (
                    err_cat == "blocked"
                    or "config_error" in str(err_msg)
                    or "external_unavailable" in str(err_msg)
                    or "missing" in str(err_msg).lower()
                )
                if is_blocked:
                    step["status"] = "failed"
                    task_state.failed_steps.append(step_id)
                    task_state.blocked_steps.append(step_id)
                else:
                    # replan 类失败: 不放入 failed_steps，让 verification 兜底
                    step["status"] = "done"
                    task_state.completed_steps.append(step_id)
                task_state.pending_steps = [s for s in task_state.pending_steps if s != step_id]
                task_state.current_step = ""
                await self._persist(task_state, run_id, user_id)
                if is_blocked:
                    continue

            if not step_result.get("error"):
                step["status"] = "done"
                task_state.completed_steps.append(step_id)
                task_state.pending_steps = [s for s in task_state.pending_steps if s != step_id]
                task_state.current_step = ""

            vr = await self._verify_step(step, step_result, task_state.acceptance_criteria, context)
            step["verification_result"] = vr.to_dict()
            task_state.verification_results.append(vr.to_dict())
            await self._persist(task_state, run_id, user_id)

        return task_state

    async def _execute_verify_loop_stream(self, goal, task_state, context, user_id, run_id):
        """Streaming execute loop - emits SSE events for each step."""
        from app.application.workflows.common import _token_callback

        task_state.goal_status = "running"

        while task_state.pending_steps:
            step = self._next_ready_step(task_state)
            if step is None:
                logger.warning("[Executor] no ready step but %d pending", len(task_state.pending_steps))
                break

            step_id = step.get("id", "")
            step_tool = step.get("tool", "")

            # Handle _finalizer pseudo-tool
            if step_tool == "_finalizer":
                step["status"] = "done"
                task_state.completed_steps.append(step_id)
                task_state.pending_steps = [s for s in task_state.pending_steps if s != step_id]
                task_state.verification_results.append({"step_id": step_id, "passed": True, "score": 100.0, "detail": "Handled by Finalizer"})
                await self._persist(task_state, run_id, user_id)
                continue

            tool_name, default_params = resolve_step_tool(step_tool)
            if tool_name is None:
                logger.error("[Executor] unknown tool '%s' for step %s", step_tool, step_id)
                step["status"] = "failed"
                task_state.failed_steps.append(step_id)
                task_state.pending_steps = [s for s in task_state.pending_steps if s != step_id]
                continue

            task_state.current_step = step_id
            step["status"] = "running"
            await self._persist(task_state, run_id, user_id)

            # Build params
            params = dict(default_params)
            step_args = step.get("args", {})
            if isinstance(step_args, dict):
                params.update(step_args)
            params["user_id"] = user_id
            params.setdefault("resume_id", context.resume_id)
            params.setdefault("job_id", context.job_id)

            if tool_name == "fetch_job_page" and "url" not in params and context.external_urls:
                params["url"] = context.external_urls[0]
                logger.info("[Executor:stream] auto-injected url: %s", params["url"][:80])
            elif tool_name == "public_search" and "query" not in params:
                params["query"] = context.goal or step.get("description", "")
                logger.info("[Executor:stream] auto-generated query: %s", params["query"][:80])
            elif tool_name == "search_knowledge" and "query" not in params:
                step_name = step.get("name", step.get("description", ""))
                params["query"] = f"{context.goal or ''} {step_name}".strip()
                logger.info("[Executor:stream] auto-generated query: %s", params["query"][:80])

            # Pre-check required inputs
            tool = tool_registry.get(tool_name)
            if tool is None:
                step["status"] = "failed"
                task_state.failed_steps.append(step_id)
                yield error_event(tool_name, f"Tool not registered: {tool_name}")
                task_state.pending_steps = [s for s in task_state.pending_steps if s != step_id]
                continue

            missing = []
            if tool.input_requirements.resume_id and params.get("resume_id") is None:
                missing.append("resume")
            if tool.input_requirements.job_id and params.get("job_id") is None:
                missing.append("job")
            if missing:
                msg = f"Missing required inputs: {', '.join(missing)}"
                step["status"] = "failed"
                task_state.failed_steps.append(step_id)
                yield error_event(tool_name, msg)
                task_state.pending_steps = [s for s in task_state.pending_steps if s != step_id]
                continue

            yield step_start_event(tool_name, {"orchestrator_step": step_id, "step_name": step.get("name", "")})
            logger.info("[Executor:stream] step=%s tool=%s", step_id, tool_name)

            # Streaming tool execution
            token_q = asyncio.Queue()

            def _on_token(t):
                try:
                    token_q.put_nowait(t)
                except asyncio.QueueFull:
                    pass

            token_token = _token_callback.set(_on_token)
            try:
                exec_task = asyncio.create_task(tool.execute(**params))
                while not exec_task.done():
                    tokens = []
                    while True:
                        try:
                            tokens.append(token_q.get_nowait())
                        except asyncio.QueueEmpty:
                            break
                    if tokens:
                        yield step_token_event(tool_name, "".join(tokens))
                    else:
                        await asyncio.sleep(0.03)

                tail = []
                while True:
                    try:
                        tail.append(token_q.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                if tail:
                    yield step_token_event(tool_name, "".join(tail))

                tool_result = await exec_task
                if tool_result.success and tool_result.data:
                    step_result = tool_result.data
                    context.record_result(tool_name, step_result)
                else:
                    step_result = {"error": tool_result.error or "Tool execution failed",
                                   "error_category": "blocked"}  # 工具返回 failure → blocked
            except Exception as exc:
                logger.exception("[Executor:stream] step=%s tool=%s exception", step_id, tool_name)
                step_result = {"error": str(exc), "error_category": "blocked"}  # 异常 → blocked
            finally:
                _token_callback.reset(token_token)

            if step_result.get("error"):
                err_msg = step_result["error"]
                err_cat = step_result.get("error_category", "")
                # ── 区分 blocked vs replan ──
                is_blocked = (
                    err_cat == "blocked"
                    or "config_error" in str(err_msg)
                    or "external_unavailable" in str(err_msg)
                    or "missing" in str(err_msg).lower()
                )
                if is_blocked:
                    step["status"] = "failed"
                    task_state.failed_steps.append(step_id)
                    task_state.blocked_steps.append(step_id)
                    yield error_event(tool_name, err_msg)
                else:
                    # replan 类失败: 不放入 failed_steps，让 verification 兜底
                    step["status"] = "done"
                    task_state.completed_steps.append(step_id)
                    yield step_complete_event(tool_name, step_result)
            else:
                step["status"] = "done"
                task_state.completed_steps.append(step_id)
                yield step_complete_event(tool_name, step_result)

                if tool_name == "fetch_job_page" and not context.job_id:
                    try:
                        from app.infrastructure.external_job import create_temp_job_from_fetch
                        job_id = await create_temp_job_from_fetch(step_result, user_id)
                        if job_id:
                            context.job_id = job_id
                            logger.info("[Executor:stream] auto-created job_id=%d", job_id)
                    except Exception as bridge_exc:
                        logger.warning("[Executor:stream] bridge fetch->job failed: %s", bridge_exc)

            task_state.pending_steps = [s for s in task_state.pending_steps if s != step_id]
            task_state.current_step = ""

            vr = await self._verify_step(step, step_result, task_state.acceptance_criteria, context)
            step["verification_result"] = vr.to_dict()
            task_state.verification_results.append(vr.to_dict())
            await self._persist(task_state, run_id, user_id)

    async def _execute_step(self, step, context, user_id):
        """Execute a single step (non-streaming)."""
        step_id = step.get("id", "unknown")
        step_tool = step.get("tool", "")

        tool_name, default_params = resolve_step_tool(step_tool)
        if tool_name is None:
            return {"error": f"Cannot resolve tool: {step_tool}"}

        tool = tool_registry.get(tool_name)
        if tool is None:
            return {"error": f"Tool not registered: {tool_name}"}

        params = dict(default_params)
        params["user_id"] = user_id
        params.setdefault("resume_id", context.resume_id)
        params.setdefault("job_id", context.job_id)

        if tool_name == "search_knowledge" and "query" not in params:
            step_name = step.get("name", step.get("description", ""))
            params["query"] = f"{context.goal or ''} {step_name}".strip()

        logger.info("[Executor] step=%s tool=%s", step_id, tool_name)

        try:
            result = await tool.execute(**params)
            if result.success:
                context.record_result(tool_name, result.data or {})
                return result.data or {}
            else:
                return {"error": result.error or "Tool execution failed"}
        except Exception as exc:
            logger.exception("[Executor] step=%s exception", step_id)
            return {"error": str(exc)}

    async def _verify_step(self, step, step_result, criteria, context):
        """Verify step output."""
        step_id = step.get("id", "unknown")
        step_tool = step.get("tool", "")
        tool_name, _ = resolve_step_tool(step_tool)
        if tool_name is None:
            return VerificationResult(passed=False, score=0, detail=f"Cannot resolve tool: {step_tool}", step_id=step_id)

        verifier = get_verifier(tool_name)
        if verifier is None:
            logger.info("[Verifier] no verifier for tool=%s, skipping", tool_name)
            return VerificationResult(passed=True, score=100.0, detail="No verifier, skipped", step_id=step_id)

        vr = await verifier.verify(step_id, step_result, criteria, context)
        logger.info("[Verifier] step=%s tool=%s passed=%s score=%.0f", step_id, tool_name, vr.passed, vr.score)
        return vr

    # ============================================================
    # Phase 4: Replan
    # ============================================================

    async def _replan(self, goal, task_state, context):
        """Replan failed steps — 清除旧失败状态，仅重规划未通过的步骤。"""
        # 先捕获失败结果（供 replan prompt 使用），再清除旧状态
        prev_verification_results = list(task_state.verification_results)
        prev_failed_steps = list(task_state.failed_steps)

        task_state.failed_steps.clear()
        task_state.blocked_steps.clear()
        task_state.verification_results.clear()
        task_state.replan_count += 1
        logger.info("[Replanner] attempt %d/%d (%d failed verifications, %d blocked steps)",
                     task_state.replan_count, task_state.max_replan,
                     sum(1 for v in prev_verification_results if not v.get("passed")),
                     len(prev_failed_steps))

        original_plan = json.dumps(task_state.plan_steps, ensure_ascii=False, indent=2)
        failed_results = json.dumps(
            [{"step_id": v.get("step_id"), "passed": v.get("passed"), "score": v.get("score"),
              "detail": v.get("detail"),
              "tool": next((s.get("tool", "") for s in task_state.plan_steps if s["id"] == v.get("step_id")), "")}
             for v in prev_verification_results if not v.get("passed")],
            ensure_ascii=False, indent=2,
        )

        tool_list = tool_registry.list_all()
        available_tools = [{"name": t.name, "description": t.description} for t in tool_list]
        prompt = _prompt_manager.render("orchestrate_replan", goal=goal, original_plan=original_plan,
                                         failed_results=failed_results, available_tools=available_tools)

        try:
            response = await asyncio.to_thread(invoke_llm, prompt, model_key=PLAN_MODEL)
            data = self._extract_json(response)
        except Exception as exc:
            logger.error("[Replanner] LLM call failed: %s", exc)
            if task_state.replan_count >= task_state.max_replan:
                task_state.goal_status = "blocked"
                task_state.next_action = "Replan exhausted"
            return task_state

        if data is None:
            logger.warning("[Replanner] JSON parse failed")
            if task_state.replan_count >= task_state.max_replan:
                task_state.goal_status = "blocked"
                task_state.next_action = "Replan failed (invalid JSON)"
            return task_state

        new_steps = data.get("plan_steps", [])
        completed_ids = set(task_state.completed_steps)
        merged_steps = [s for s in task_state.plan_steps if s["id"] in completed_ids]
        new_pending = []
        for step in new_steps:
            step.setdefault("status", "pending")
            step.setdefault("depends_on", [])
            if step["id"] not in completed_ids:
                merged_steps.append(step)
                new_pending.append(step["id"])

        task_state.plan_steps = merged_steps
        task_state.pending_steps = new_pending
        task_state.goal_status = "running"
        logger.info("[Replanner] merged plan: %d steps (%d completed, %d new)", len(merged_steps), len(completed_ids), len(new_pending))
        return task_state

    # ============================================================
    # Phase 5: Finalize
    # ============================================================

    async def _finalize(self, goal, task_state, context):
        """Compile final report."""
        logger.info("[Finalizer] compiling report from %d tool results", len(context.tool_results))
        report = self._compile_report(goal, task_state, context)
        task_state.final_report = report
        task_state.next_suggestions = self._extract_suggestions(task_state, context)
        task_state.goal_status = "completed"
        return task_state

    @staticmethod
    def _compile_report(goal, task_state, context):
        """Generate final report using unified ReportFormatter."""
        from app.application.copilot.report_formatter import format_report
        from app.tools.output_schema import normalize_tool_output

        outputs = []
        for tool_name in context.executed_tools:
            raw = context.tool_results.get(tool_name, {})
            outputs.append(normalize_tool_output(tool_name, raw))

        report = format_report(goal, outputs)

        plan_lines = ["\n\n---\n\n## Plan\n"]
        for step in task_state.plan_steps:
            icon = "OK" if step.get("status") == "done" else ("FAIL" if step.get("status") == "failed" else "...")
            plan_lines.append(f"- {icon} **{step.get('name', step.get('id', ''))}**")

        if task_state.verification_results:
            plan_lines.append("\n## Verification")
            for v in task_state.verification_results:
                icon = "OK" if v.get("passed") else "WARN"
                plan_lines.append(f"- {icon} {v.get('step_id', '')}: score={v.get('score', 0):.0f}")

        return report + "\n".join(plan_lines)

    @staticmethod
    def _extract_suggestions(task_state, context):
        """Extract follow-up suggestions from tool outputs."""
        suggestions = []
        for tool_name in context.executed_tools:
            data = context.tool_results.get(tool_name, {})
            analysis = data.get("analysis")
            if isinstance(analysis, dict):
                sug = analysis.get("suggestions") or analysis.get("recommendations") or []
                if isinstance(sug, list):
                    suggestions.extend(str(s) for s in sug)
        if not suggestions:
            suggestions = ["Review each module output for improvement areas"]
        return suggestions[:5]

    @staticmethod
    def _format_plan_for_display(task_state):
        """Format plan for frontend display."""
        lines = ["**Plan**:"]
        for i, step in enumerate(task_state.plan_steps, 1):
            name = step.get("name", step.get("id", f"Step {i}"))
            desc = step.get("description", "")
            tool = step.get("tool", "")
            line = f"{i}. **{name}**"
            if tool:
                line += f" (tool: {tool})"
            if desc:
                line += f" - {desc}"
            lines.append(line)
        if task_state.acceptance_criteria:
            lines.append("")
            lines.append("**Acceptance Criteria**:")
            for c in task_state.acceptance_criteria:
                lines.append(f"- {c}")
        return "\n".join(lines)

    # ============================================================
    # Helpers
    # ============================================================

    async def _init_task_state(self, goal, context, user_id, run_id):
        """Initialize or resume TaskState."""
        if run_id:
            run = await asyncio.to_thread(get_agent_run, run_id, user_id)
            if run:
                task_state = TaskState.from_dict(run)
                logger.info("[Orchestrator] resumed run_id=%d status=%s", run_id, task_state.goal_status)
                return task_state, run_id

        task_state = TaskState(goal=goal, goal_type="prepare", goal_status="created")
        run = await asyncio.to_thread(create_agent_run, goal=goal, goal_type="prepare", user_id=user_id, session_id=context.session_id)
        run_id = int(run["id"])
        logger.info("[Orchestrator] created run_id=%d", run_id)
        return task_state, run_id

    async def _persist(self, task_state, run_id, user_id):
        """Persist TaskState to DB."""
        await asyncio.to_thread(update_agent_run, run_id=run_id, user_id=user_id,
                                 status=task_state.goal_status, goal_type=task_state.goal_type,
                                 plan_steps=task_state.plan_steps, current_step=task_state.current_step,
                                 completed_steps=task_state.completed_steps, pending_steps=task_state.pending_steps,
                                 failed_steps=task_state.failed_steps, blockers=task_state.blockers,
                                 next_action=task_state.next_action, acceptance_criteria=task_state.acceptance_criteria,
                                 verification_results=task_state.verification_results, replan_count=task_state.replan_count,
                                 final_report=task_state.final_report, next_suggestions=task_state.next_suggestions)

    def _next_ready_step(self, task_state):
        """Get next step whose dependencies are met."""
        completed = set(task_state.completed_steps)
        for step_id in task_state.pending_steps:
            step = next((s for s in task_state.plan_steps if s["id"] == step_id), None)
            if step is None:
                continue
            depends = set(step.get("depends_on", []))
            if depends.issubset(completed):
                return step
        return None

    def _infer_goal_type(self, goal):
        """Infer task_type from goal text (兜底，与 intent.py 的 8 种对齐)。"""
        g = goal.lower()
        if any(kw in g for kw in ["compare", "vs", "versus", "对比", "比较"]):
            return "comparison"
        if any(kw in g for kw in ["optimize", "improve", "fix", "改", "优化"]):
            return "resume_optimization"
        if any(kw in g for kw in ["review", "retrospect", "复盘"]):
            return "review"
        if any(kw in g for kw in ["plan", "schedule", "week", "day", "计划"]):
            return "planning"
        if any(kw in g for kw in ["match", "匹配", "分析", "打分"]):
            return "match_analysis"
        if any(kw in g for kw in ["interview", "面试", "题", "出题"]):
            return "interview_prep"
        if any(kw in g for kw in ["search", "查", "搜索", "公开", "抓取"]):
            return "info_gathering"
        if any(kw in g for kw in ["full", "全面", "一条龙", "全套"]):
            return "full_prep"
        return "info_gathering"  # 默认开放信息收集

    @staticmethod
    def _extract_json(text):
        """Extract JSON object from LLM output."""
        if not text:
            return None
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return None
