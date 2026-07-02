"""Copilot API — SSE 流式端点，实时推送 Pipeline 执行进度。

路由规则 (Phase 2):
- classify_intent() 分类用户意图 → IntentResult
- fixed intent → _direct_tools（固定工具链，零 LLM 路由）
- open intent / 无匹配 → ClosedLoopOrchestrator.run_stream()

多轮对话：通过 session_id 续接已有会话，自动加载历史消息。
"""

import asyncio
import json
import logging
import queue
import re
import time
from typing import AsyncGenerator

_URL_RE = re.compile(r"https?://[^\s,，。；;]+")

_REPORT_MARKER = "__COPILOT_REPORT__"

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from app.api.deps import get_current_user
from app.shared.observability import metrics
from app.shared.observability.route_tracer import trace_route
from app.shared.stream_utils import error_event, final_event, sse_event, step_complete_event, step_start_event, step_token_event
from app.application.copilot.conversation import conversation_manager
from app.shared.state import PipelineContext, PipelineState
from app.application.copilot.summarizer import summarize_result
from app.application.orchestrator import ClosedLoopOrchestrator
from app.infrastructure.db.crud import (
    create_copilot_session,
    get_conversation_messages,
    get_copilot_session,
    list_copilot_sessions,
    update_copilot_session,
)
from app.shared.schemas.agent_schema import CopilotRunRequest
from app.ai.skills.intent import classify_intent, IntentResult
from app.ai.skills.registry import skill_registry
from app.tools import tool_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/copilot", tags=["Copilot"])


@router.post("/run")
async def copilot_run(
    payload: CopilotRunRequest,
    current_user: dict = Depends(get_current_user),
):
    """运行 Copilot Pipeline，通过 SSE 流式返回执行进度和结果。

    路由规则:
    - Skill 命中 + mode=workflow → _direct_tools（固定工具链，零 LLM 路由）
    - 其余全部 → ClosedLoopOrchestrator.run_stream（开放任务，plan→execute→verify）
    """
    user_id = int(current_user["id"])

    # ── URL 提取：从 goal 中识别链接，写入 external_urls ──
    external_urls = _URL_RE.findall(payload.goal or "")

    context = PipelineContext(
        resume_id=payload.resume_id,
        job_id=payload.job_id,
        personal_info=payload.personal_info,
        goal=payload.goal,
        extra_context_text=payload.extra_context or "",
        external_urls=external_urls,
    )

    # ── 会话管理：加载历史或创建新会话 ──
    history_messages: list = []

    if payload.session_id:
        session = get_copilot_session(payload.session_id, user_id=user_id)
        if session is None:
            logger.warning(
                "[Copilot] stale session_id=%s for user=%d, auto-creating new session",
                payload.session_id, user_id,
            )
            session = create_copilot_session(goal=payload.goal, user_id=user_id)
            session_id = int(session["id"])
            context.session_id = session_id
        else:
            session_id = payload.session_id
            context.session_id = session_id
            context.messages_summary = session.get("messages_summary")
            history_messages = conversation_manager.load_history(session_id, user_id, system_prompt="")
            logger.info("[Copilot] resume session=%d, %d history messages", session_id, len(history_messages))
    else:
        session = create_copilot_session(goal=payload.goal, user_id=user_id)
        session_id = int(session["id"])
        context.session_id = session_id

    # ── 路由决策 (Phase 2: classify_intent + task_classifier) ──
    _t0 = time.monotonic()
    skills = skill_registry.match_all(payload.goal)
    intent = await classify_intent(
        payload.goal, skills,
        external_urls=context.external_urls,
        job_id=context.job_id,
        extra_context_text=context.extra_context_text,
    )

    # Phase 2 Round A: 注入任务分类到上下文
    context.task_type = intent.task_type
    context.expected_output_shape = intent.expected_output_shape
    context.execution_mode = intent.execution_mode

    # 结构化路由追踪日志（回答"为什么走这条路"）
    trace_route(
        session_id=session_id,
        user_id=user_id,
        goal=payload.goal,
        intent_result=intent,
        duration_ms=(time.monotonic() - _t0) * 1000,
    )

    if intent.route == "direct_tools":
        logger.info(
            "[Copilot:route] %s task_type=%s source=%s skills=%s tools=%s",
            intent.route, intent.task_type, intent.decision_source,
            intent.matched_skills, intent.tools,
        )
        generator = _direct_tools(context, user_id, session_id, intent)
    else:
        logger.info(
            "[Copilot:route] %s task_type=%s source=%s skills=%s rationale=%s",
            intent.route, intent.task_type, intent.decision_source,
            intent.matched_skills, intent.rationale[:80],
        )
        orchestrator = ClosedLoopOrchestrator()
        generator = orchestrator.run_stream(
            payload.goal, context, user_id,
            intent=intent,
        )

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Session-Id": str(session_id),
        },
    )


