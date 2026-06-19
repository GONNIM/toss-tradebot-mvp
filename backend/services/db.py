"""SQLAlchemy 2.0 async DB setup.

결정 37 — SQLite (MVP 1~3개월) → Supabase Postgres 마이그 (운영 안정 후).
ORM 추상화로 DATABASE_URL 만 변경하면 DB 전환 가능.

사용:
    from backend.services.db import get_session

    async with get_session() as session:
        ...
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv 미설치 시 환경변수 직접 사용

# DATABASE_URL: SQLite 기본, Postgres 마이그 가능
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./data/tradebot.db",
)

# sqlite scheme 보정 (sync → async)
if DATABASE_URL.startswith("sqlite:///") and "+aiosqlite" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("sqlite:///", "sqlite+aiosqlite:///", 1)

# Postgres scheme 보정
if DATABASE_URL.startswith("postgresql://") and "+asyncpg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

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
