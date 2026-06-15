"""Copilot API — SSE 流式端点，实时推送 Pipeline 执行进度。"""

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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/copilot", tags=["Copilot"])


@router.post("/run")
async def copilot_run(
    payload: CopilotRunRequest,
    current_user: dict = Depends(get_current_user),
):
    """运行 Copilot Pipeline，通过 SSE 流式返回执行进度和结果。"""
    user_id = int(current_user["id"])

    # 构建初始状态
    context = PipelineContext(
        resume_id=payload.resume_id,
        job_id=payload.job_id,
    )
    initial_state: PipelineState = {
        "messages": [HumanMessage(content=payload.goal)],
        "context": context,
        "user_id": user_id,
    }

    async def event_generator() -> AsyncGenerator[str, None]:
        """SSE 事件生成器 — 从 LangGraph astream 事件转为 SSE。"""
        current_tool: str | None = None
        final_messages: list = []

        try:
            # 使用 astream 逐步获取每个节点的状态变更
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
                            yield step_complete_event(
                                current_tool,
                                ctx.tool_results.get(current_tool, {}),
                            )

            # 循环结束，生成最终报告
            logger.info("[Copilot] Pipeline 执行完毕, tasks=%s", context.task_ids)

            # 从最终状态提取 LLM 回复
            final_text = ""
            for msg in reversed(final_messages):
                if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                    final_text = str(msg.content or "")
                    break

            report = summarize_result(context, final_message=final_text)
            yield final_event(
                summary=report["summary"],
                task_ids=report["task_ids"],
            )

            # 更新会话记录为完成状态
            update_copilot_session(
                session_id=session_id,
                status="COMPLETED",
                context_json=context.to_summary(),
                task_ids_json=report["task_ids"],
                summary_json=report,
                user_id=user_id,
            )

        except Exception as exc:
            logger.exception("[Copilot] Pipeline 异常")
            update_copilot_session(
                session_id=session_id,
                status="ERROR",
                summary_json={"error": str(exc)},
                user_id=user_id,
            )
            yield error_event(current_tool or "pipeline", str(exc))

    # 创建会话记录
    session = create_copilot_session(goal=payload.goal, user_id=user_id)
    session_id = int(session["id"])

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
            "X-Session-Id": str(session_id),  # 返回会话 ID 便于后续查询
        },
    )


@router.get("/sessions")
def list_sessions(
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """列出当前用户的 Copilot 会话历史。"""
    user_id = int(current_user["id"])
    return list_copilot_sessions(user_id=user_id, limit=limit)


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