def _save_report(session_id, user_id, report, preexisting_messages=None, goal=None):
    """将报告序列化并存入 conversation_messages，供前端恢复 step card。"""
    messages = list(preexisting_messages) if preexisting_messages else []
    if goal:
        messages.insert(0, HumanMessage(content=goal))
    report_json = json.dumps(report, ensure_ascii=False)
    messages.append(AIMessage(content=_REPORT_MARKER + report_json))
    conversation_manager.save_messages(session_id, user_id, messages)


def _summarize_node_state(node_name: str, state: dict) -> str:
    """从节点状态提取一行可读摘要（供 step_progress SSE 事件使用）。"""
    if state.get("error_msg"):
        return f"出错: {state['error_msg'][:60]}"
    if node_name.startswith("llm"):
        return "LLM 分析中..."
    if node_name.startswith("save"):
        return "保存结果..."
    if node_name.startswith("load"):
        return "加载数据..."
    if node_name.startswith("build"):
        return "构建提示词..."
    if node_name.startswith("parse"):
        return "解析结果..."
    if node_name.startswith("retrieve"):
        return f"检索知识库... (命中{state.get('knowledge_count', 0)}条)"
    if node_name.startswith("run_match"):
        return "匹配分析中..."
    if node_name.startswith("run_optimize"):
        return "简历优化中..."
    if node_name.startswith("run_search"):
        return "岗位搜索中..."
    return "执行中..."


# ═══════════════════════════════════════════════════════════════
# 路径 1b: 意图明确但 Skill 配置的是 tools 而非 sub_agents
# ── 工具名 → 特殊参数注入规则 ──
# 基础参数 (resume_id / job_id / user_id / personal_info) 总是传入。
# 下面定义哪些工具需要从 PipelineContext 中额外提取特定参数。
_TOOL_PARAM_INJECTION: dict[str, dict] = {
    "public_search":     {"query": "goal"},       # context.goal → query
    "fetch_job_page":    {"url": "external_urls[0]"},  # context.external_urls[0] → url
    "search_knowledge":  {"query": "goal"},
}


def _build_tool_params(
    tool_name: str,
    tool: "ToolDefinition",
    context: PipelineContext,
    user_id: int,
) -> tuple[dict, str | None]:
    """构建工具执行参数。返回 (params, error_msg)。

    优先级链:
    1. 固定基础: user_id, resume_id, job_id, personal_info
    2. 工具名显式映射 (query / url 等)
    3. Schema 默认值补全 (top_k, enable_rag 等)
    4. 缺参检查: schema required 字段未满足 → 返回 error_msg
    """
    rid = context.resume_id
    jid = context.job_id

    params: dict = {
        "user_id": user_id,
        "resume_id": int(rid or 0),
        "job_id": int(jid or 0),
        "personal_info": context.personal_info or "",
    }

    # ── 工具名显式映射 ──
    injection = _TOOL_PARAM_INJECTION.get(tool_name, {})
    for param_name, context_attr in injection.items():
        if context_attr == "goal":
            params[param_name] = context.goal or ""
        elif context_attr == "external_urls[0]":
            urls = context.external_urls
            params[param_name] = urls[0] if urls else ""

    # ── Schema 默认值补全 ──
    schema_props = tool.parameters.get("properties", {})
    for prop_name, prop_schema in schema_props.items():
        if prop_name not in params and "default" in prop_schema:
            params[prop_name] = prop_schema["default"]

    # ── 缺参检查 ──
    required = tool.parameters.get("required", [])
    for req_param in required:
        val = params.get(req_param)
        if val is None or (isinstance(val, str) and not val.strip()):
            return {}, f"缺少必要参数: {req_param} (工具 {tool_name} 需要此参数，但上下文未提供)"

    # 预检查 InputRequirements
    missing = []
    if tool.input_requirements.resume_id and not rid:
        missing.append("resume")
    if tool.input_requirements.job_id and not jid:
        missing.append("job")
    if missing:
        return {}, f"缺少必要输入: {', '.join(missing)}，请先在左侧面板中选择"

    return params, None


