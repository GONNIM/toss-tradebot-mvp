"""DB 단위 테스트 — Phase B 검증.

실행:
    cd backend && pytest tests/test_db.py -v

각 테스트는 임시 SQLite 사용 (메모리 또는 ./data/test_tradebot.db).
"""
from __future__ import annotations

import os

# 테스트 전용 DB 격리
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_init_db_creates_all_tables():
    """init_db 호출 시 모든 테이블이 생성되는지 확인."""
    from backend.services.db import drop_db, init_db
    from backend.services.models import Base

    await drop_db()
    await init_db()

    expected_tables = {
        # Discovery
        "crazy_picks",
        "moonshot_picks",
        "daily_candles",
        "logs",
        "ticker_universe",
        # 자동매매 코어 (Phase K)
        "accounts",
        "account_positions",
        "orders",
        "engine_status",
        "audit_trades",
    }
    actual_tables = set(Base.metadata.tables.keys())
    assert expected_tables == actual_tables, (
        f"Missing: {expected_tables - actual_tables}, "
        f"Extra: {actual_tables - expected_tables}"
    )


@pytest.mark.asyncio
async def test_crazy_pick_insert_and_query():
    """CrazyPick 모델 CRUD."""
    from backend.services.db import drop_db, get_session, init_db
    from backend.services.models import CrazyPick

    await drop_db()
    await init_db()

    # Insert
    async with get_session() as session:
        pick = CrazyPick(
            pick_date="2026-06-19",
            rank=1,
            ticker="AAPL",
            company_name="Apple Inc.",
            sector="Tech",
            close_price=200.50,
            composite_score=87.5,
            thesis="Strong earnings momentum + iPhone 16 launch catalyst.",
        )
        session.add(pick)

    # Query
    async with get_session() as session:
        result = await session.execute(
            select(CrazyPick).where(CrazyPick.ticker == "AAPL")
        )
        retrieved = result.scalar_one()
        assert retrieved.company_name == "Apple Inc."
        assert retrieved.composite_score == 87.5
        assert retrieved.rank == 1


@pytest.mark.asyncio
async def test_moonshot_pick_9_factor_scores():
    """MoonshotPick 9 인자 점수 (결정 32) 저장·조회."""
    from backend.services.db import drop_db, get_session, init_db
    from backend.services.models import MoonshotPick

    await drop_db()
    await init_db()

    async with get_session() as session:
        pick = MoonshotPick(
            pick_date="2026-06-19",
            rank=1,
            ticker="EHGO",
            company_name="Eshallgo Inc.",
            market_cap=2_800_000.0,  # $2.8M 마이크로캡
            current_price=4.50,
            # 9 인자 점수
            score_volatility=85.0,
            score_catalyst=95.0,
            score_squeeze=40.0,
            score_social=60.0,
            score_news=88.0,
            score_technical=72.0,
            score_gap_volume=98.0,
            score_low_rebound=15.0,
            score_insider=20.0,
            composite_score=87.0,
            # 매수가 3 옵션
            buy_price_a=4.50,
            buy_price_b=4.27,
            buy_price_c=4.85,
            # 위험 분류 (결정 40)
            market_cap_category="MICRO",
            risk_level="HIGH",
            manipulation_risk=4,
        )
        session.add(pick)

    async with get_session() as session:
        result = await session.execute(
            select(MoonshotPick).where(MoonshotPick.ticker == "EHGO")
        )
        retrieved = result.scalar_one()
        assert retrieved.risk_level == "HIGH"
        assert retrieved.target_sell_multiplier == 2.0  # 결정 34 default
        assert retrieved.stop_loss_multiplier == 0.5
        assert retrieved.time_stop_days == 5
        assert retrieved.score_catalyst == 95.0


@pytest.mark.asyncio
async def test_daily_candle_cache():
    """DailyCandle 일봉 캐시 (Stooq + Toss 공통)."""
    from backend.services.db import drop_db, get_session, init_db
    from backend.services.models import DailyCandle

    await drop_db()
    await init_db()

    async with get_session() as session:
        candle = DailyCandle(
            ticker="AAPL",
            date="2026-06-19",
            open=199.0,
            high=201.5,
            low=198.5,
            close=200.50,
            volume=50_000_000,
            source="stooq",
        )
        session.add(candle)

    async with get_session() as session:
        result = await session.execute(
            select(DailyCandle).where(
                DailyCandle.ticker == "AAPL",
                DailyCandle.date == "2026-06-19",
            )
        )
        retrieved = result.scalar_one()
        assert retrieved.high == 201.5
        assert retrieved.source == "stooq"


@pytest.mark.asyncio
async def test_log_insert():
    """Log 감사 로그."""
    from backend.services.db import drop_db, get_session, init_db
    from backend.services.models import Log

    await drop_db()
    await init_db()

    async with get_session() as session:
        log = Log(
            level="INFO",
            module="moonshot",
            message="Top 10 generated for 2026-06-19",
            context='{"count": 10, "duration_ms": 1234}',
        )
        session.add(log)

    async with get_session() as session:
        result = await session.execute(select(Log).where(Log.module == "moonshot"))
        retrieved = result.scalar_one()
        assert retrieved.level == "INFO"
        assert "Top 10" in retrieved.message
