"""Copilot API — SSE 流式端点，实时推送 Pipeline 执行进度。

两种执行路径（后端 Skill 匹配自动选择）：
- 意图明确 (Skill 命中) → 直接跑子 Agent pipeline，跳过 Coordinator LLM
- 意图模糊 (Skill 未命中) → Coordinator LLM 推理委派
"""

import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from app.agents import (
    create_coordinator_graph,
    interview_agent,
    resume_agent,
    search_agent,
)
from app.api.deps import get_current_user
from app.api.stream_utils import error_event, final_event, step_complete_event, step_start_event
from app.copilot.state import PipelineContext, PipelineState
from app.copilot.summarizer import summarize_result
from app.db.crud import (
    create_copilot_session,
    get_copilot_session,
    list_copilot_sessions,
    update_copilot_session,
)
from app.schemas.agent_schema import CopilotRunRequest
from app.skills.registry import skill_registry
from app.tools import tool_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/copilot", tags=["Copilot"])

# 子 Agent 名称 → 实例映射
_AGENT_MAP = {
    "resume_agent": resume_agent,
    "interview_agent": interview_agent,
    "search_agent": search_agent,
}

# Coordinator graph 单例（意图模糊时的 fallback）
_COORDINATOR_GRAPH = create_coordinator_graph([resume_agent, interview_agent, search_agent])


@router.post("/run")
async def copilot_run(
    payload: CopilotRunRequest,
    current_user: dict = Depends(get_current_user),
):
    """运行 Copilot Pipeline，通过 SSE 流式返回执行进度和结果。

    后端根据 Skill 匹配自动选择路径：
    - 命中 → 直接跑子 Agent pipeline（零路由延迟）
    - 未命中 → Coordinator LLM 推理委派
    """
    user_id = int(current_user["id"])
    context = PipelineContext(resume_id=payload.resume_id, job_id=payload.job_id)

    session = create_copilot_session(goal=payload.goal, user_id=user_id)
    session_id = int(session["id"])

    # ── 后端 Skill 匹配：决定走哪条路径 ──
    skills = skill_registry.match_all(payload.goal)

    if skills:
        # 合并所有命中 Skill 的 sub_agents，去重
        sub_agent_names = _merge_agents(skills)
        tools = _merge_tools(skills)
        logger.info("[Copilot] skills=%s agents=%s tools=%s",
                     [s.name for s in skills], sub_agent_names, tools)

        if sub_agent_names:
            generator = _direct_agents(context, user_id, session_id, sub_agent_names)
        elif tools:
            generator = _direct_tools(context, user_id, session_id, tools)
        else:
            generator = _coordinator_generator(context, user_id, session_id, payload.goal)
    else:
        logger.info("[Copilot] no skill matched, fallback to coordinator")
        generator = _coordinator_generator(context, user_id, session_id, payload.goal)

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


def _merge_agents(skills) -> list[str]:
    """从 Skill 列表中提取 sub_agents，去重保序。"""
    seen = set()
    result = []
    for s in skills:
        for name in (s.sub_agents or []):
            if name not in seen:
                seen.add(name)
                result.append(name)
    return result


def _merge_tools(skills) -> list[str]:
    """从 Skill 列表中提取 tools（fast 模式的工具名），去重保序。"""
    seen = set()
    result = []
    for s in skills:
        for name in (s.tools or []):
            if name not in seen:
                seen.add(name)
                result.append(name)
    return result


# ═══════════════════════════════════════════════════════════════
# 路径 1: 意图明确 → 直接跑子 Agent，零 LLM 路由
# ═══════════════════════════════════════════════════════════════

