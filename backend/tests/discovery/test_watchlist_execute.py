"""Watchlist 개장 실행 · Sprint 2 Week 3 T64·T65·T66·T67 Contract Test.

시나리오:
  1. 갭업 진입 성공 · 조건 통과
  2. 갭업 초과 (상투) · 진입 거부
  3. 갭 부족 (미갭업) · 진입 거부
  4. rankings_confirm 활성 · rankings 미매치 → 거부
  5. rankings_confirm 활성 · rankings 매치 → 통과
  6. min_composite_score 미달 · 배제
  7. watchlist_execute_enabled=False · 즉시 skip
  8. 활성창 밖 · 즉시 skip (force_window=True 로 우회)
  9. Watchlist 비어있음 · skip
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.discovery.live_tape.params import SniperParamsStore
from backend.discovery.watchlist import execute as ex_mod
from backend.discovery.watchlist.execute import (
    compute_gap_pct,
    execute_watchlist_scan,
)
from backend.execution.brokers.paper_adapter import PaperAdapter
from backend.execution.kill_switch import KillSwitch, get_kill_switch
from backend.tests.discovery.conftest import SniperFakeTossClient
from backend.services.db import get_session, init_db
from backend.services.models import (
    LiveTapeUniverse,
    OrderAudit,
    SniperSignal,
    Watchlist,
    WatchlistSignal,
)


TRADE_DATE = datetime.now(tz=timezone(timedelta(hours=9))).date().isoformat()


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(WatchlistSignal))
        await session.execute(delete(Watchlist))
        await session.execute(delete(LiveTapeUniverse))
        await session.execute(delete(SniperSignal))
        await session.execute(delete(OrderAudit))
    # Kill Switch 리셋 (테스트 격리)
    ks = get_kill_switch()
    if ks.is_active():
        ks.deactivate(actor="test")
    yield


@pytest_asyncio.fixture
async def stubbed_adapter(tmp_path, monkeypatch):
    """PaperAdapter · SniperFakeTossClient · 실 HTTP 우회.

    execute._resolve_order_manager 를 이 stub 으로 replace.
    """
    fake_toss = SniperFakeTossClient(prices={})
    state_path = tmp_path / "paper_state.json"

    def _factory(prices: dict[str, float]) -> PaperAdapter:
        fake_toss._prices.update(prices)
        # 새 KillSwitch (프로세스 싱글턴 격리 위해 factory 마다 새로)
        ks = KillSwitch()
        adapter = PaperAdapter(
            toss_client=fake_toss,
            kill_switch=ks,
            state_path=state_path,
            fx_usd_krw=1370.0,
        )
        # 시드 자본 주입 (params.seed_cap_krw 와 정합)
        adapter.reset(cash_krw=1_000_000)
        return adapter
    return {"factory": _factory, "toss": fake_toss}


@pytest_asyncio.fixture
async def isolated_params(tmp_path, monkeypatch):
    """격리된 SniperParams · watchlist_execute 활성."""
    store = SniperParamsStore(path=tmp_path / "sniper_params.json")
    params = store.get()
    # 실행 관련 · watchlist 활성 · sniper.enabled True (execute_entry 통과 위해)
    store.patch({
        "enabled": True,
        "watchlist_execute_enabled": True,
        "watchlist_gap_min_pct": 0.005,
        "watchlist_gap_max_pct": 0.05,
        "watchlist_min_composite_score": 1.0,
        "watchlist_use_rankings_confirm": False,
        # execute_entry 통과 위한 active_window 는 항상 (00:00~23:59)
        "active_start_kst": "00:00",
        "active_end_kst": "23:59",
        "seed_cap_krw": 1_000_000,
        "per_order_krw": 100_000,
    })
    import backend.discovery.live_tape.params as p_mod
    monkeypatch.setattr(p_mod, "_store", store)
    return store


async def _seed_ticker(ticker: str, name: str, prev_close: float):
    async with get_session() as session:
        session.add(LiveTapeUniverse(
            ticker=ticker, name=name, market="KOSDAQ",
            dept=None, close_price=prev_close, market_cap_krw=100_000_000_000,
            shares=1_000_000, amount_today=1_000_000_000,
            amount_20d_avg=None, is_squeeze_candidate=False,
            refreshed_at=datetime.now(tz=timezone.utc),
        ))


def _stub_warnings(monkeypatch):
    """execute_entry 내부 check_warnings 를 통과시키기."""
    from dataclasses import dataclass

    @dataclass
    class _WarnStub:
        blocked: bool = False
        active_types: list = None
        def __post_init__(self):
            if self.active_types is None:
                self.active_types = []

    async def _stub(ticker):
        return _WarnStub()

    import backend.discovery.live_tape.entry as entry_mod
    monkeypatch.setattr(entry_mod, "check_warnings", _stub)


async def _seed_watchlist(ticker: str, name: str, composite: float, rank: int = 1):
    async with get_session() as session:
        session.add(Watchlist(
            trade_date=TRADE_DATE, ticker=ticker, name=name,
            rank=rank, composite_score=composite,
            news_score=0, board_score=0, youtube_score=0,
            event_score=0, prev_day_score=0,
            source_breakdown=None, locked=False, added_by="auto",
        ))


# ─── 기본 도우미 ──────────────────────────────
def test_compute_gap_pct():
    assert compute_gap_pct(102.0, 100.0) == pytest.approx(0.02)
    assert compute_gap_pct(100.0, 100.0) == pytest.approx(0.0)
    assert compute_gap_pct(100.0, 0) is None
    assert compute_gap_pct(100.0, -1) is None


# ─── 시나리오 테스트 ──────────────────────────
@pytest.mark.asyncio
async def test_scenario_1_gap_up_enters_successfully(isolated_params, stubbed_adapter, monkeypatch):
    """갭업 +2% · 통과 · 매수 성공."""
    await _seed_ticker("005930", "삼성전자", prev_close=1000.0)
    await _seed_watchlist("005930", "삼성전자", composite=1.5)

    # 가격 stub: 1020 (+2%)
    async def _stub_prices(tickers):
        return {"005930": 1020.0}
    monkeypatch.setattr(ex_mod, "fetch_current_prices", _stub_prices)
    # OrderManager stub
    om = stubbed_adapter["factory"]({"005930": 1020.0})
    monkeypatch.setattr(ex_mod, "_resolve_order_manager", lambda: om)
    # warnings stub (Toss API 401 회피)
    _stub_warnings(monkeypatch)

    stats = await execute_watchlist_scan(force_window=True)
    assert stats["entered"] == 1
    cand = stats["candidates"][0]
    assert cand["ticker"] == "005930"
    assert cand["gap_pct"] == pytest.approx(0.02)
    assert cand["reject_reason"] is None


@pytest.mark.asyncio
async def test_scenario_2_gap_above_max_rejects_상투(isolated_params, monkeypatch):
    """갭업 +8% · 상투 배제."""
    await _seed_ticker("005930", "삼성전자", prev_close=1000.0)
    await _seed_watchlist("005930", "삼성전자", composite=1.5)

    async def _stub_prices(tickers):
        return {"005930": 1080.0}   # +8%
    monkeypatch.setattr(ex_mod, "fetch_current_prices", _stub_prices)

    stats = await execute_watchlist_scan(force_window=True)
    assert stats["entered"] == 0
    reject_keys = list(stats["rejects"].keys())
    assert any("상투" in k or "gap_above_max" in k for k in reject_keys)


@pytest.mark.asyncio
async def test_scenario_3_gap_below_min_rejects(isolated_params, monkeypatch):
    """갭 0.1% · 미갭업 배제."""
    await _seed_ticker("005930", "삼성전자", prev_close=1000.0)
    await _seed_watchlist("005930", "삼성전자", composite=1.5)

    async def _stub_prices(tickers):
        return {"005930": 1001.0}   # +0.1%
    monkeypatch.setattr(ex_mod, "fetch_current_prices", _stub_prices)

    stats = await execute_watchlist_scan(force_window=True)
    assert stats["entered"] == 0
    assert any("gap_below_min" in k for k in stats["rejects"].keys())


@pytest.mark.asyncio
async def test_scenario_4_rankings_confirm_missing_rejects(isolated_params, monkeypatch):
    """rankings_confirm=True · 매치 실패 → 거부."""
    isolated_params.patch({"watchlist_use_rankings_confirm": True})
    await _seed_ticker("005930", "삼성전자", prev_close=1000.0)
    await _seed_watchlist("005930", "삼성전자", composite=1.5)

    async def _stub_prices(tickers):
        return {"005930": 1020.0}
    monkeypatch.setattr(ex_mod, "fetch_current_prices", _stub_prices)

    async def _stub_ranks(window_sec=600):
        return []   # rankings 매치 없음
    monkeypatch.setattr(ex_mod, "tickers_with_snapshots", _stub_ranks)

    stats = await execute_watchlist_scan(force_window=True)
    assert stats["entered"] == 0
    assert stats["rejects"].get("rankings_confirm_missing", 0) == 1


@pytest.mark.asyncio
async def test_scenario_5_rankings_confirm_present_passes(isolated_params, stubbed_adapter, monkeypatch):
    """rankings_confirm=True · 매치 성공 → 통과."""
    isolated_params.patch({"watchlist_use_rankings_confirm": True})
    await _seed_ticker("005930", "삼성전자", prev_close=1000.0)
    await _seed_watchlist("005930", "삼성전자", composite=1.5)

    async def _stub_prices(tickers):
        return {"005930": 1020.0}
    monkeypatch.setattr(ex_mod, "fetch_current_prices", _stub_prices)

    async def _stub_ranks(window_sec=600):
        return ["005930", "000660"]
    monkeypatch.setattr(ex_mod, "tickers_with_snapshots", _stub_ranks)

    om = stubbed_adapter["factory"]({"005930": 1020.0})
    monkeypatch.setattr(ex_mod, "_resolve_order_manager", lambda: om)
    _stub_warnings(monkeypatch)

    stats = await execute_watchlist_scan(force_window=True)
    assert stats["entered"] == 1
    assert stats["candidates"][0]["in_rankings"] is True


@pytest.mark.asyncio
async def test_scenario_6_below_min_score_excluded(isolated_params, monkeypatch):
    """composite_score < 1.0 · watchlist 있어도 스캔 배제."""
    await _seed_ticker("005930", "삼성전자", prev_close=1000.0)
    await _seed_watchlist("005930", "삼성전자", composite=0.5)   # 0.5 < 1.0

    async def _stub_prices(tickers):
        return {"005930": 1020.0}
    monkeypatch.setattr(ex_mod, "fetch_current_prices", _stub_prices)

    stats = await execute_watchlist_scan(force_window=True)
    assert stats["entered"] == 0
    assert stats["rejects"].get("below_min_score", 0) == 1


@pytest.mark.asyncio
async def test_scenario_7_execute_disabled_skips(isolated_params, monkeypatch):
    """watchlist_execute_enabled=False · 즉시 skip."""
    isolated_params.patch({"watchlist_execute_enabled": False})
    stats = await execute_watchlist_scan(force_window=True)
    assert stats.get("skipped_reason") == "watchlist_execute_disabled"


@pytest.mark.asyncio
async def test_scenario_9_empty_watchlist_skips(isolated_params):
    """Watchlist 비어있으면 skip."""
    stats = await execute_watchlist_scan(force_window=True)
    assert stats.get("skipped_reason") == "empty_watchlist"


@pytest.mark.asyncio
async def test_scheduler_registers_execute_job():
    """T64 스케줄러 잡 등록 확인."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from backend.discovery.watchlist.scheduler import register_watchlist_jobs

    scheduler = AsyncIOScheduler()
    register_watchlist_jobs(scheduler)
    ids = {j.id for j in scheduler.get_jobs()}
    assert "watchlist_execute" in ids
