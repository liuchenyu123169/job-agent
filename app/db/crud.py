import json
import sqlite3
from typing import Any

from app.core.constants import DEFAULT_USER_ID
from app.core.security import DuplicateUserError
from app.db.database import get_conn


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _loads_json(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    loaded = json.loads(value)
    if isinstance(loaded, dict):
        return loaded
    raise ValueError("Stored JSON value is not a dict")


def _loads_json_or_raw(value: str | None) -> dict[str, Any] | str | None:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _next_local_id(
    cursor: sqlite3.Cursor,
    table_name: str,
    column_name: str,
    user_id: int,
) -> int:
    cursor.execute(
        f"""
        SELECT COALESCE(MAX({column_name}), 0)
        FROM {table_name}
        WHERE user_id = ?
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    current_max = int(row[0] or 0) if row is not None else 0
    return current_max + 1


def create_user(username: str, password_hash: str) -> dict[str, Any]:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO user (username, password_hash, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
            (username, password_hash),
        )
        user_id = int(cursor.lastrowid)
        conn.commit()
        user = get_user_by_id(user_id)
        if user is None:
            raise RuntimeError("Created user not found")
        return user
    except sqlite3.IntegrityError as exc:
        if conn is not None:
            conn.rollback()
        raise DuplicateUserError("Username already exists") from exc
    except sqlite3.Error as exc:
        if conn is not None:
            conn.rollback()
        raise RuntimeError("Failed to create user") from exc
    finally:
        if conn is not None:
            conn.close()


def get_user_by_username(username: str) -> dict[str, Any] | None:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, password_hash, is_admin, created_at, updated_at
            FROM user
            WHERE username = ?
            """,
            (username,),
        )
        return _row_to_dict(cursor.fetchone())
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to query user by username: {username}") from exc
    finally:
        if conn is not None:
            conn.close()


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, password_hash, is_admin, created_at, updated_at
            FROM user
            WHERE id = ?
            """,
            (user_id,),
        )
        return _row_to_dict(cursor.fetchone())
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to query user by id: {user_id}") from exc
    finally:
        if conn is not None:
            conn.close()


def insert_resume(file_name: str, content: str, user_id: int = DEFAULT_USER_ID) -> int:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        local_resume_id = _next_local_id(cursor, "resume", "local_resume_id", user_id)
        cursor.execute(
            """
            INSERT INTO resume (file_name, content, user_id, local_resume_id)
            VALUES (?, ?, ?, ?)
            """,
            (file_name, content, user_id, local_resume_id),
        )
        conn.commit()
        return int(cursor.lastrowid)
    except sqlite3.Error as exc:
        if conn is not None:
            conn.rollback()
        raise RuntimeError("Failed to insert resume") from exc
    finally:
        if conn is not None:
            conn.close()


def get_resume_by_id(resume_id: int, user_id: int = DEFAULT_USER_ID) -> dict[str, Any] | None:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, local_resume_id, file_name, content, parsed_json, created_at
            FROM resume
            WHERE id = ? AND user_id = ?
            """,
            (resume_id, user_id),
        )
        return _row_to_dict(cursor.fetchone())
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to query resume by id: {resume_id}") from exc
    finally:
        if conn is not None:
            conn.close()


def get_resume_by_local_id(
    local_resume_id: int,
    user_id: int = DEFAULT_USER_ID,
) -> dict[str, Any] | None:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, local_resume_id, file_name, content, parsed_json, created_at
            FROM resume
            WHERE local_resume_id = ? AND user_id = ?
            """,
            (local_resume_id, user_id),
        )
        return _row_to_dict(cursor.fetchone())
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to query resume by local id: {local_resume_id}") from exc
    finally:
        if conn is not None:
            conn.close()


def list_resumes_for_user(user_id: int = DEFAULT_USER_ID, limit: int = 100) -> list[dict[str, Any]]:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, local_resume_id, file_name, content, created_at
            FROM resume
            WHERE user_id = ?
            ORDER BY local_resume_id ASC, id ASC
            LIMIT ?
            """,
            (user_id, limit),
        )
        items: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            item = dict(row)
            item["content_preview"] = str(item.get("content") or "")[:200]
            items.append(item)
        return items
    except sqlite3.Error as exc:
        raise RuntimeError("Failed to list resumes for user") from exc
    finally:
        if conn is not None:
            conn.close()


