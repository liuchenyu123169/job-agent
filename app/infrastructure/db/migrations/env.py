"""Alembic env.py — Raw SQL 迁移模式（不使用 SQLAlchemy ORM）。

DATABASE_URL 从环境变量读取，默认指向 PostgreSQL。
"""

import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv

load_dotenv()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 从环境变量读取数据库 URL，alembic.ini 里的值作为 fallback
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    config.get_main_option("sqlalchemy.url", "postgresql://jobagent:jobagent@localhost:5432/jobagent"),
)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# 纯 raw SQL 迁移，不需要 ORM metadata
target_metadata = None


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 脚本，不连数据库。"""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库执行迁移。"""
    from sqlalchemy import create_engine

    connectable = create_engine(DATABASE_URL)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
