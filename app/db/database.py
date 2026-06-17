import sqlite3
from pathlib import Path

from app.core.constants import DEFAULT_USER_ID


DB_PATH = Path(__file__).resolve().parents[2] / "job_agent.db"


def get_conn() -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to connect to database: {DB_PATH}") from exc


def _get_table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {str(row[1]) for row in cursor.fetchall()}


def _ensure_user_id_column(cursor: sqlite3.Cursor, table_name: str) -> None:
    columns = _get_table_columns(cursor, table_name)
    if "user_id" not in columns:
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN user_id INTEGER DEFAULT {DEFAULT_USER_ID}"
        )
    cursor.execute(
        f"UPDATE {table_name} SET user_id = ? WHERE user_id IS NULL",
        (DEFAULT_USER_ID,),
    )


def _ensure_column(
    cursor: sqlite3.Cursor,
    table_name: str,
    column_name: str,
    column_type: str,
) -> None:
    """安全添加列：如果列不存在则 ALTER TABLE ADD COLUMN。"""
    columns = _get_table_columns(cursor, table_name)
    if column_name not in columns:
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        )


def _ensure_local_id_column(
    cursor: sqlite3.Cursor,
    table_name: str,
    column_name: str,
) -> None:
    columns = _get_table_columns(cursor, table_name)
    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} INTEGER")


def _backfill_local_ids(
    cursor: sqlite3.Cursor,
    table_name: str,
    local_id_column: str,
) -> None:
    cursor.execute(
        f"""
        SELECT id, user_id
        FROM {table_name}
        ORDER BY user_id ASC, COALESCE(created_at, CURRENT_TIMESTAMP) ASC, id ASC
        """
    )
    rows = cursor.fetchall()
    counters: dict[int, int] = {}
    for row in rows:
        row_id = int(row["id"])
        user_id = int(row["user_id"] or DEFAULT_USER_ID)
        counters[user_id] = counters.get(user_id, 0) + 1
        cursor.execute(
            f"""
            UPDATE {table_name}
            SET {local_id_column} = ?
            WHERE id = ? AND ({local_id_column} IS NULL OR {local_id_column} <= 0)
            """,
            (counters[user_id], row_id),
        )


def _ensure_local_id_index(
    cursor: sqlite3.Cursor,
    table_name: str,
    local_id_column: str,
) -> None:
    cursor.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_{table_name}_user_{local_id_column}_unique
        ON {table_name} (user_id, {local_id_column})
        WHERE {local_id_column} IS NOT NULL
        """
    )


def _ensure_user_table(cursor: sqlite3.Cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            password_hash TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    columns = _get_table_columns(cursor, "user")
    if "password_hash" not in columns:
        cursor.execute("ALTER TABLE user ADD COLUMN password_hash TEXT")
    if "updated_at" not in columns:
        cursor.execute("ALTER TABLE user ADD COLUMN updated_at DATETIME")
    cursor.execute(
        """
        UPDATE user
        SET updated_at = COALESCE(updated_at, created_at, datetime('now'))
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_user_username_unique
        ON user (username)
        """
    )


def init_db() -> None:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()

        # 并发优化：WAL 模式 + 写锁等待
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")

        _ensure_user_table(cursor)

        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS resume (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                content TEXT NOT NULL,
                parsed_json TEXT,
                user_id INTEGER DEFAULT {DEFAULT_USER_ID},
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS job (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT,
                title TEXT NOT NULL,
                jd_text TEXT NOT NULL,
                parsed_json TEXT,
                user_id INTEGER DEFAULT {DEFAULT_USER_ID},
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS agent_task (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                resume_id INTEGER,
                job_id INTEGER,
                input_json TEXT,
                output_json TEXT,
                status TEXT NOT NULL,
                error_msg TEXT,
                user_id INTEGER DEFAULT {DEFAULT_USER_ID},
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (resume_id) REFERENCES resume (id),
                FOREIGN KEY (job_id) REFERENCES job (id)
            )
            """
        )

        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS copilot_session (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER DEFAULT {DEFAULT_USER_ID},
                goal TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'RUNNING',
                context_json TEXT,
                task_ids_json TEXT,
                summary_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES user (id)
            )
            """
        )

        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                tool_calls_json TEXT,
                tool_call_id TEXT,
                tool_name TEXT,
                content_hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES copilot_session (id),
                FOREIGN KEY (user_id) REFERENCES user (id)
            )
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_msg_dedup
            ON conversation_messages (session_id, content_hash)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_msg_session
            ON conversation_messages (session_id, created_at)
            """
        )

        # 给 copilot_session 加 messages_summary 列（安全迁移）
        _ensure_column(cursor, "copilot_session", "messages_summary", "TEXT")

        # 安全迁移：is_admin 列
        _ensure_column(cursor, "user", "is_admin", "INTEGER DEFAULT 0")

        # 确保已存在的 default_user 也是管理员 + 有默认密码
        cursor.execute(
            "UPDATE user SET is_admin = 1 WHERE id = ? AND (is_admin IS NULL OR is_admin = 0)",
            (DEFAULT_USER_ID,),
        )

        from app.core.security import hash_password  # noqa: E402
        default_pw = hash_password("123456")
        cursor.execute(
            """
            INSERT OR IGNORE INTO user (id, username, password_hash, updated_at, is_admin)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1)
            """,
            (DEFAULT_USER_ID, "default_user", default_pw),
        )
        # 兼容旧数据：如果 password_hash 为空则补上
        cursor.execute(
            "UPDATE user SET password_hash = ? WHERE id = ? AND password_hash IS NULL",
            (default_pw, DEFAULT_USER_ID),
        )

        _ensure_user_id_column(cursor, "resume")
        _ensure_user_id_column(cursor, "job")
        _ensure_user_id_column(cursor, "agent_task")
        _ensure_local_id_column(cursor, "resume", "local_resume_id")
        _ensure_local_id_column(cursor, "job", "local_job_id")
        _backfill_local_ids(cursor, "resume", "local_resume_id")
        _backfill_local_ids(cursor, "job", "local_job_id")
        _ensure_local_id_index(cursor, "resume", "local_resume_id")
        _ensure_local_id_index(cursor, "job", "local_job_id")

        conn.commit()
    except sqlite3.Error as exc:
        if conn is not None:
            conn.rollback()
        raise RuntimeError("Failed to initialize database tables") from exc
    finally:
        if conn is not None:
            conn.close()
