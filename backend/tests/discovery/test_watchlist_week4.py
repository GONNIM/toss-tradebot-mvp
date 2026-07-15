"""Watchlist Week 4 · Sprint 2 T68·T69·T70 테스트.

- 시뮬 러너 · 갭업/상투/미갭업/청산 시나리오
- 메트릭 · win_rate·avg·MDD 정확도
- DoD · pass/fail 판정
- /watchlist/report API
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ["SNIPER_API_TOKEN"] = "test_token_32chars_00000000000000"

from backend.discovery.live_tape.params import SniperParams
from backend.discovery.watchlist.metrics import (
    Trade,
    compute_metrics,
    evaluate_dod,
)
from backend.discovery.watchlist.simulator import (
    DayScenario,
    SimTickerBar,
    simulate,
)
from backend.services.db import get_session, init_db
from backend.services.models import SniperSignal


# ═══════════════════════════════════════════════════════════════
# T69 · Metrics
# ═══════════════════════════════════════════════════════════════
def test_metrics_empty():
    m = compute_metrics([])
    assert m.total_trades == 0
    assert m.win_rate == 0.0


def test_metrics_all_wins():
    trades = [
        Trade("A", 100, 110),   # +10%
        Trade("B", 100, 105),   # +5%
        Trade("C", 100, 103),   # +3%
    ]
    m = compute_metrics(trades)
    assert m.total_trades == 3
    assert m.wins == 3
    assert m.losses == 0
    assert m.win_rate == 1.0
    assert m.max_win_pct == pytest.approx(0.10)
    assert m.avg_win_pct == pytest.approx(0.06, abs=0.001)
    # MDD 0 (계속 상승)
    assert m.mdd_pct == 0.0


def test_metrics_mixed_and_mdd():
    trades = [
        Trade("A", 100, 105),   # +5%
        Trade("B", 100, 95),    # -5%
        Trade("C", 100, 110),   # +10%
        Trade("D", 100, 90),    # -10%
    ]
    m = compute_metrics(trades)
    assert m.total_trades == 4
    assert m.wins == 2
    assert m.losses == 2
    assert m.win_rate == 0.5
    # equity: 1.0 → 1.05 → 0.9975 → 1.09725 → 0.98753
    # peak = 1.09725, trough = 0.98753 → drawdown ≈ -10%
    assert m.mdd_pct < -0.09 and m.mdd_pct > -0.11


def test_metrics_rr_ratio():
    trades = [
        Trade("A", 100, 110),   # +10%
        Trade("B", 100, 95),    # -5%
    ]
    m = compute_metrics(trades)
    # avg_win = 0.10, avg_loss = -0.05 → RR = 2.0
    assert m.r_r_ratio == pytest.approx(2.0, abs=0.01)


# ═══════════════════════════════════════════════════════════════
# T70 · DoD 판정
# ═══════════════════════════════════════════════════════════════
def test_dod_all_pass():
    trades = [
        Trade("A", 100, 108),   # +8%
        Trade("B", 100, 106),   # +6%
        Trade("C", 100, 105),   # +5%
        Trade("D", 100, 98),    # -2%
        Trade("E", 100, 97),    # -3%
    ]
    m = compute_metrics(trades)
    dod = evaluate_dod(m)
    # win_rate = 3/5 = 60% >= 45%
    # r_r = 6.33% / 2.5% ≈ 2.53
    # MDD 작음
    # total_trades = 5
    assert dod.total_pass is True
    assert all(c.passed for c in dod.checks)


def test_dod_fails_on_low_win_rate():
    trades = [
        Trade("A", 100, 90),    # -10%
        Trade("B", 100, 92),    # -8%
        Trade("C", 100, 105),   # +5%
        Trade("D", 100, 88),    # -12%
        Trade("E", 100, 93),    # -7%
    ]
    m = compute_metrics(trades)
    dod = evaluate_dod(m)
    assert dod.total_pass is False
    win_rate_check = next(c for c in dod.checks if c.name == "win_rate")
    assert win_rate_check.passed is False


def test_dod_fails_on_insufficient_trades():
    trades = [Trade("A", 100, 110)]   # 단 1건
    m = compute_metrics(trades)
    dod = evaluate_dod(m)
    assert dod.total_pass is False
    min_check = next(c for c in dod.checks if c.name == "min_trades")
    assert min_check.passed is False


# ═══════════════════════════════════════════════════════════════
# T68 · Simulator
# ═══════════════════════════════════════════════════════════════
def _default_params() -> SniperParams:
    p = SniperParams()
    p.watchlist_gap_min_pct = 0.005
    p.watchlist_gap_max_pct = 0.05
    p.watchlist_min_composite_score = 1.0
    p.trailing_giveback_pct = 0.03
    p.hard_stop_loss_pct = -0.03
    return p


def test_simulator_gap_up_target_hit():
    """+2% 갭업 · intraday_high 1080 (+5.9%) · trailing target(4.5%) 달성."""
    params = _default_params()
    day = DayScenario("2026-07-14", [
        SimTickerBar(
            ticker="005930", composite_score=1.5,
            prev_close=1000, open_price=1020,      # +2% gap
            intraday_high=1080, intraday_low=1010, # peak +5.9% from entry
            close_price=1050,
        )
    ])
    summary = simulate([day], params)
    assert summary.entries == 1
    assert len(summary.trades) == 1
    trade = summary.trades[0]
    assert trade.reason == "trailing_target"
    # exit = peak (1080) × (1 - giveback 0.03) = 1047.6
    assert trade.exit_price == pytest.approx(1047.6, abs=0.5)
    assert trade.pnl_pct > 0


def test_simulator_hard_sl_hit():
    """+2% 갭업 후 intraday_low -3% · hard SL."""
    params = _default_params()
    day = DayScenario("2026-07-14", [
        SimTickerBar(
            ticker="005930", composite_score=1.5,
            prev_close=1000, open_price=1020,
            intraday_high=1025, intraday_low=989,     # -3.03% from 1020
            close_price=990,
        )
    ])
    summary = simulate([day], params)
    trade = summary.trades[0]
    assert trade.reason in ("hard_sl", "hard_sl_before_target")
    assert trade.pnl_pct < 0


def test_simulator_force_close():
    """+2% 갭업 · intraday 미만 · close 종가 청산."""
    params = _default_params()
    day = DayScenario("2026-07-14", [
        SimTickerBar(
            ticker="005930", composite_score=1.5,
            prev_close=1000, open_price=1020,
            intraday_high=1030, intraday_low=1015,   # 목표·손절 모두 미달
            close_price=1025,
        )
    ])
    summary = simulate([day], params)
    trade = summary.trades[0]
    assert trade.reason == "force_close"
    assert trade.exit_price == 1025


def test_simulator_rejects_상투():
    """+8% 갭업 · 상투 배제 · 진입 0."""
    params = _default_params()
    day = DayScenario("2026-07-14", [
        SimTickerBar(
            ticker="005930", composite_score=1.5,
            prev_close=1000, open_price=1080,   # +8%
            intraday_high=1090, intraday_low=1050,
            close_price=1070,
        )
    ])
    summary = simulate([day], params)
    assert summary.entries == 0
    reasons = list(summary.rejected.keys())
    assert any("상투" in r or "gap_above_max" in r for r in reasons)


def test_simulator_5_day_forward_test():
    """5거래일 시뮬 · 승률·DoD 요약 흐름 통합 검증."""
    params = _default_params()
    scenarios = []
    # 5일 · 승·승·패·승·패 = 3승 2패 → win_rate 60%
    outcomes = [
        (1060, 1010, 1050),   # win (target)
        (1055, 1020, 1050),   # win (target: peak 1055 × 0.97 = 1023 → net +0.3%)
        (1030, 989, 990),     # loss (SL from 1020)
        (1058, 1015, 1045),   # win (target)
        (1030, 989, 995),     # loss (SL)
    ]
    for i, (hi, lo, cl) in enumerate(outcomes):
        scenarios.append(DayScenario(f"2026-07-{14+i:02d}", [
            SimTickerBar(
                ticker=f"00593{i}", composite_score=1.5,
                prev_close=1000, open_price=1020,
                intraday_high=hi, intraday_low=lo, close_price=cl,
            )
        ]))
    summary = simulate(scenarios, params)
    assert summary.entries == 5
    m = compute_metrics(summary.trades)
    assert m.total_trades == 5
    assert m.wins >= 2
    # DoD 판정 실행 · 결과는 시나리오에 따라 달라짐
    dod = evaluate_dod(m)
    assert len(dod.checks) == 4


# ═══════════════════════════════════════════════════════════════
# T70 · API
# ═══════════════════════════════════════════════════════════════
@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(SniperSignal))
    yield


@pytest_asyncio.fixture
async def api_client():
    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _seed_signals(closed_trades: list[tuple[str, float, float, str]]):
    async with get_session() as session:
        now = datetime.now(tz=timezone.utc)
        for ticker, entry, exitp, reason in closed_trades:
            session.add(SniperSignal(
                ticker=ticker,
                detected_at=now,
                tape_score=1.5,
                rank_velocity=0.0,
                trades_intensity=0.0,
                orderbook_imbalance=0.0,
                entry_order_uuid="uuid-" + ticker,
                entry_price=entry,
                exit_order_uuid="uuid-exit-" + ticker,
                exit_price=exitp,
                peak_price=max(entry, exitp),
                reason=reason,
            ))


@pytest.mark.asyncio
async def test_report_api_empty(api_client):
    resp = await api_client.get("/api/v1/watchlist/report")
    assert resp.status_code == 200
    body = resp.json()
    assert body["closed_trades"] == 0
    assert body["metrics"]["total_trades"] == 0
    assert body["total_pass"] is False   # min_trades 미달


@pytest.mark.asyncio
async def test_report_api_with_signals_shows_metrics(api_client):
    await _seed_signals([
        ("A", 100, 108, "trailing_target"),
        ("B", 100, 106, "trailing_target"),
        ("C", 100, 105, "trailing_target"),
        ("D", 100, 98, "hard_sl"),
        ("E", 100, 97, "hard_sl"),
    ])
    resp = await api_client.get("/api/v1/watchlist/report?days=30")
    body = resp.json()
    assert body["closed_trades"] == 5
    assert body["metrics"]["total_trades"] == 5
    assert body["metrics"]["wins"] == 3
    assert 0 < body["metrics"]["win_rate"] <= 1.0
    assert body["total_pass"] is True   # 3승 2패 · 60% · MDD 작음
