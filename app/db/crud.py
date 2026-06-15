import json
import sqlite3
from typing import Any

from app.core.constants import DEFAULT_USER_ID
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
        raise RuntimeError("Username already exists") from exc
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
            SELECT id, username, password_hash, created_at, updated_at
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
            SELECT id, username, password_hash, created_at, updated_at
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
) -> int:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
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
                user_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
