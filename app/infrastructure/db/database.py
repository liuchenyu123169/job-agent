import logging
import os
import re
from contextlib import contextmanager
from datetime import datetime

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL 未配置。请在 .env 中设置 PostgreSQL 连接字符串，\n"
        "例如: DATABASE_URL=postgresql://jobagent:jobagent@localhost:5432/jobagent"
    )


class _StringifyDictCursor(psycopg2.extras.RealDictCursor):
    """RealDictCursor 子类：自动将 datetime 值转为 ISO 字符串。"""

    def fetchone(self):
        row = super().fetchone()
        if row:
            for k in list(row.keys()):
                if isinstance(row[k], datetime):
                    row[k] = row[k].isoformat()
        return row

    def fetchall(self):
        rows = super().fetchall()
        for row in rows:
            for k in list(row.keys()):
                if isinstance(row[k], datetime):
                    row[k] = row[k].isoformat()
        return rows


def get_conn():
    """获取 PostgreSQL 数据库连接（dict-like row access，datetime → ISO 字符串）。"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.cursor_factory = _StringifyDictCursor
        return conn
    except psycopg2.Error as exc:
        raise RuntimeError(f"Failed to connect to PostgreSQL: {DATABASE_URL}") from exc


@contextmanager
def get_db():
    """数据库连接上下文管理器，自动 commit/rollback/close。"""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute(cursor, sql_text: str, params: tuple = ()) -> None:
    """执行 SQL，自动适配 PostgreSQL 语法（? → %s，保留字 "user" 加引号）。"""
    if "?" in sql_text:
        sql_text = sql_text.replace("?", "%s")
    if "user" in sql_text:
        for keyword in ("FROM", "INTO", "UPDATE", "TABLE", "JOIN", "ON", "REFERENCES"):
            sql_text = re.sub(
                rf'({keyword}\s+)user\b',
                rf'\1"user"',
                sql_text,
            )
    cursor.execute(sql_text, params)


def get_last_id(cursor, table_name: str = "") -> int:
    """获取最后插入的 ID（需配合 RETURNING 使用）。"""
    cursor.execute("SELECT lastval()")
    return int(cursor.fetchone()["lastval"])


def init_db() -> None:
    """Schema 由 Alembic 管理。"""
    logger.info("PostgreSQL — schema managed by Alembic, init_db() is a no-op")


# ── 通用查询辅助函数 ──

def fetch_all(conn, query: str, params: tuple = ()) -> list[dict]:
    """执行查询并返回全部结果行（dict 列表）。"""
    cursor = conn.cursor()
    try:
        execute(cursor, query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        cursor.close()


def fetch_one(conn, query: str, params: tuple = ()) -> dict | None:
    """执行查询并返回第一行（dict），无结果返回 None。"""
    cursor = conn.cursor()
    try:
        execute(cursor, query, params)
        row = cursor.fetchone()
        return dict(row) if row is not None else None
    finally:
        cursor.close()


def execute_sql(conn, query: str, params: tuple = ()) -> int:
    """执行写操作并返回受影响行数。"""
    cursor = conn.cursor()
    try:
        execute(cursor, query, params)
        return cursor.rowcount
    finally:
        cursor.close()