async def _direct_agents(
    context: PipelineContext,
    user_id: int,
    session_id: int,
    agent_names: list[str],
) -> AsyncGenerator[str, None]:
    """直接按顺序执行子 Agent，跳过 Coordinator LLM。

    每个子 Agent 内部运行自己的 pipeline。适合意图明确的场景。
    """
    try:
        for name in agent_names:
            agent = _AGENT_MAP.get(name)
            if agent is None:
                yield error_event(name, f"未知的子 Agent: {name}")
                continue

            yield step_start_event(name, {
                "resume_id": context.resume_id,
                "job_id": context.job_id,
            })
            logger.info("[Copilot:direct] executing %s", name)

            result = agent.run(
                goal=f"执行 {name}",
                resume_id=int(context.resume_id or 0),
                job_id=int(context.job_id or 0),
                user_id=user_id,
            )
            if result["success"] and result.get("data"):
                context.record_result(name, result["data"])
                yield step_complete_event(name, result["data"])
            else:
                yield error_event(name, result.get("error") or "unknown error")

        report = summarize_result(context)
        yield final_event(summary=report["summary"], task_ids=report["task_ids"])

        update_copilot_session(
            session_id=session_id, status="COMPLETED",
            context_json=context.to_summary(),
            task_ids_json=report["task_ids"], summary_json=report, user_id=user_id,
        )

    except Exception as exc:
        logger.exception("[Copilot:direct] failed")
        update_copilot_session(
            session_id=session_id, status="ERROR",
            summary_json={"error": str(exc)}, user_id=user_id,
        )
        yield error_event("pipeline", str(exc))


# ═══════════════════════════════════════════════════════════════
# 路径 1b: 意图明确但 Skill 配置的是 tools 而非 sub_agents
# ═══════════════════════════════════════════════════════════════

async def _direct_tools(
    context: PipelineContext,
    user_id: int,
    session_id: int,
    tools: list[str],
) -> AsyncGenerator[str, None]:
    """直接按 tools 列表顺序执行原子工具（兼容 fast 模式）。"""
    try:
        for tool_name in tools:
            tool = tool_registry.get(tool_name)
            if tool is None:
                continue

            rid = context.resume_id
            jid = context.job_id
            yield step_start_event(tool_name, {"resume_id": rid, "job_id": jid})
            logger.info("[Copilot:tools] executing %s", tool_name)

            result = await tool.execute(resume_id=int(rid or 0), job_id=int(jid or 0), user_id=user_id)
            if result.success and result.data:
                context.record_result(tool_name, result.data)
                yield step_complete_event(tool_name, result.data)
            else:
                yield error_event(tool_name, result.error or "unknown error")

        report = summarize_result(context)
        yield final_event(summary=report["summary"], task_ids=report["task_ids"])

        update_copilot_session(
            session_id=session_id, status="COMPLETED",
            context_json=context.to_summary(),
            task_ids_json=report["task_ids"], summary_json=report, user_id=user_id,
        )

    except Exception as exc:
        logger.exception("[Copilot:tools] failed")
        update_copilot_session(
            session_id=session_id, status="ERROR",
            summary_json={"error": str(exc)}, user_id=user_id,
        )
        yield error_event("pipeline", str(exc))


# ═══════════════════════════════════════════════════════════════
# 路径 2: 意图模糊 → Coordinator LLM 推理委派
# ═══════════════════════════════════════════════════════════════

async def _coordinator_generator(
    context: PipelineContext,
    user_id: int,
    session_id: int,
    goal: str,
) -> AsyncGenerator[str, None]:
    """Coordinator SSE 生成器：委派子 Agent，流式推送进度。"""
    current_tool: str | None = None
    final_messages: list = []

    initial_state: PipelineState = {
        "messages": [HumanMessage(content=goal)],
        "context": context,
        "user_id": user_id,
    }

    try:
        async for chunk in _COORDINATOR_GRAPH.astream(
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
        logger.exception("[Copilot:coordinator] failed")
        update_copilot_session(
            session_id=session_id, status="ERROR",
            summary_json={"error": str(exc)}, user_id=user_id,
        )
        yield error_event(current_tool or "coordinator", str(exc))


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
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/tools")
def list_tools() -> list[dict]:
    """返回所有已注册工具的元数据。"""
    return [t.to_api_dict() for t in tool_registry.list_all()]


@router.get("/skills")
def list_skills() -> list[dict]:
    """返回所有 Agent Skill 的元数据。"""
    return skill_registry.to_api_list()
