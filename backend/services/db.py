"""SQLAlchemy 2.0 async DB setup.

결정 37 — SQLite (MVP 1~3개월) → Supabase Postgres 마이그 (운영 안정 후).
ORM 추상화로 DATABASE_URL 만 변경하면 DB 전환 가능.

사용:
    from backend.services.db import get_session

    async with get_session() as session:
        ...
"""
from __future__ import annotations

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

# Engine + Session factory (모듈 레벨, 프로세스 lifetime)
engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,  # DEBUG 시 True
    future=True,
    pool_pre_ping=True,
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


async def drop_db() -> None:
    """모든 테이블 삭제. 테스트 전용 — 운영에서 절대 호출 X."""
    from backend.services.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
