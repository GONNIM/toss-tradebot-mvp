"""Watchlist Store · Sprint 2 T58 단위 테스트.

검증:
- upsert_signal · 정상 insert · id 반환
- 중복 방지 (5분 window · 동일 ticker/source/signal_type) · None 반환
- signals_for_date · trade_date 필터
- recent_signals · 최근 N시간 조회
- next_trade_date · 마감 후 감지 → 다음 영업일
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.discovery.watchlist.store import (
    next_trade_date,
    recent_signals,
    signals_for_date,
    upsert_signal,
)
from backend.services.db import get_session, init_db
from backend.services.models import WatchlistSignal


_KST = timezone(timedelta(hours=9))


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(WatchlistSignal))
    yield


@pytest.mark.asyncio
async def test_upsert_inserts_row():
    row_id = await upsert_signal(
        ticker="005930",
        source="news_yhap",
        signal_type="headline",
        intensity=1.0,
        payload={"title": "삼성전자 실적 호조", "url": "https://example.com/1"},
    )
    assert row_id is not None

    items = await recent_signals(hours=1)
    assert len(items) == 1
    assert items[0]["ticker"] == "005930"
    assert items[0]["source"] == "news_yhap"
    assert items[0]["payload"]["title"] == "삼성전자 실적 호조"


@pytest.mark.asyncio
async def test_upsert_dedup_within_window():
    first = await upsert_signal(
        ticker="373220",
        source="news_edaily",
        signal_type="headline",
        intensity=1.0,
    )
    second = await upsert_signal(
        ticker="373220",
        source="news_edaily",
        signal_type="headline",
        intensity=1.0,
    )
    assert first is not None
    assert second is None  # 중복 5분 내

    items = await recent_signals(hours=1)
    assert len(items) == 1


@pytest.mark.asyncio
async def test_upsert_dedup_boundary_by_source_and_type():
    """같은 ticker 라도 source 다르면 별개 저장."""
    a = await upsert_signal(ticker="000660", source="news_yhap", signal_type="headline", intensity=1.0)
    b = await upsert_signal(ticker="000660", source="news_edaily", signal_type="headline", intensity=1.0)
    c = await upsert_signal(ticker="000660", source="news_yhap", signal_type="board_post_velocity", intensity=2.5)
    assert a is not None and b is not None and c is not None

    items = await recent_signals(hours=1)
    assert len(items) == 3


@pytest.mark.asyncio
async def test_signals_for_date_filters():
    today_kst = datetime.now(tz=_KST).date().isoformat()
    tomorrow = (datetime.now(tz=_KST) + timedelta(days=1)).date().isoformat()

    await upsert_signal(ticker="005930", source="news_yhap", signal_type="headline", intensity=1.0, trade_date=today_kst)
    await upsert_signal(ticker="000660", source="news_yhap", signal_type="headline", intensity=1.0, trade_date=tomorrow)

    today_rows = await signals_for_date(today_kst)
    tomorrow_rows = await signals_for_date(tomorrow)
    assert len(today_rows) == 1 and today_rows[0]["ticker"] == "005930"
    assert len(tomorrow_rows) == 1 and tomorrow_rows[0]["ticker"] == "000660"


def test_next_trade_date_before_close_returns_today():
    ref = datetime(2026, 7, 14, 10, 0, 0, tzinfo=_KST).astimezone(timezone.utc)  # 화요일 10:00 KST
    assert next_trade_date(ref) == "2026-07-14"


def test_next_trade_date_after_close_returns_next_business_day():
    # 월요일 16:00 KST 마감 후 → 화요일
    monday_close = datetime(2026, 7, 13, 16, 0, 0, tzinfo=_KST).astimezone(timezone.utc)
    assert next_trade_date(monday_close) == "2026-07-14"

    # 금요일 16:00 KST 마감 후 → 월요일 (주말 skip)
    friday_close = datetime(2026, 7, 17, 16, 0, 0, tzinfo=_KST).astimezone(timezone.utc)
    assert next_trade_date(friday_close) == "2026-07-20"

    # 토요일 감지 → 월요일
    saturday = datetime(2026, 7, 18, 10, 0, 0, tzinfo=_KST).astimezone(timezone.utc)
    assert next_trade_date(saturday) == "2026-07-20"
