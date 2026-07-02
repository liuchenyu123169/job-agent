"""add_agent_run — 任务推进状态持久化表。

与 copilot_session 的职责分离：
  - copilot_session: "聊过什么"（对话历史）
  - agent_run:       "任务做到哪了"（任务推进状态）

Revision ID: 449830085605
Revises: 70cbc99400b3
Create Date: 2026-06-25 17:56:37.617648
"""
from typing import Sequence, Union

from alembic import op

revision: str = "449830085605"
down_revision: Union[str, Sequence[str], None] = "70cbc99400b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE agent_run (
            id              BIGSERIAL PRIMARY KEY,
            user_id         INTEGER NOT NULL REFERENCES "user"(id),
            session_id      INTEGER REFERENCES copilot_session(id),
            goal            TEXT NOT NULL,
            goal_type       TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'created',
            plan_json       TEXT,
            current_step    TEXT,
            completed_steps_json TEXT,
            pending_steps_json   TEXT,
            failed_steps_json    TEXT,
            blockers_json   TEXT,
            next_action     TEXT,
            acceptance_criteria_json TEXT,
            verification_results_json TEXT,
            replan_count    INTEGER DEFAULT 0,
            final_report    TEXT,
            next_suggestions_json TEXT,
            task_ids_json   TEXT,
            created_at      TIMESTAMP DEFAULT NOW(),
            updated_at      TIMESTAMP DEFAULT NOW()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_run CASCADE")
