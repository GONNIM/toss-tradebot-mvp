"""Alembic 환경 설정 · toss-tradebot-mvp.

- DATABASE_URL env 우선 (services.db 와 동일 규칙)
- async 드라이버 (aiosqlite/asyncpg) → sync 로 변환 (Alembic 은 sync API)
- target_metadata = services.models.Base.metadata (autogenerate 지원)
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# ── backend/ 를 sys.path 에 추가 (services.models import 위해)
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from services.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_sync_url() -> str:
    """DATABASE_URL 을 Alembic 용 sync 스킴으로 변환."""
    url = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{BACKEND_DIR / 'data' / 'tradebot.db'}",
    )
    # async → sync 스킴 정규화
    url = url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


config.set_main_option("sqlalchemy.url", _resolve_sync_url())

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite ALTER TABLE 호환
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite ALTER TABLE 호환
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
