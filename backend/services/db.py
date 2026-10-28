"""SQLAlchemy 2.0 async DB setup.

결정 37 — SQLite (MVP 1~3개월) → Supabase Postgres 마이그 (운영 안정 후).
ORM 추상화로 DATABASE_URL 만 변경하면 DB 전환 가능.

사용:
    from backend.services.db import get_session

    async with get_session() as session:
        ...
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.services.config import database_url

# DATABASE_URL 결정·scheme 보정은 backend.services.config.database_url() 로 위임
# (Phase D 주 8 · 2026-07-31 · Postgres 전환 시 진입점 단일화).
DATABASE_URL = database_url()



def _connect_args_for(url: str) -> dict:
    """SQLite 는 api·cron·biotech 세 프로세스가 같은 파일을 쓰므로 잠금 대기 5초 (Postgres 는 없음)."""
    return {"timeout": 5} if url.startswith("sqlite") else {}


def _connect_args() -> dict:
    return _connect_args_for(DATABASE_URL)


# Engine + Session factory (모듈 레벨, 프로세스 lifetime)
engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,  # DEBUG 시 True
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args(),
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """비동기 세션 컨텍스트 매니저.

    - 정상 종료: commit
    - 예외: rollback
    - 항상 close
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """모든 테이블 생성. 첫 운영 또는 테스트용."""
    from backend.services.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_columns()


logger = logging.getLogger(__name__)

# 기존 표에 나중에 붙인 열 (create_all 은 있는 표에 열을 넣지 않는다) · (표, 열, SQL 타입)
_ADDED_COLUMNS = [
    ("user_judgments", "result_base_price", "FLOAT"),        # 1025-05
    ("user_judgments", "result_base_source", "VARCHAR(10)"),  # 1025-05
    ("ticker_universe", "current_price", "FLOAT"),            # 1027-03
]


async def ensure_columns() -> None:
    """빠진 열만 ALTER TABLE ADD COLUMN (멱등 · SQLite)."""
    from sqlalchemy import text

    if engine.dialect.name != "sqlite":
        return  # Postgres 전환 때는 마이그레이션 도구로
    async with engine.begin() as conn:
        for table, col, typ in _ADDED_COLUMNS:
            rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).all()
            if rows and col not in {r[1] for r in rows}:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))
                logger.warning("[db] 열 추가 %s.%s", table, col)


async def drop_db() -> None:
    """모든 테이블 삭제. 테스트 전용 — 운영에서 절대 호출 X."""
    from backend.services.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
