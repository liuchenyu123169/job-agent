"""Copilot API — SSE 流式端点，实时推送 Pipeline 执行进度。

两种执行模式：
- 直通模式：resume_id + job_id 都已提供 → 跳过 LLM Planner，直接三步流水线
- ReAct 模式：未提供 ID → LLM Planner 自主探索
"""

import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from app.api.deps import get_current_user
from app.api.stream_utils import error_event, final_event, step_complete_event, step_start_event
from app.copilot.graph import copilot_graph
from app.copilot.state import PipelineContext, PipelineState
from app.copilot.summarizer import summarize_result
from app.db.crud import (
    create_copilot_session,
    get_copilot_session,
    list_copilot_sessions,
    update_copilot_session,
)
from app.schemas.agent_schema import CopilotRunRequest
from app.tools import tool_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/copilot", tags=["Copilot"])

@router.post("/run")
async def copilot_run(
    payload: CopilotRunRequest,
    current_user: dict = Depends(get_current_user),
):
    """运行 Copilot Pipeline，通过 SSE 流式返回执行进度和结果。"""
    user_id = int(current_user["id"])
    context = PipelineContext(resume_id=payload.resume_id, job_id=payload.job_id)
    use_fast = payload.resume_id is not None and payload.job_id is not None

    # 直通模式工具列表：优先用请求传入的，否则默认三步全跑
    fast_tools = payload.tools or ["match_analyze", "optimize_resume", "generate_interview_questions"]

    # 创建会话记录
    session = create_copilot_session(goal=payload.goal, user_id=user_id)
    session_id = int(session["id"])

    logger.info("[Copilot] mode=%s resume_id=%s job_id=%s tools=%s", "fast" if use_fast else "react", payload.resume_id, payload.job_id, fast_tools)

    generator = _fast_generator(context, user_id, session_id, fast_tools) if use_fast else _react_generator(context, user_id, session_id, payload.goal)

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


# ── 直通模式：跳过 LLM Planner，直接按工具列表顺序执行 ──

async def _fast_generator(
    context: PipelineContext,
    user_id: int,
    session_id: int,
    tools: list[str],
) -> AsyncGenerator[str, None]:
    """直通模式 SSE 生成器：按传入的工具列表顺序执行。"""
    try:
        for tool_name in tools:
            tool = tool_registry.get(tool_name)
            if tool is None:
                continue

            rid = context.resume_id
            jid = context.job_id
            yield step_start_event(tool_name, {"resume_id": rid, "job_id": jid})
            logger.info("[Copilot:fast] executing %s", tool_name)

            result = await tool.execute(resume_id=int(rid), job_id=int(jid), user_id=user_id)
            if result.success and result.data:
                context.record_result(tool_name, result.data)
                yield step_complete_event(tool_name, result.data)
            else:
                yield error_event(tool_name, result.error or "unknown error")

        report = summarize_result(context)  # 单次遍历，自动生成文本摘要
        yield final_event(summary=report["summary"], task_ids=report["task_ids"])

        update_copilot_session(
            session_id=session_id, status="COMPLETED",
            context_json=context.to_summary(),
            task_ids_json=report["task_ids"], summary_json=report, user_id=user_id,
        )

    except Exception as exc:
        logger.exception("[Copilot:fast] failed")
        update_copilot_session(
            session_id=session_id, status="ERROR",
            summary_json={"error": str(exc)}, user_id=user_id,
        )
        yield error_event("pipeline", str(exc))


# ── ReAct 模式：LLM Planner 自主决策 ──

async def _react_generator(
    context: PipelineContext,
    user_id: int,
    session_id: int,
    goal: str,
) -> AsyncGenerator[str, None]:
    """ReAct 模式 SSE 生成器：LLM Planner 逐步探索。"""
    current_tool: str | None = None
    final_messages: list = []

    initial_state: PipelineState = {
        "messages": [HumanMessage(content=goal)],
        "context": context,
        "user_id": user_id,
    }

    try:
        async for chunk in copilot_graph.astream(
            initial_state,
            config={"recursion_limit": 50},
        ):
            for node_name, node_state in chunk.items():
                if node_name == "agent":
                    final_messages = node_state.get("messages", [])
                    if final_messages:
                        last_msg = final_messages[-1]
                        if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
                            for tc in last_msg.tool_calls:
                                current_tool = tc.get("name", "")
                                yield step_start_event(current_tool, tc.get("args", {}))

                elif node_name == "tools":
                    ctx: PipelineContext = node_state.get("context", context)
                    if current_tool and current_tool in ctx.tool_results:
                        yield step_complete_event(current_tool, ctx.tool_results.get(current_tool, {}))

        final_text = ""
        for msg in reversed(final_messages):
            if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                final_text = str(msg.content or "")
                break

        report = summarize_result(context, final_message=final_text)
        yield final_event(summary=report["summary"], task_ids=report["task_ids"])

        update_copilot_session(
            session_id=session_id, status="COMPLETED",
            context_json=context.to_summary(),
            task_ids_json=report["task_ids"], summary_json=report, user_id=user_id,
        )

    except Exception as exc:
        logger.exception("[Copilot:react] failed")
        update_copilot_session(
            session_id=session_id, status="ERROR",
            summary_json={"error": str(exc)}, user_id=user_id,
        )
        yield error_event(current_tool or "pipeline", str(exc))


# ── 会话查询 ──

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
        raise HTTPException(status_code=404, detail="Session not found")
    return session


# ── 工具发现 ──

@router.get("/tools")
def list_tools() -> list[dict]:
    """返回所有已注册工具的元数据（name / description / keywords / render_type）。

    前端可用此接口动态发现工具，无需硬编码工具列表。
    """
    return [t.to_api_dict() for t in tool_registry.list_all()]
