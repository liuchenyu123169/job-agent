"""SSE 事件推送工具 — Server-Sent Events 格式化输出。"""

import json
from typing import Any


def sse_event(event: str, data: dict[str, Any]) -> str:
    """将事件名和数据格式化为 SSE 协议字符串。

    SSE 格式规范:
        event: <事件名>
        data: <JSON 数据>
        (空行分隔)

    Args:
        event: 事件类型（plan / step_start / step_complete / error / final）
        data: 事件携带的数据

    Returns:
        符合 SSE 协议的消息字符串
    """
    inner = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {inner}\n\n"


# ── 常用事件构造函数 ──

def plan_event(steps: list[str]) -> str:
    """执行计划事件。"""
    return sse_event("plan", {"steps": steps})


def step_start_event(tool_name: str, args: dict[str, Any]) -> str:
    """工具开始执行事件。"""
    return sse_event("step_start", {"tool": tool_name, "args": args})


def step_complete_event(tool_name: str, result_summary: dict[str, Any]) -> str:
    """工具执行完毕事件。"""
    return sse_event("step_complete", {"tool": tool_name, "result": result_summary})


def error_event(tool_name: str, error: str) -> str:
    """错误事件。"""
    return sse_event("error", {"tool": tool_name, "error": error})


def final_event(summary: str, task_ids: list[int], session_id: int | None = None) -> str:
    """全部完成事件。"""
    data: dict[str, Any] = {"summary": summary, "task_ids": task_ids}
    if session_id is not None:
        data["session_id"] = session_id
    return sse_event("final", data)
