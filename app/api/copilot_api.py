"""Copilot API — SSE 流式端点，实时推送 Pipeline 执行进度。

两种执行路径（后端 Skill 匹配自动选择）：
- 意图明确 (Skill 命中) → 直接跑子 Agent pipeline，跳过 Coordinator LLM
- 意图模糊 (Skill 未命中) → Coordinator LLM 推理委派

多轮对话：通过 session_id 续接已有会话，自动加载历史消息。
"""

import asyncio
import json
import logging
import queue  # 线程安全队列（asyncio.Queue 不跨线程安全）
from typing import AsyncGenerator

_REPORT_MARKER = "__COPILOT_REPORT__"

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
from app.api.stream_utils import error_event, final_event, sse_event, step_complete_event, step_start_event, step_token_event
from app.copilot.conversation import conversation_manager
from app.copilot.state import PipelineContext, PipelineState
from app.copilot.summarizer import summarize_result
from app.db.crud import (
    create_copilot_session,
    get_conversation_messages,
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

    多轮对话：传 session_id 续接已有会话，自动加载历史消息。
    """
    user_id = int(current_user["id"])
    context = PipelineContext(
        resume_id=payload.resume_id,
        job_id=payload.job_id,
        personal_info=payload.personal_info,
        goal=payload.goal,
    )

    # ── 会话管理：加载历史或创建新会话 ──
    history_messages: list = []

    if payload.session_id:
        session = get_copilot_session(payload.session_id, user_id=user_id)
        if session is None:
            # 会话已被删除或数据库重建 → 静默降级为新建，前端在响应头 X-Session-Id 拿到新 ID
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

            # 加载历史消息（Coordinator 路径使用）
            history_messages = conversation_manager.load_history(session_id, user_id, system_prompt="")
            logger.info("[Copilot] resume session=%d, %d history messages", session_id, len(history_messages))
    else:
        session = create_copilot_session(goal=payload.goal, user_id=user_id)
        session_id = int(session["id"])
        context.session_id = session_id

    # ── 后端 Skill 匹配：决定走哪条路径 ──
    skills = skill_registry.match_all(payload.goal)

    if skills:
        sub_agent_names = _merge_agents(skills)
        tools = _merge_tools(skills)
        logger.info("[Copilot] skills=%s agents=%s tools=%s",
                     [s.name for s in skills], sub_agent_names, tools)

        if sub_agent_names:
            generator = _direct_agents(context, user_id, session_id, sub_agent_names)
        elif tools:
            generator = _direct_tools(context, user_id, session_id, tools)
        else:
            generator = _coordinator_generator(context, user_id, session_id, payload.goal, history_messages)
    else:
        logger.info("[Copilot] no skill matched, fallback to coordinator")
        generator = _coordinator_generator(context, user_id, session_id, payload.goal, history_messages)

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
            logger.info("[Copilot:direct] streaming %s", name)

            # 双队列：progress（节点进度）+ token（LLM 逐字输出）
            progress_q: queue.Queue = queue.Queue()
            token_q: queue.Queue = queue.Queue()

            def on_step(node_name: str, duration_ms: float) -> None:
                progress_q.put(("step", node_name, duration_ms))

            def on_token(t: str) -> None:
                token_q.put(t)

            task = asyncio.create_task(agent.run_stream_async(
                goal=f"执行 {name}",
                resume_id=int(context.resume_id or 0),
                job_id=int(context.job_id or 0),
                user_id=user_id,
                on_step=on_step,
                on_token=on_token,
            ))

            loop = asyncio.get_running_loop()

            # 合并排水：一次取空两队列，批量发 token 减少 SSE 事件量
            def _drain_all() -> tuple[list[tuple[str, str, float]], list[str]]:
                steps: list[tuple[str, str, float]] = []
                tokens: list[str] = []
                while True:
                    try:
                        steps.append(progress_q.get_nowait())
                    except queue.Empty:
                        break
                while True:
                    try:
                        tokens.append(token_q.get_nowait())
                    except queue.Empty:
                        break
                return steps, tokens

            while not task.done():
                steps, tokens = await loop.run_in_executor(None, _drain_all)
                # 发进度事件
                for _, node_name, duration_ms in steps:
                    yield sse_event("step_progress", {
                        "agent": name,
                        "node": node_name,
                        "duration_ms": duration_ms,
                        "state_summary": _summarize_node_state(node_name, {}),
                    })
                # 发 token 事件（批量合并成一段）
                if tokens:
                    yield step_token_event(name, "".join(tokens))

                # 空队列时短暂 sleep，避免忙等
                if not steps and not tokens:
                    await asyncio.sleep(0.05)

            result = await task

            # task 完成后清空残留
            steps, tokens = await loop.run_in_executor(None, _drain_all)
            for _, node_name, duration_ms in steps:
                yield sse_event("step_progress", {
                    "agent": name,
                    "node": node_name,
                    "duration_ms": duration_ms,
                    "state_summary": _summarize_node_state(node_name, {}),
                })
            if tokens:
                yield step_token_event(name, "".join(tokens))

            if result["success"] and result.get("data"):
                context.record_result(name, result["data"])
                yield step_complete_event(name, result["data"])
            else:
                yield error_event(name, result.get("error") or "unknown error")

        report = summarize_result(context)
        report["session_id"] = session_id
        _save_report(session_id, user_id, report, goal=context.goal)
        yield final_event(summary=report["summary"], task_ids=report["task_ids"], session_id=session_id)

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
                logger.warning("[Copilot:tools] unknown tool '%s' in skill config", tool_name)
                yield error_event(tool_name, f"未知的工具: {tool_name}")
                continue

            rid = context.resume_id
            jid = context.job_id
            yield step_start_event(tool_name, {"resume_id": rid, "job_id": jid})
            logger.info("[Copilot:tools] executing %s", tool_name)

            result = await tool.execute(
                resume_id=int(rid or 0),
                job_id=int(jid or 0),
                user_id=user_id,
                personal_info=context.personal_info or "",
            )
            if result.success and result.data:
                context.record_result(tool_name, result.data)
                yield step_complete_event(tool_name, result.data)
            else:
                yield error_event(tool_name, result.error or "unknown error")

        report = summarize_result(context)
        report["session_id"] = session_id
        _save_report(session_id, user_id, report, goal=context.goal)
        yield final_event(summary=report["summary"], task_ids=report["task_ids"], session_id=session_id)

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
    history_messages: list | None = None,
) -> AsyncGenerator[str, None]:
    """Coordinator SSE 生成器：委派子 Agent，流式推送进度。

    支持多轮对话：传入 history_messages 则从历史消息恢复上下文。
    """
    current_tool: str | None = None
    final_messages: list = []

    # 构建初始消息列表：历史消息 + 当前用户消息
    if history_messages:
        messages = list(history_messages)
        messages.append(HumanMessage(content=goal))
        # 管理上下文窗口
        messages, summary = conversation_manager.manage_window(messages)
        if summary:
            context.messages_summary = summary
    else:
        messages = [HumanMessage(content=goal)]

    initial_state: PipelineState = {
        "messages": messages,
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

        # 保存本轮消息到 DB（ReAct 对话 + 结构化报告）
        report = summarize_result(context, final_message=final_text)
        report["session_id"] = session_id
        _save_report(session_id, user_id, report, preexisting_messages=final_messages)
        if context.messages_summary:
            conversation_manager.save_summary(session_id, user_id, context.messages_summary)
        yield final_event(summary=report["summary"], task_ids=report["task_ids"], session_id=session_id)

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
        # 映射 DB role → 前端 role
        frontend_role = {
            "user": "user",
            "assistant": "copilot",
            "ai": "copilot",
            "tool": "tool",
            "system": "copilot",
        }.get(db_role, "copilot")
        result.append({
            "role": frontend_role,
            "content": str(row.get("content") or ""),
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
