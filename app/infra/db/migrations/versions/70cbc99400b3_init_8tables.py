"""init_8tables — 初始 schema：7 张业务表 + 1 张新 evaluation_run 表。

Revision ID: 70cbc99400b3
Revises:
Create Date: 2026-06-23 15:50:38.393166
"""
from typing import Sequence, Union

from alembic import op

revision: str = "70cbc99400b3"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. user
    op.execute("""
        CREATE TABLE "user" (
            id          BIGSERIAL PRIMARY KEY,
            username    TEXT NOT NULL,
            password_hash TEXT,
            is_admin    INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT NOW(),
            updated_at  TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_username_unique ON \"user\" (username)")

    # 2. resume
    op.execute("""
        CREATE TABLE resume (
            id              BIGSERIAL PRIMARY KEY,
            file_name       TEXT NOT NULL,
            content         TEXT NOT NULL,
            parsed_json     TEXT,
            local_resume_id INTEGER,
            user_id         INTEGER DEFAULT 1,
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_resume_user_local_resume_id_unique ON resume (user_id, local_resume_id) WHERE local_resume_id IS NOT NULL")

    # 3. job
    op.execute("""
        CREATE TABLE job (
            id              BIGSERIAL PRIMARY KEY,
            company         TEXT,
            title           TEXT NOT NULL,
            jd_text         TEXT NOT NULL,
            parsed_json     TEXT,
            local_job_id    INTEGER,
            user_id         INTEGER DEFAULT 1,
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_job_user_local_job_id_unique ON job (user_id, local_job_id) WHERE local_job_id IS NOT NULL")

    # 4. agent_task（比 SQLite 版多 3 列：prompt_version, model_name, rag_hit_info）
    op.execute("""
        CREATE TABLE agent_task (
            id              BIGSERIAL PRIMARY KEY,
            task_type       TEXT NOT NULL,
            resume_id       INTEGER REFERENCES resume(id),
            job_id          INTEGER REFERENCES job(id),
            input_json      TEXT,
            output_json     TEXT,
            status          TEXT NOT NULL,
            error_msg       TEXT,
            trace_json      TEXT,
            prompt_version  TEXT,
            model_name      TEXT,
            rag_hit_info    TEXT,
            user_id         INTEGER DEFAULT 1,
            created_at      TIMESTAMP DEFAULT NOW(),
            updated_at      TIMESTAMP DEFAULT NOW()
        )
    """)

    # 5. task_trace
    op.execute("""
        CREATE TABLE task_trace (
            id              BIGSERIAL PRIMARY KEY,
            task_id         INTEGER NOT NULL REFERENCES agent_task(id),
            span_name       TEXT NOT NULL,
            duration_ms     REAL NOT NULL,
            metadata        TEXT,
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """)

    # 6. copilot_session
    op.execute("""
        CREATE TABLE copilot_session (
            id                  BIGSERIAL PRIMARY KEY,
            user_id             INTEGER DEFAULT 1 REFERENCES "user"(id),
            goal                TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'RUNNING',
            context_json        TEXT,
            task_ids_json       TEXT,
            summary_json        TEXT,
            messages_summary    TEXT,
            created_at          TIMESTAMP DEFAULT NOW(),
            updated_at          TIMESTAMP DEFAULT NOW()
        )
    """)

    # 7. conversation_messages
    op.execute("""
        CREATE TABLE conversation_messages (
            id              BIGSERIAL PRIMARY KEY,
            session_id      INTEGER NOT NULL REFERENCES copilot_session(id),
            user_id         INTEGER NOT NULL REFERENCES "user"(id),
            role            TEXT NOT NULL,
            content         TEXT,
            tool_calls_json TEXT,
            tool_call_id    TEXT,
            tool_name       TEXT,
            content_hash    TEXT,
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_msg_dedup ON conversation_messages (session_id, content_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_conversation_msg_session ON conversation_messages (session_id, created_at)")

    # 8. evaluation_run（新表，Phase 2 新增）
    op.execute("""
        CREATE TABLE evaluation_run (
            id              BIGSERIAL PRIMARY KEY,
            workflow        TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'running',
            total_cases     INTEGER DEFAULT 0,
            passed_cases    INTEGER DEFAULT 0,
            avg_score       REAL DEFAULT 0,
            result_json     TEXT,
            started_at      TIMESTAMP DEFAULT NOW(),
            finished_at     TIMESTAMP
        )
    """)

    # 默认管理员用户
    op.execute("""
        INSERT INTO "user" (id, username, password_hash, is_admin, updated_at)
        VALUES (1, 'default_user', '$2b$12$LJ3m4ys3GZfnYMz8kVsKaOTSxGHLfEhCgJwF7pQmGXHxZmzwV9X3G', 1, NOW())
        ON CONFLICT (id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS evaluation_run CASCADE")
    op.execute("DROP TABLE IF EXISTS conversation_messages CASCADE")
    op.execute("DROP TABLE IF EXISTS copilot_session CASCADE")
    op.execute("DROP TABLE IF EXISTS task_trace CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_task CASCADE")
    op.execute("DROP TABLE IF EXISTS job CASCADE")
    op.execute("DROP TABLE IF EXISTS resume CASCADE")
    op.execute("DROP TABLE IF EXISTS \"user\" CASCADE")
