import json
import sqlite3
from typing import Any

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


def insert_resume(file_name: str, content: str) -> int:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO resume (file_name, content)
            VALUES (?, ?)
            """,
            (file_name, content),
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


def get_resume_by_id(resume_id: int) -> dict[str, Any] | None:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, file_name, content, parsed_json, created_at
            FROM resume
            WHERE id = ?
            """,
            (resume_id,),
        )
        return _row_to_dict(cursor.fetchone())
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to query resume by id: {resume_id}") from exc
    finally:
        if conn is not None:
            conn.close()


def insert_job(company: str | None, title: str, jd_text: str) -> int:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO job (company, title, jd_text)
            VALUES (?, ?, ?)
            """,
            (company, title, jd_text),
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


def get_job_by_id(job_id: int) -> dict[str, Any] | None:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, company, title, jd_text, parsed_json, created_at
            FROM job
            WHERE id = ?
            """,
            (job_id,),
        )
        return _row_to_dict(cursor.fetchone())
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to query job by id: {job_id}") from exc
    finally:
        if conn is not None:
            conn.close()


def insert_agent_task(
    task_type: str,
    resume_id: int | None,
    job_id: int | None,
    input_data: dict,
    output_data: dict | None = None,
    status: str = "SUCCESS",
    error_msg: str | None = None,
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
                error_msg
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_type,
                resume_id,
                job_id,
                json.dumps(input_data, ensure_ascii=False),
                json.dumps(output_data, ensure_ascii=False) if output_data is not None else None,
                status,
                error_msg,
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


def get_task_by_id(task_id: int) -> dict[str, Any] | None:
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
            WHERE id = ?
            """,
            (task_id,),
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
        WHERE 1 = 1
        """
        params: list[Any] = []

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