def insert_job(
    company: str | None,
    title: str,
    jd_text: str,
    user_id: int = DEFAULT_USER_ID,
) -> int:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        local_job_id = _next_local_id(cursor, "job", "local_job_id", user_id)
        cursor.execute(
            """
            INSERT INTO job (company, title, jd_text, user_id, local_job_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (company, title, jd_text, user_id, local_job_id),
        )
        conn.commit()
        return int(cursor.lastrowid)
    except sqlite3.Error as exc:
        if conn is not None:
            conn.rollback()
        raise RuntimeError("Failed to insert job") from exc
    finally:
        if conn is not None:
            conn.close()


def get_job_by_id(job_id: int, user_id: int = DEFAULT_USER_ID) -> dict[str, Any] | None:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, local_job_id, company, title, jd_text, parsed_json, created_at
            FROM job
            WHERE id = ? AND user_id = ?
            """,
            (job_id, user_id),
        )
        return _row_to_dict(cursor.fetchone())
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to query job by id: {job_id}") from exc
    finally:
        if conn is not None:
            conn.close()


def get_job_by_local_id(
    local_job_id: int,
    user_id: int = DEFAULT_USER_ID,
) -> dict[str, Any] | None:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, local_job_id, company, title, jd_text, parsed_json, created_at
            FROM job
            WHERE local_job_id = ? AND user_id = ?
            """,
            (local_job_id, user_id),
        )
        return _row_to_dict(cursor.fetchone())
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to query job by local id: {local_job_id}") from exc
    finally:
        if conn is not None:
            conn.close()


def list_jobs_for_user(
    user_id: int = DEFAULT_USER_ID,
    limit: int = 10,
    newest_first: bool = False,
) -> list[dict[str, Any]]:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        order_by = "created_at DESC, id DESC" if newest_first else "local_job_id ASC, id ASC"
        cursor.execute(
            f"""
            SELECT id, local_job_id, company, title, jd_text, parsed_json, created_at
            FROM job
            WHERE user_id = ?
            ORDER BY {order_by}
            LIMIT ?
            """,
            (user_id, limit),
        )
        items: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            item = dict(row)
            item["jd_preview"] = str(item.get("jd_text") or "")[:200]
            items.append(item)
        return items
    except sqlite3.Error as exc:
        raise RuntimeError("Failed to list jobs for user") from exc
    finally:
        if conn is not None:
            conn.close()


def resolve_resume_for_user(
    user_id: int,
    resume_id: int | None = None,
    local_resume_id: int | None = None,
) -> dict[str, Any] | None:
    if resume_id is not None:
        return get_resume_by_id(resume_id, user_id=user_id)
    if local_resume_id is not None:
        return get_resume_by_local_id(local_resume_id, user_id=user_id)
    return None


def resolve_job_for_user(
    user_id: int,
    job_id: int | None = None,
    local_job_id: int | None = None,
) -> dict[str, Any] | None:
    if job_id is not None:
        return get_job_by_id(job_id, user_id=user_id)
    if local_job_id is not None:
        return get_job_by_local_id(local_job_id, user_id=user_id)
    return None


def insert_agent_task(
    task_type: str,
    resume_id: int | None,
    job_id: int | None,
    input_data: dict,
    output_data: dict | None = None,
    status: str = "SUCCESS",
    error_msg: str | None = None,
    user_id: int = DEFAULT_USER_ID,
    trace_spans: list[dict] | None = None,
) -> int:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        trace_json_str = json.dumps(trace_spans, ensure_ascii=False) if trace_spans else None
        cursor.execute(
            """
            INSERT INTO agent_task (
                task_type,
                resume_id,
                job_id,
                input_json,
                output_json,
                status,
                error_msg,
                user_id,
                trace_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_type,
                resume_id,
                job_id,
                json.dumps(input_data, ensure_ascii=False),
                json.dumps(output_data, ensure_ascii=False) if output_data is not None else None,
                status,
                error_msg,
                user_id,
                trace_json_str,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    except sqlite3.Error as exc:
        if conn is not None:
            conn.rollback()
        raise RuntimeError("Failed to insert agent task") from exc
    finally:
        if conn is not None:
            conn.close()


def insert_task_traces(task_id: int, spans: list[dict]) -> int:
    """批量写入任务执行链路 span。"""
    if not spans:
        return 0
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        for span in spans:
            cursor.execute(
                """
                INSERT INTO task_trace (task_id, span_name, duration_ms, metadata)
                VALUES (?, ?, ?, ?)
                """,
                (
                    task_id,
                    span["name"],
                    span["duration_ms"],
                    json.dumps(span.get("metadata", {}), ensure_ascii=False),
                ),
            )
        conn.commit()
        return len(spans)
    except sqlite3.Error as exc:
        if conn is not None:
            conn.rollback()
        raise RuntimeError(f"Failed to insert task traces for task {task_id}") from exc
    finally:
        if conn is not None:
            conn.close()


def get_task_traces(task_id: int) -> list[dict]:
    """查询单个任务的所有链路 span。"""
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, span_name, duration_ms, metadata, created_at FROM task_trace WHERE task_id = ? ORDER BY id",
            (task_id,),
        )
        rows = cursor.fetchall()
        result: list[dict] = []
        for row in rows:
            d = dict(row)
            if d.get("metadata"):
                d["metadata"] = _loads_json_or_raw(d["metadata"])
            result.append(d)
        return result
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to get task traces for task {task_id}") from exc
    finally:
        if conn is not None:
            conn.close()


