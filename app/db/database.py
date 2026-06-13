import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[2] / "job_agent.db"


def get_conn() -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to connect to database: {DB_PATH}") from exc


def init_db() -> None:
    conn: sqlite3.Connection | None = None
    try:
        conn = get_conn()
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS resume (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                content TEXT NOT NULL,
                parsed_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS job (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT,
                title TEXT NOT NULL,
                jd_text TEXT NOT NULL,
                parsed_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_task (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                resume_id INTEGER,
                job_id INTEGER,
                input_json TEXT,
                output_json TEXT,
                status TEXT NOT NULL,
                error_msg TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (resume_id) REFERENCES resume (id),
                FOREIGN KEY (job_id) REFERENCES job (id)
            )
            """
        )

        conn.commit()
    except sqlite3.Error as exc:
        if conn is not None:
            conn.rollback()
        raise RuntimeError("Failed to initialize database tables") from exc
    finally:
        if conn is not None:
            conn.close()
