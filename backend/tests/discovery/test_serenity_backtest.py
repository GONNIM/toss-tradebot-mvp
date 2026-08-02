"""Serenity Backtest 단위 테스트 · Phase L5 · 2026-08-02.

yfinance mock (ticker_client 주입) · pending 조회·persist·race.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pandas as pd

from backend.discovery.serenity.backtest import (
    backtest_signal,
    load_pending_signals,
    refresh_backtests,
)
from backend.services.db import get_session, init_db
from backend.services.models import SerenityBacktest, SerenitySignal
from backend.services.ticker_map import to_yfinance_symbol


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(SerenityBacktest))
        await session.execute(delete(SerenitySignal))
    yield


def _make_signal(sid: str, ticker: str, days_ago: int = 30) -> SerenitySignal:
    return SerenitySignal(
        id=sid,
        tweet_id=int(sid.split("-")[0][:10], 16) if "-" in sid else 1,
        ticker=ticker,
        sentiment="bullish",
        confidence=0.9,
        extracted_at=datetime.utcnow() - timedelta(days=days_ago),
    )


def _fake_ticker(history_df: pd.DataFrame):
    """yf.Ticker(symbol).history(start, end) mock 객체."""
    obj = SimpleNamespace()
    obj.history = MagicMock(return_value=history_df)
    return obj


def _fake_client(history_df: pd.DataFrame):
    """backtest_signal 의 ticker_client 인자용 · 콜러블."""
    return MagicMock(return_value=_fake_ticker(history_df))


# ─── ticker_map ────────────────────────────────────────────────


def test_ticker_map_stockholm():
    assert to_yfinance_symbol("SIVE") == "SIVE.ST"


def test_ticker_map_kq_to_ks():
    assert to_yfinance_symbol("138080.KQ") == "138080.KS"
    assert to_yfinance_symbol("999999.KQ") == "999999.KS"   # 규칙 자동 승격


def test_ticker_map_passthrough_uppercase():
    assert to_yfinance_symbol("nbis") == "NBIS"


# ─── backtest_signal (mock yfinance) ─────────────────────────


def test_backtest_signal_computes_returns():
    """200일 시계열 · 5·10·30·60·180 return 정확 계산."""
    prices = [100.0 + i * 0.5 for i in range(200)]  # 매일 +0.5
    idx = pd.date_range("2026-01-01", periods=200, freq="D")
    df = pd.DataFrame({"Close": prices}, index=idx)

    signal = {
        "id": str(uuid.uuid4()),
        "ticker": "NBIS",
        "extracted_at": datetime(2026, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None),
    }
    out = backtest_signal(signal, ticker_client=_fake_client(df))
    assert out is not None
    assert out["ticker"] == "NBIS"
    assert out["signal_date"] == "2026-01-01"
    assert out["price_at_signal"] == 100.0
    # +5일 후 close=102.5 → return = 2.5%
    assert out["return_5d"] == 2.5
    assert out["return_10d"] == 5.0
    assert out["return_30d"] == 15.0
    assert out["return_60d"] == 30.0
    assert out["return_180d"] == 90.0


def test_backtest_signal_short_history_returns_none_missing_windows():
    """20일치만 · 30/60/180 은 None."""
    idx = pd.date_range("2026-01-01", periods=20, freq="D")
    df = pd.DataFrame({"Close": [100.0] * 20}, index=idx)

    signal = {"id": "x", "ticker": "AXTI", "extracted_at": datetime(2026, 1, 1)}
    out = backtest_signal(signal, ticker_client=_fake_client(df))
    assert out["return_5d"] == 0.0
    assert out["return_10d"] == 0.0
    assert out["return_30d"] is None
    assert out["return_60d"] is None
    assert out["return_180d"] is None


def test_backtest_signal_empty_history_returns_none():
    df = pd.DataFrame({"Close": []})
    signal = {"id": "x", "ticker": "AAOI", "extracted_at": datetime(2026, 1, 1)}
    assert backtest_signal(signal, ticker_client=_fake_client(df)) is None


def test_backtest_signal_history_exception_returns_none():
    """yfinance history() 예외 시 None (에러 전파 X)."""
    def _client(_symbol):
        obj = SimpleNamespace()
        obj.history = MagicMock(side_effect=RuntimeError("rate limit"))
        return obj

    signal = {"id": "x", "ticker": "AAOI", "extracted_at": datetime(2026, 1, 1)}
    assert backtest_signal(signal, ticker_client=_client) is None


def test_backtest_signal_maps_symbol_before_call():
    """SIVE → SIVE.ST 로 yfinance 호출됨."""
    captured = {}

    def _client(symbol):
        captured["symbol"] = symbol
        idx = pd.date_range("2026-01-01", periods=10, freq="D")
        df = pd.DataFrame({"Close": [100.0] * 10}, index=idx)
        return _fake_ticker(df)

    signal = {"id": "x", "ticker": "SIVE", "extracted_at": datetime(2026, 1, 1)}
    backtest_signal(signal, ticker_client=_client)
    assert captured["symbol"] == "SIVE.ST"


# ─── load_pending_signals ────────────────────────────────────


@pytest.mark.asyncio
async def test_load_pending_excludes_backtested():
    async with get_session() as session:
        session.add_all([
            _make_signal("aaa", "NBIS"),
            _make_signal("bbb", "AXTI"),
        ])
        session.add(SerenityBacktest(
            id=str(uuid.uuid4()), signal_id="aaa", ticker="NBIS",
            signal_date="2026-01-01",
        ))
        await session.commit()

    pending = await load_pending_signals(limit=10)
    assert [p["id"] for p in pending] == ["bbb"]


# ─── refresh_backtests · 통합 ────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_backtests_inserts_and_counts():
    async with get_session() as session:
        session.add_all([
            _make_signal("s1", "NBIS"),
            _make_signal("s2", "AXTI"),
        ])
        await session.commit()

    idx = pd.date_range("2026-01-01", periods=200, freq="D")
    df = pd.DataFrame({"Close": [100.0 + i for i in range(200)]}, index=idx)
    result = await refresh_backtests(batch_size=10, concurrency=2, ticker_client=_fake_client(df))
    assert result == {"pending": 2, "computed": 2, "failed": 0}

    async with get_session() as session:
        n = (await session.execute(select(func.count(SerenityBacktest.id)))).scalar_one()
    assert n == 2


@pytest.mark.asyncio
async def test_refresh_backtests_failed_counted_when_history_empty():
    async with get_session() as session:
        session.add(_make_signal("s3", "UNKNOWN"))
        await session.commit()

    df = pd.DataFrame({"Close": []})
    result = await refresh_backtests(batch_size=10, concurrency=1, ticker_client=_fake_client(df))
    assert result["pending"] == 1
    assert result["computed"] == 0
    assert result["failed"] == 1


@pytest.mark.asyncio
async def test_refresh_backtests_no_pending():
    result = await refresh_backtests(batch_size=10, concurrency=1)
    assert result == {"pending": 0, "computed": 0, "failed": 0}