def get_task_by_id(task_id: int, user_id: int = DEFAULT_USER_ID) -> dict[str, Any] | None:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                id,
                task_type,
                resume_id,
                job_id,
                input_json,
                output_json,
                status,
                error_msg,
                trace_json,
                created_at,
                updated_at
            FROM agent_task
            WHERE id = ? AND user_id = ?
            """,
            (task_id, user_id),
        )
        task = _row_to_dict(cursor.fetchone())
        if task is None:
            return None

        task["input_json"] = _loads_json(task["input_json"])
        task["output_json"] = _loads_json(task["output_json"])
        task["trace_json"] = _loads_json_or_raw(task["trace_json"])
        return task
    except (sqlite3.Error, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Failed to query task by id: {task_id}") from exc
    finally:
        if conn is not None:
            conn.close()


def list_agent_tasks(
    task_type: str | None = None,
    resume_id: int | None = None,
    job_id: int | None = None,
    limit: int = 20,
    user_id: int = DEFAULT_USER_ID,
) -> list[dict[str, Any]]:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()

        query = """
        SELECT
            id,
            task_type,
            resume_id,
            job_id,
            input_json,
            output_json,
            status,
            error_msg,
            created_at,
            updated_at
        FROM agent_task
        WHERE user_id = ?
        """
        params: list[Any] = [user_id]

        if task_type is not None:
            query += " AND task_type = ?"
            params.append(task_type)
        if resume_id is not None:
            query += " AND resume_id = ?"
            params.append(resume_id)
        if job_id is not None:
            query += " AND job_id = ?"
            params.append(job_id)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        tasks: list[dict[str, Any]] = []
        for row in rows:
            task = dict(row)
            task["input_json"] = _loads_json_or_raw(task["input_json"])
            task["output_json"] = _loads_json_or_raw(task["output_json"])
            tasks.append(task)

        return tasks
    except sqlite3.Error as exc:
        raise RuntimeError("Failed to list agent tasks") from exc
    finally:
        if conn is not None:
            conn.close()


# ── Copilot Session CRUD ──

def create_copilot_session(
    goal: str,
    user_id: int = DEFAULT_USER_ID,
) -> dict[str, Any]:
    """创建 Copilot 会话记录。"""
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO copilot_session (user_id, goal, status)
            VALUES (?, ?, 'RUNNING')
            """,
            (user_id, goal),
        )
        conn.commit()
        session_id = int(cursor.lastrowid)
        return get_copilot_session(session_id, user_id=user_id) or {}
    except sqlite3.Error as exc:
        if conn is not None:
            conn.rollback()
        raise RuntimeError("Failed to create copilot session") from exc
    finally:
        if conn is not None:
            conn.close()


