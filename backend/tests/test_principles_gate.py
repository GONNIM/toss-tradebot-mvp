"""PrinciplesGate 단위 테스트 (gate-design-v1 §3-1 · 세션 A · 2026-08-23).

8 케이스:
  1. PASS 종목 · 통과
  2. 비PASS 종목 · principles_fail_closed 차단
  3. 최신 run stale (>26h) · principles_run_stale 차단
  4. principles_runs 비어있음 · principles_run_missing 차단
  5. sniper 소스 · whitelist_bypass · 통과
  6. 미분류 source (unknown) · 비PASS 종목 · fail-closed
  7. finished_at IS NULL run 만 있음 · principles_run_missing (미완료 skip)
  8. 차단 시 PrinciplesGateBlockLog 저장 확인
"""
from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import delete, select

# 격리 · in-memory sqlite 로 테스트 (config 로 인 · setup_secure_logging 자동)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.services import config  # noqa: F401 · logging setup + env load
from backend.services.db import Base, engine, get_session
from backend.services.models import (
    PrinciplesGateBlockLog,
    PrinciplesResult,
    PrinciplesRun,
)
from backend.execution.principles_gate import (
    PrinciplesGateChecker,
    STALE_HOURS,
    reset_principles_gate,
)


@pytest.fixture(autouse=True)
async def _setup_db():
    """각 테스트 전 · 인메모리 DB 초기화."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    reset_principles_gate()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _insert_run(session, *, finished: bool, hours_ago: float = 0.0, run_id: int | None = None):
    from datetime import datetime, timedelta
    now = datetime.now()
    started = now - timedelta(hours=hours_ago + 0.1)
    finished_at = (now - timedelta(hours=hours_ago)) if finished else None
    run = PrinciplesRun(
        started_at=started,
        finished_at=finished_at,
        trigger="test",
        charter_version="1.0.9",
        universe_size=832,
        pass_count=10,
        fail_count=792,
        insufficient_count=30,
        dart_call_count=0,
    )
    session.add(run)
    await session.flush()
    return run


async def _insert_pass(session, run_id: int, ticker: str, name: str = "테스트"):
    session.add(PrinciplesResult(
        run_id=run_id, ticker=ticker, name=name, verdict="PASS",
    ))


@pytest.mark.asyncio
async def test_1_pass_ticker_allowed():
    """1. PASS 종목 · 통과."""
    async with get_session() as s:
        run = await _insert_run(s, finished=True, hours_ago=1.0)
        await _insert_pass(s, run.id, "033530")  # SJG세종
        await s.commit()
    checker = PrinciplesGateChecker()
    r = await checker.check(ticker="033530", source="super_signal")
    assert r.passed is True
    assert r.bypass is False


@pytest.mark.asyncio
async def test_2_non_pass_ticker_blocked():
    """2. 비PASS 종목 · principles_fail_closed 차단."""
    async with get_session() as s:
        run = await _insert_run(s, finished=True, hours_ago=1.0)
        await _insert_pass(s, run.id, "033530")
        await s.commit()
    checker = PrinciplesGateChecker()
    r = await checker.check(ticker="005930", source="super_signal")
    assert r.passed is False
    assert r.reason == "principles_fail_closed"


@pytest.mark.asyncio
async def test_3_run_stale_blocked():
    """3. 최신 run stale (>26h) · principles_run_stale 차단."""
    async with get_session() as s:
        run = await _insert_run(s, finished=True, hours_ago=27.0)
        await _insert_pass(s, run.id, "033530")
        await s.commit()
    checker = PrinciplesGateChecker()
    r = await checker.check(ticker="033530", source="super_signal")
    assert r.passed is False
    assert r.reason == "principles_run_stale"


@pytest.mark.asyncio
async def test_4_no_runs_blocked():
    """4. principles_runs 비어있음 · principles_run_missing 차단."""
    checker = PrinciplesGateChecker()
    r = await checker.check(ticker="005930", source="super_signal")
    assert r.passed is False
    assert r.reason == "principles_run_missing"


@pytest.mark.asyncio
async def test_5_sniper_bypass_allowed():
    """5. sniper 소스 · whitelist_bypass · 통과 + 로그 (비PASS 종목도 우회)."""
    async with get_session() as s:
        run = await _insert_run(s, finished=True, hours_ago=1.0)
        await _insert_pass(s, run.id, "033530")
        await s.commit()
    checker = PrinciplesGateChecker()
    r = await checker.check(ticker="005930", source="sniper")  # 비PASS 종목이지만 sniper
    assert r.passed is True
    assert r.bypass is True
    assert r.reason == "whitelist_bypass"


@pytest.mark.asyncio
async def test_6_unknown_source_fail_closed():
    """6. 미분류 source (unknown) · 비PASS 종목 · fail-closed."""
    async with get_session() as s:
        run = await _insert_run(s, finished=True, hours_ago=1.0)
        await _insert_pass(s, run.id, "033530")
        await s.commit()
    checker = PrinciplesGateChecker()
    # 미분류 source 는 화이트리스트 미매치 · PASS 아닌 종목이면 차단
    r = await checker.check(ticker="005930", source="unknown_source_xyz")
    assert r.passed is False
    assert r.reason == "principles_fail_closed"


@pytest.mark.asyncio
async def test_7_only_unfinished_run_treated_as_missing():
    """7. finished_at IS NULL run 만 있음 · principles_run_missing (미완료 skip)."""
    async with get_session() as s:
        # 미완료 run 만 삽입
        await _insert_run(s, finished=False, hours_ago=0.5)
        await s.commit()
    checker = PrinciplesGateChecker()
    r = await checker.check(ticker="033530", source="super_signal")
    assert r.passed is False
    assert r.reason == "principles_run_missing"


@pytest.mark.asyncio
async def test_8_block_log_persisted():
    """8. 차단 시 PrinciplesGateBlockLog 저장 확인."""
    async with get_session() as s:
        run = await _insert_run(s, finished=True, hours_ago=1.0)
        await _insert_pass(s, run.id, "033530")
        await s.commit()
    checker = PrinciplesGateChecker()
    r = await checker.check(ticker="005930", source="super_signal")
    assert r.passed is False
    # 로그 저장 확인
    async with get_session() as s:
        logs = (await s.execute(
            select(PrinciplesGateBlockLog).where(
                PrinciplesGateBlockLog.ticker == "005930"
            )
        )).scalars().all()
        assert len(logs) == 1
        assert logs[0].reason == "principles_fail_closed"
        assert logs[0].source == "super_signal"
        assert logs[0].run_id is not None


@pytest.mark.asyncio
async def test_9_bypass_logged_and_persisted(caplog):
    """보완 (2026-08-23) · bypass 시 INFO 로그 + BlockLog reason='whitelist_bypass' 저장."""
    import logging as _logging
    async with get_session() as s:
        await _insert_run(s, finished=True, hours_ago=1.0)
        await s.commit()
    checker = PrinciplesGateChecker()
    with caplog.at_level(_logging.INFO, logger="backend.execution.principles_gate"):
        r = await checker.check(ticker="005930", source="sniper")
    assert r.passed is True and r.bypass is True
    # INFO 로그 실증
    assert any("whitelist_bypass" in rc.message for rc in caplog.records)
    # BlockLog 저장 실증 (reason="whitelist_bypass")
    async with get_session() as s:
        logs = (await s.execute(
            select(PrinciplesGateBlockLog).where(
                PrinciplesGateBlockLog.reason == "whitelist_bypass"
            )
        )).scalars().all()
        assert len(logs) == 1
        assert logs[0].ticker == "005930"
        assert logs[0].source == "sniper"


@pytest.mark.asyncio
async def test_10_direct_call_source_via_router_still_bypasses():
    """9. sniper source 는 라우터 경유 시에도 우회 (미래 통합 대비 안전장치)."""
    async with get_session() as s:
        # PASS 리스트 없이도 sniper 는 우회
        await _insert_run(s, finished=True, hours_ago=1.0)
        await s.commit()
    checker = PrinciplesGateChecker()
    r = await checker.check(ticker="ANY_TICKER", source="sniper")
    assert r.passed is True
    assert r.bypass is True
