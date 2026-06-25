"""管理员 API — 用户管理、全局资源查询（分页+筛选）、聚合统计、链路追踪。"""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_admin_user
from app.db.crud import get_user_by_id
from app.db.database import execute, execute_sql, fetch_all, fetch_one, get_conn

router = APIRouter(prefix="/api/admin", tags=["Admin"])

# ── 本地别名（兼容函数体内现有调用）──
_fetchall = fetch_all
_fetchone = fetch_one
_run = execute_sql


def _paginate(query: str, params: tuple, page: int, page_size: int, conn) -> dict:
    """执行分页查询，返回 {items, total, page, page_size}。"""
    # 查总数
    count_sql = f"SELECT COUNT(*) as cnt FROM ({query}) AS paged_query"
    total_row = _fetchone(conn, count_sql, params) or {"cnt": 0}
    total = total_row["cnt"]
    # 查分页数据
    offset = (page - 1) * page_size
    data_sql = f"{query} LIMIT {page_size} OFFSET {offset}"
    items = _fetchall(conn, data_sql, params)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _get_username_map(conn) -> dict[int, str]:
    rows = _fetchall(conn, 'SELECT id, username FROM "user"')
    return {r["id"]: r["username"] for r in rows}


def _attach_usernames(items: list[dict], conn) -> list[dict]:
    username_map = _get_username_map(conn)
    for item in items:
        item["username"] = username_map.get(item.get("user_id"), "")
    return items


# ═══════════════════════════════════════════════
# 用户管理
# ═══════════════════════════════════════════════

@router.get("/users")
def list_users(_admin: dict = Depends(get_admin_user)) -> list[dict]:
    conn = get_conn()
    try:
        return _fetchall(
            conn,
            'SELECT id, username, is_admin, created_at, updated_at FROM "user" ORDER BY id',
        )
    finally:
        conn.close()


@router.put("/users/{user_id}")
def update_user(user_id: int, body: dict, _admin: dict = Depends(get_admin_user)) -> dict:
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户未找到")
    is_admin = bool(body.get("is_admin", False))
    conn = get_conn()
    try:
        _run(
            conn,
            'UPDATE "user" SET is_admin = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (int(is_admin), user_id),
        )
        conn.commit()
        return {"user_id": user_id, "is_admin": is_admin}
    finally:
        conn.close()


@router.delete("/users/{user_id}")
def delete_user(user_id: int, _admin: dict = Depends(get_admin_user)) -> dict:
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户未找到")
    conn = get_conn()
    try:
        for table in ["conversation_messages", "copilot_session", "agent_task", "job", "resume"]:
            _run(conn, f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        _run(conn, 'DELETE FROM "user" WHERE id = ?', (user_id,))
        conn.commit()
        return {"user_id": user_id, "deleted": True}
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"删除用户失败: {exc}") from exc
    finally:
        conn.close()


# ═══════════════════════════════════════════════
# 全局资源（分页 + 筛选 + 用户名）
# ═══════════════════════════════════════════════

@router.get("/resumes")
def list_all_resumes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    username: str = Query(""),
    _admin: dict = Depends(get_admin_user),
) -> dict:
    conn = get_conn()
    try:
        base = """SELECT r.id, r.user_id, r.local_resume_id, r.file_name, r.content, r.created_at
                  FROM resume r"""
        params: tuple = ()
        if username:
            base += " JOIN \"user\" u ON r.user_id = u.id WHERE u.username LIKE ?"
            params = (f"%{username}%",)
        base += " ORDER BY r.created_at DESC"
        result = _paginate(base, params, page, page_size, conn)
        result["items"] = _attach_usernames(result["items"], conn)
        return result
    finally:
        conn.close()


@router.get("/jobs")
def list_all_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    username: str = Query(""),
    _admin: dict = Depends(get_admin_user),
) -> dict:
    conn = get_conn()
    try:
        base = """SELECT j.id, j.user_id, j.local_job_id, j.company, j.title, j.jd_text, j.created_at
                  FROM job j"""
        params: tuple = ()
        if username:
            base += " JOIN \"user\" u ON j.user_id = u.id WHERE u.username LIKE ?"
            params = (f"%{username}%",)
        base += " ORDER BY j.created_at DESC"
        result = _paginate(base, params, page, page_size, conn)
        result["items"] = _attach_usernames(result["items"], conn)
        return result
    finally:
        conn.close()