def get_copilot_session(
    session_id: int,
    user_id: int = DEFAULT_USER_ID,
) -> dict[str, Any] | None:
    """查询单个 Copilot 会话。"""
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, goal, status, context_json, task_ids_json, summary_json,
                   created_at, updated_at
            FROM copilot_session
            WHERE id = ? AND user_id = ? AND status != 'ARCHIVED'
            """,
            (session_id, user_id),
        )
        session = _row_to_dict(cursor.fetchone())
        if session is None:
            return None
        session["context_json"] = _loads_json_or_raw(session["context_json"])
        session["task_ids_json"] = _loads_json_or_raw(session["task_ids_json"])
        session["summary_json"] = _loads_json_or_raw(session["summary_json"])
        return session
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to query copilot session: {session_id}") from exc
    finally:
        if conn is not None:
            conn.close()


def update_copilot_session(
    session_id: int,
    status: str | None = None,
    context_json: dict | None = None,
    task_ids_json: list | None = None,
    summary_json: dict | None = None,
    user_id: int = DEFAULT_USER_ID,
) -> dict[str, Any] | None:
    """更新 Copilot 会话状态和结果。"""
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()

        set_clauses: list[str] = []
        params: list[Any] = []

        if status is not None:
            set_clauses.append("status = ?")
            params.append(status)
        if context_json is not None:
            set_clauses.append("context_json = ?")
            params.append(json.dumps(context_json, ensure_ascii=False))
        if task_ids_json is not None:
            set_clauses.append("task_ids_json = ?")
            params.append(json.dumps(task_ids_json, ensure_ascii=False))
        if summary_json is not None:
            set_clauses.append("summary_json = ?")
            params.append(json.dumps(summary_json, ensure_ascii=False))

        if not set_clauses:
            return get_copilot_session(session_id, user_id=user_id)

        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        params.extend([session_id, user_id])

        query = f"UPDATE copilot_session SET {', '.join(set_clauses)} WHERE id = ? AND user_id = ?"
        cursor.execute(query, tuple(params))
        conn.commit()
        return get_copilot_session(session_id, user_id=user_id)
    except sqlite3.Error as exc:
        if conn is not None:
            conn.rollback()
        raise RuntimeError(f"Failed to update copilot session: {session_id}") from exc
    finally:
        if conn is not None:
            conn.close()


def list_copilot_sessions(
    user_id: int = DEFAULT_USER_ID,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """列出用户的 Copilot 会话历史。"""
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, goal, status, context_json, task_ids_json, summary_json,
                   created_at, updated_at
            FROM copilot_session
            WHERE user_id = ? AND status != 'ARCHIVED'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        sessions: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            session = dict(row)
            session["context_json"] = _loads_json_or_raw(session["context_json"])
            session["task_ids_json"] = _loads_json_or_raw(session["task_ids_json"])
            session["summary_json"] = _loads_json_or_raw(session["summary_json"])
            sessions.append(session)
        return sessions
    except sqlite3.Error as exc:
        raise RuntimeError("Failed to list copilot sessions") from exc
    finally:
        if conn is not None:
            conn.close()


# ── Conversation Messages CRUD ──

import hashlib  # noqa: E402


def _make_content_hash(role: str, content: str | None, tool_call_id: str | None = None) -> str:
    """生成消息去重哈希。"""
    raw = f"{role}::{content or ''}::{tool_call_id or ''}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def create_conversation_message(
    session_id: int,
    user_id: int,
    role: str,
    content: str | None = None,
    tool_calls_json: str | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
) -> int | None:
    """插入一条对话消息。已存在则跳过（返回 None）。"""
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        content_hash = _make_content_hash(role, content, tool_call_id)
        cursor.execute(
            """
            INSERT OR IGNORE INTO conversation_messages
                (session_id, user_id, role, content, tool_calls_json, tool_call_id, tool_name, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, user_id, role, content, tool_calls_json, tool_call_id, tool_name, content_hash),
        )
        conn.commit()
        return int(cursor.lastrowid) if cursor.lastrowid else None
    except sqlite3.Error as exc:
        if conn is not None:
            conn.rollback()
        raise RuntimeError("Failed to create conversation message") from exc
    finally:
        if conn is not None:
            conn.close()


def get_conversation_messages(
    session_id: int,
    user_id: int,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """加载会话的所有消息，按创建时间升序。"""
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, session_id, user_id, role, content, tool_calls_json, tool_call_id, tool_name, created_at
            FROM conversation_messages
            WHERE session_id = ? AND user_id = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (session_id, user_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to get conversation messages for session {session_id}") from exc
    finally:
        if conn is not None:
            conn.close()


def delete_conversation_messages(session_id: int, user_id: int) -> int:
    """删除会话的所有消息，返回删除条数。"""
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM conversation_messages WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        )
        deleted = cursor.rowcount
        conn.commit()
        return deleted
    except sqlite3.Error as exc:
        if conn is not None:
            conn.rollback()
        raise RuntimeError(f"Failed to delete conversation messages for session {session_id}") from exc
    finally:
        if conn is not None:
            conn.close()


def update_session_messages_summary(
    session_id: int,
    user_id: int,
    messages_summary: str | None,
) -> None:
    """更新会话的消息摘要。"""
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE copilot_session SET messages_summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (messages_summary, session_id, user_id),
        )
        conn.commit()
    except sqlite3.Error as exc:
        if conn is not None:
            conn.rollback()
        raise RuntimeError(f"Failed to update messages_summary for session {session_id}") from exc
    finally:
        if conn is not None:
            conn.close()