async def _direct_tools(
    context: PipelineContext,
    user_id: int,
    session_id: int,
    intent: "IntentResult",
) -> AsyncGenerator[str, None]:
    """直接按 IntentResult 中的 tools 列表顺序执行原子工具。

    Phase 2 Round A: 接收完整 IntentResult，注入 task_type/expected_output_shape。

    支持 LLM token 级流式推送：通过 ContextVar 捕获工具内部 LLM 调用产生的 token。
    """
    from app.application.workflows.common import _token_callback

    tools = intent.tools
    success_count = 0
    failed_tools: list[str] = []

    # ── 防御：空工具列表直接报错，不标记 COMPLETED ──
    if not tools:
        logger.error(
            "[Copilot:tools] direct_tools route with empty tools list. "
            "task_type=%s intent_type=%s matched_skills=%s",
            intent.task_type, intent.intent_type, intent.matched_skills,
        )
        yield error_event(
            "orchestrator",
            "系统未能匹配到可执行工具。请尝试更具体地描述需求，如'帮我优化简历中的项目经历'。",
        )
        yield final_event(
            "未能执行任何工具 — 请提供更具体的输入后重试",
            context.task_ids, context.session_id,
        )
        metrics.record_tool_error("_empty_tools")
        return

    try:
        for tool_name in tools:
            tool = tool_registry.get(tool_name)
            if tool is None:
                logger.warning("[Copilot:tools] unknown tool '%s' in skill config", tool_name)
                yield error_event(tool_name, f"未知的工具: {tool_name}")
                failed_tools.append(tool_name)
                continue

            # ── 构建参数 ──
            params, param_err = _build_tool_params(tool_name, tool, context, user_id)
            if param_err:
                logger.warning("[Copilot:tools] %s param error: %s", tool_name, param_err)
                yield error_event(tool_name, param_err)
                metrics.record_tool_error(tool_name)
                failed_tools.append(tool_name)
                continue

            yield step_start_event(tool_name, {
                "resume_id": context.resume_id,
                "job_id": context.job_id,
            })
            logger.info("[Copilot:tools] executing %s params=%s", tool_name,
                         {k: v for k, v in params.items() if k not in ("personal_info",)})

            # ── Token 级流式推送 ──
            token_q: asyncio.Queue = asyncio.Queue(maxsize=256)

            def _on_token(t: str) -> None:
                try:
                    token_q.put_nowait(t)
                except asyncio.QueueFull:
                    pass

            token_token = _token_callback.set(_on_token)
            try:
                exec_task = asyncio.create_task(tool.execute(**params))

                # 在工具执行期间持续排空 token 队列
                while not exec_task.done():
                    tokens: list[str] = []
                    while True:
                        try:
                            tokens.append(token_q.get_nowait())
                        except asyncio.QueueEmpty:
                            break
                    if tokens:
                        yield step_token_event(tool_name, "".join(tokens))
                    else:
                        await asyncio.sleep(0.03)

                # 排空残留 token
                tail: list[str] = []
                while True:
                    try:
                        tail.append(token_q.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                if tail:
                    yield step_token_event(tool_name, "".join(tail))

                result = await exec_task
            finally:
                _token_callback.reset(token_token)

            if result.success and result.data:
                context.record_result(
                    tool_name,
                    result.data,
                    step_id=tool_name,
                    step_name=tool_name,
                    source_query=str(params.get("query", "")),
                )
                yield step_complete_event(tool_name, result.data)
                success_count += 1
            else:
                err_msg = result.error or "unknown error"
                yield error_event(tool_name, err_msg)
                metrics.record_tool_error(tool_name)
                failed_tools.append(tool_name)

        # ── 完成态判断 ──
        total = len(tools)
        if success_count == total:
            status = "COMPLETED"
        elif success_count > 0:
            status = "PARTIAL"
        else:
            status = "ERROR"

        report = summarize_result(context)
        report["session_id"] = session_id
        report["failed_tools"] = list(failed_tools)

        # 部分失败时在 summary 中明确标注
        if failed_tools and success_count > 0:
            failed_note = f"\n\n> ⚠️ 部分步骤失败: {', '.join(failed_tools)}"
            report["summary"] = (report.get("summary") or "") + failed_note

        _save_report(session_id, user_id, report, goal=context.goal)
        yield final_event(
            summary=report["summary"],
            task_ids=report["task_ids"],
            session_id=session_id,
            failed_tools=list(failed_tools) if failed_tools else None,
            status=status,
        )

        update_copilot_session(
            session_id=session_id,
            status=status,
            context_json=context.to_summary(),
            task_ids_json=report["task_ids"],
            summary_json=report,
            user_id=user_id,
        )

    except Exception as exc:
        logger.exception("[Copilot:tools] fatal exception")
        update_copilot_session(
            session_id=session_id, status="ERROR",
            summary_json={"error": str(exc)}, user_id=user_id,
        )
        yield error_event("pipeline", str(exc))


# ═══════════════════════════════════════════════════════════════
# 会话查询 + 工具/Skill 发现
# ═══════════════════════════════════════════════════════════════

@router.get("/sessions")
def list_sessions(
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """列出当前用户的 Copilot 会话历史。"""
    return list_copilot_sessions(user_id=int(current_user["id"]), limit=limit)


@router.get("/sessions/{session_id}")
def get_session(
    session_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """查询单个 Copilot 会话的详情。"""
    user_id = int(current_user["id"])
    session = get_copilot_session(session_id, user_id=user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话未找到")
    return session


@router.get("/tools")
def list_tools() -> list[dict]:
    """返回所有已注册工具的元数据。"""
    return [t.to_api_dict() for t in tool_registry.list_all()]


@router.get("/skills")
def list_skills() -> list[dict]:
    """返回所有 Agent Skill 的元数据。"""
    return skill_registry.to_api_list()


@router.get("/sessions/{session_id}/messages")
def get_session_messages(
    session_id: int,
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """返回指定会话的所有对话消息（用于前端恢复聊天记录）。

    返回格式：[{role, content, created_at}, ...]
    role 使用前端约定：'user' | 'copilot' | 'tool'
    """
    user_id = int(current_user["id"])
    session = get_copilot_session(session_id, user_id=user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话未找到")
    rows = get_conversation_messages(session_id, user_id)
    result: list[dict] = []
    for row in rows:
        db_role = str(row.get("role") or "")
        # 跳过中间消息：tool 调用、tool 结果、系统提示词
        if db_role in ("tool", "system"):
            continue
        if db_role == "assistant" and row.get("tool_calls_json"):
            # 这是 LLM 决定调用工具时的中间消息，不是给用户看的最终回复
            continue
        # 映射 DB role → 前端 role
        frontend_role = {
            "user": "user",
            "assistant": "copilot",
            "ai": "copilot",
        }.get(db_role, "copilot")
        content = str(row.get("content") or "")
        if not content.strip():
            continue
        result.append({
            "role": frontend_role,
            "content": content,
            "created_at": str(row.get("created_at") or ""),
            "tool_name": row.get("tool_name"),
        })
    return result


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """删除会话及其所有消息。"""
    user_id = int(current_user["id"])
    session = get_copilot_session(session_id, user_id=user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话未找到")
    deleted = conversation_manager.clear_session(session_id, user_id)
    update_copilot_session(
        session_id=session_id, status="ARCHIVED", user_id=user_id,
    )
    return {"session_id": session_id, "deleted_messages": deleted}
