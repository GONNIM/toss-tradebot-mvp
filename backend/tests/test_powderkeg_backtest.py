"""P7-4 백테스트 · CAR + validation 게이트 테스트."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.powderkeg import backtest as bt_mod
from backend.powderkeg import event_study as es_mod
from backend.powderkeg.backtest import (
    GATE_WINDOWS,
    MIN_SAMPLES,
    ValidationDecision,
    apply_validation,
    evaluate_validation,
    run_backtest_for_event_type,
    run_event_study_from_db,
)
from backend.powderkeg.event_study import (
    WINDOW_DAYS,
    AggregatedResult,
    SingleEventReturn,
    WindowStats,
    aggregate_returns,
    compute_event_return,
)
from backend.services.db import get_session, init_db
from backend.services.models import PowderKegEvent


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(PowderKegEvent))
    yield


# ─── event_study.aggregate_returns ─────────
def test_aggregate_with_mixed_wins_and_losses():
    returns = [
        SingleEventReturn(ticker="A", event_date="2026-01-01", entry_date="2026-01-02",
                          entry_price=100, per_window_returns={"1m": 0.10, "3m": 0.20}),
        SingleEventReturn(ticker="B", event_date="2026-01-01", entry_date="2026-01-02",
                          entry_price=100, per_window_returns={"1m": -0.05, "3m": 0.05}),
        SingleEventReturn(ticker="C", event_date="2026-01-01", entry_date="2026-01-02",
                          entry_price=100, per_window_returns={"1m": 0.03, "3m": -0.02}),
    ]
    agg = aggregate_returns("A3", returns, windows={"1m": 21, "3m": 63})
    assert agg.total_events == 3
    assert agg.valid_events == 3

    w1m = agg.per_window["1m"]
    assert w1m.n == 3
    assert w1m.mean_return == pytest.approx((0.10 - 0.05 + 0.03) / 3, rel=1e-3)
    assert w1m.win_rate == pytest.approx(2 / 3, abs=0.001)


def test_aggregate_handles_missing_and_errors():
    returns = [
        SingleEventReturn(ticker="A", event_date="2026-01-01",
                          entry_date=None, entry_price=None, error="no_price_data"),
        SingleEventReturn(ticker="B", event_date="2026-01-01",
                          entry_date="2026-01-02", entry_price=100,
                          per_window_returns={"1m": 0.10, "3m": None}),
    ]
    agg = aggregate_returns("B1", returns, windows={"1m": 21, "3m": 63})
    assert agg.valid_events == 1
    assert agg.error_counts.get("no_price_data") == 1
    assert agg.per_window["1m"].n == 1
    assert "3m" not in agg.per_window   # 값 없음 · window 자체 미생성


# ─── evaluate_validation ─────────────────
def _make_agg(event_type: str, n: int, mean: float, std: float, win: float,
              window="1m") -> AggregatedResult:
    import math
    t_stat = (mean / (std / math.sqrt(n))) if std > 0 else 0.0
    return AggregatedResult(
        event_type=event_type, total_events=n, valid_events=n,
        per_window={window: WindowStats(
            label=window, n=n, mean_return=mean, median_return=mean,
            win_rate=win, std=std, t_stat=t_stat,
            max_return=mean * 3, min_return=-mean,
        )},
    )


def test_validation_fails_low_samples():
    agg = _make_agg("A3", n=10, mean=0.05, std=0.10, win=0.7)
    d = evaluate_validation(agg)
    assert d.validated is False
    assert any("insufficient_samples" in r for r in d.reasons)


def test_validation_fails_low_t_stat():
    # n=60 · mean=0.001 · std=0.10 → t=0.077 · 미달
    agg = _make_agg("A3", n=60, mean=0.001, std=0.10, win=0.55)
    d = evaluate_validation(agg)
    assert d.validated is False
    assert any("t_stat" in r for r in d.reasons)


def test_validation_passes():
    """n=100 · mean=0.05 · std=0.10 → t=5.0 · win=0.65 · pass."""
    agg = _make_agg("A3", n=100, mean=0.05, std=0.10, win=0.65)
    d = evaluate_validation(agg)
    assert d.validated is True
    assert d.passing_window == "1m"


def test_validation_negative_mean_fails():
    agg = _make_agg("A3", n=100, mean=-0.02, std=0.10, win=0.45)
    d = evaluate_validation(agg)
    assert d.validated is False


# ─── apply_validation ─────────────────
@pytest.mark.asyncio
async def test_apply_validation_updates_all_matching():
    async with get_session() as session:
        for i in range(3):
            session.add(PowderKegEvent(
                ticker=f"00000{i}", event_type="A3", source="dart",
                source_id=f"id{i}", title="담보제공",
            ))
        session.add(PowderKegEvent(
            ticker="999999", event_type="B1", source="dart",
            source_id="idb", title="횡령",
        ))

    d = ValidationDecision(event_type="A3", validated=True, passing_window="1m")
    updated = await apply_validation("A3", d)
    assert updated == 3

    async with get_session() as session:
        a3 = (await session.execute(
            select(PowderKegEvent).where(PowderKegEvent.event_type == "A3")
        )).scalars().all()
        b1 = (await session.execute(
            select(PowderKegEvent).where(PowderKegEvent.event_type == "B1")
        )).scalar_one()
    assert all(e.validated for e in a3)
    assert b1.validated is False   # B1 은 미영향


@pytest.mark.asyncio
async def test_apply_validation_skips_when_not_validated():
    async with get_session() as session:
        session.add(PowderKegEvent(
            ticker="005930", event_type="A3", source="dart",
            source_id="id", title="담보",
        ))
    d = ValidationDecision(event_type="A3", validated=False)
    updated = await apply_validation("A3", d)
    assert updated == 0


# ─── run_backtest_for_event_type 통합 ───
@pytest.mark.asyncio
async def test_run_backtest_stubs_fdr_and_computes(monkeypatch):
    """FDR stub · 3 이벤트 · 백테스트 흐름."""
    async with get_session() as session:
        for i, ret in enumerate([0.15, 0.10, 0.05]):
            session.add(PowderKegEvent(
                ticker=f"AAA00{i}", event_type="A5", source="dart",
                source_id=f"id{i}", title="자사주 소각",
                release_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ))

    # compute_event_return 대체 · 항상 양수 수익률
    async def _stub_compute(ticker, event_date, windows=WINDOW_DAYS, extra_padding_days=30):
        # ticker 별 다른 수익률 반환
        ret_map = {"AAA000": 0.15, "AAA001": 0.10, "AAA002": 0.05}
        r = ret_map.get(ticker, 0.0)
        return SingleEventReturn(
            ticker=ticker, event_date=event_date.isoformat(),
            entry_date=(event_date + timedelta(days=1)).isoformat(),
            entry_price=100.0,
            per_window_returns={label: r for label in windows},
        )
    monkeypatch.setattr(bt_mod, "compute_event_return", _stub_compute)

    report = await run_backtest_for_event_type("A5")
    assert report["event_type"] == "A5"
    assert report["aggregate"]["valid_events"] == 3
    # 3 표본 · MIN_SAMPLES 50 미달 → not validated
    assert report["decision"]["validated"] is False
    assert any("insufficient_samples" in r for r in report["decision"]["reasons"])
    assert report["updated_rows"] == 0


@pytest.mark.asyncio
async def test_run_backtest_validates_when_gate_passes(monkeypatch):
    """55 이벤트 · 강한 양수 · gate 통과."""
    async with get_session() as session:
        for i in range(55):
            session.add(PowderKegEvent(
                ticker=f"BB{i:04d}", event_type="A3", source="dart",
                source_id=f"idA3-{i}", title="담보",
                release_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ))

    async def _stub_compute(ticker, event_date, windows=WINDOW_DAYS, extra_padding_days=30):
        # 승률 70% · 평균 5% · std 낮게
        i = int(ticker[-4:])
        r = 0.05 if i % 10 < 7 else -0.03
        return SingleEventReturn(
            ticker=ticker, event_date=event_date.isoformat(),
            entry_date=(event_date + timedelta(days=1)).isoformat(),
            entry_price=100.0,
            per_window_returns={label: r for label in windows},
        )
    monkeypatch.setattr(bt_mod, "compute_event_return", _stub_compute)

    report = await run_backtest_for_event_type("A3")
    assert report["aggregate"]["valid_events"] == 55
    # 55 >= 50 · 통과 예상 (승률 70% · mean 양수 · t-stat 매우 큼)
    assert report["decision"]["validated"] is True
    assert report["updated_rows"] == 55


# ─── compute_event_return · 안전성 ────────
@pytest.mark.asyncio
async def test_compute_returns_error_when_no_fdr(monkeypatch):
    """FinanceDataReader import 실패 · 안전 반환."""
    import sys, builtins
    orig_import = builtins.__import__
    def _blocked(name, *a, **kw):
        if name == "FinanceDataReader":
            raise ImportError("blocked for test")
        return orig_import(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", _blocked)
    if "FinanceDataReader" in sys.modules:
        monkeypatch.delitem(sys.modules, "FinanceDataReader", raising=False)

    r = await compute_event_return("005930", date(2026, 1, 1))
    assert r.error == "fdr_not_installed"
    assert r.entry_price is None