@router.get("/tasks")
def list_all_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    task_type: str = Query(""),
    status: str = Query(""),
    username: str = Query(""),
    _admin: dict = Depends(get_admin_user),
) -> dict:
    conn = get_conn()
    try:
        base = """SELECT t.id, t.task_type, t.user_id, t.resume_id, t.job_id,
                         t.status, t.error_msg, t.output_json, t.trace_json, t.created_at, t.updated_at
                  FROM agent_task t"""
        conditions: list[str] = []
        params_list: list[Any] = []

        if task_type:
            conditions.append("t.task_type = ?")
            params_list.append(task_type.upper())
        if status:
            conditions.append("t.status = ?")
            params_list.append(status.upper())
        if username:
            base += " JOIN \"user\" u ON t.user_id = u.id"
            conditions.append("u.username LIKE ?")
            params_list.append(f"%{username}%")

        if conditions:
            base += " WHERE " + " AND ".join(conditions)
        base += " ORDER BY t.created_at DESC"

        result = _paginate(base, tuple(params_list), page, page_size, conn)

        # 解析 JSON 字段 + 填充 trace 数据
        for item in result["items"]:
            item["username"] = ""
            if item.get("output_json") and isinstance(item["output_json"], str):
                try:
                    item["output_json"] = json.loads(item["output_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            # 从 task_trace 表查 span
            spans = _fetchall(
                conn,
                "SELECT span_name, duration_ms, metadata FROM task_trace WHERE task_id = ? ORDER BY id",
                (item["id"],),
            )
            trace = []
            for s in spans:
                meta = {}
                if s["metadata"]:
                    try:
                        meta = json.loads(s["metadata"]) if isinstance(s["metadata"], str) else s["metadata"]
                    except (json.JSONDecodeError, TypeError):
                        pass
                trace.append({"name": s["span_name"], "duration_ms": s["duration_ms"], "metadata": meta})
            item["trace_json"] = trace if trace else None

        result["items"] = _attach_usernames(result["items"], conn)
        return result
    finally:
        conn.close()


@router.get("/sessions")
def list_all_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    username: str = Query(""),
    _admin: dict = Depends(get_admin_user),
) -> dict:
    conn = get_conn()
    try:
        base = """SELECT s.id, s.user_id, s.goal, s.status, s.task_ids_json, s.created_at, s.updated_at
                  FROM copilot_session s"""
        params: tuple = ()
        if username:
            base += " JOIN \"user\" u ON s.user_id = u.id WHERE u.username LIKE ?"
            params = (f"%{username}%",)
        base += " AND s.status != 'ARCHIVED'" if "WHERE" in base else " WHERE s.status != 'ARCHIVED'"
        base += " ORDER BY s.created_at DESC"
        result = _paginate(base, params, page, page_size, conn)
        result["items"] = _attach_usernames(result["items"], conn)
        return result
    finally:
        conn.close()


# ═══════════════════════════════════════════════
# 链路追踪
# ═══════════════════════════════════════════════

@router.get("/traces")
def list_traces(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    _admin: dict = Depends(get_admin_user),
) -> dict:
    """返回所有有链路数据的任务及其 span 详情（从 task_trace 表查询）。"""
    conn = get_conn()
    try:
        # 查询有 trace 的任务
        base = """SELECT DISTINCT t.id, t.task_type, t.user_id, t.resume_id, t.job_id,
                         t.status, t.created_at
                  FROM agent_task t
                  JOIN task_trace tr ON t.id = tr.task_id
                  ORDER BY t.created_at DESC"""
        result = _paginate(base, (), page, page_size, conn)

        for item in result["items"]:
            item["username"] = ""
            # 查该任务的所有 span
            spans = _fetchall(
                conn,
                "SELECT span_name, duration_ms, metadata FROM task_trace WHERE task_id = ? ORDER BY id",
                (item["id"],),
            )
            trace = []
            for s in spans:
                meta = {}
                if s["metadata"]:
                    try:
                        meta = json.loads(s["metadata"]) if isinstance(s["metadata"], str) else s["metadata"]
                    except (json.JSONDecodeError, TypeError):
                        pass
                trace.append({"name": s["span_name"], "duration_ms": s["duration_ms"], "metadata": meta})
            item["trace_json"] = trace
            item["total_duration_ms"] = round(sum(t.get("duration_ms", 0) for t in trace), 2)

        result["items"] = _attach_usernames(result["items"], conn)
        return result
    finally:
        conn.close()


# ═══════════════════════════════════════════════
# 聚合统计
# ═══════════════════════════════════════════════

@router.get("/stats")
def get_stats(_admin: dict = Depends(get_admin_user)) -> dict:
    conn = get_conn()
    try:
        c = conn.cursor()

        c.execute('SELECT COUNT(*) as cnt FROM "user"');          user_count = c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM resume");           resume_count = c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM job");              job_count = c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM agent_task");       task_count = c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM copilot_session WHERE status != 'ARCHIVED'"); session_count = c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM conversation_messages"); msg_count = c.fetchone()["cnt"]

        # 按状态统计
        c.execute("SELECT status, COUNT(*) as cnt FROM agent_task GROUP BY status")
        task_by_status = {r["status"]: r["cnt"] for r in c.fetchall()}

        # 按类型统计
        c.execute("SELECT task_type, COUNT(*) as cnt FROM agent_task GROUP BY task_type")
        task_by_type = {r["task_type"]: r["cnt"] for r in c.fetchall()}

        # 平均耗时（从 trace_json 估算）
        c.execute("SELECT trace_json FROM agent_task WHERE trace_json IS NOT NULL AND trace_json != ''")
        durations: list[float] = []
        for (tj,) in c.fetchall():
            try:
                spans = json.loads(tj) if isinstance(tj, str) else tj
                if isinstance(spans, list):
                    durations.append(sum(s.get("duration_ms", 0) for s in spans))
            except (json.JSONDecodeError, TypeError):
                pass
        avg_duration = round(sum(durations) / len(durations), 1) if durations else 0

        # 最近 24h 任务数
        c.execute("SELECT COUNT(*) as cnt FROM agent_task WHERE created_at >= NOW() - INTERVAL '1 day'")
        tasks_24h = c.fetchone()["cnt"]

        return {
            "users": user_count,
            "resumes": resume_count,
            "jobs": job_count,
            "tasks": task_count,
            "tasks_by_status": task_by_status,
            "tasks_by_type": task_by_type,
            "tasks_24h": tasks_24h,
            "avg_task_duration_ms": avg_duration,
            "sessions": session_count,
            "messages": msg_count,
        }
    finally:
        conn.close()
