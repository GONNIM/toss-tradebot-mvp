"""backtest.py v6 · entry_next_open + gap + delisting + raw return 검증."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.discovery.serenity import backtest as bt_mod


class _FakeTicker:
    """yfinance.Ticker mock."""

    def __init__(self, hist_df: pd.DataFrame):
        self._hist = hist_df

    def history(self, start=None, end=None):
        return self._hist


def _make_hist_from_prices(start_date, closes, opens=None):
    dates = pd.date_range(start_date, periods=len(closes), freq="D")
    idx = pd.DatetimeIndex(dates)
    df = pd.DataFrame({
        "Open": opens if opens else closes,
        "Close": closes,
    }, index=idx)
    return df


def test_entry_next_open_and_raw_returns():
    """entry = 다음 시가 · return_* 은 다음 시가 기준 raw."""
    signal_date = datetime(2026, 1, 1)
    # 40일치 history · 앞 5일만 실 값 · 나머지는 130 유지 (delisting=False 보장)
    closes = [100.0, 121.0, 130.0, 132.0, 140.0] + [140.0] * 35
    opens = [95.0, 110.0, 121.0, 130.0, 135.0] + [140.0] * 35
    hist = _make_hist_from_prices(signal_date, closes, opens)
    client = lambda sym: _FakeTicker(hist)

    result = bt_mod.backtest_signal(
        {"id": "sig-1", "ticker": "TEST", "extracted_at": signal_date},
        ticker_client=client,
    )
    assert result is not None
    assert result["price_at_signal"] == 100.0
    assert result["entry_next_open_price"] == 110.0
    assert result["entry_with_slippage_price"] == pytest.approx(110.0 * 1.01, rel=1e-4)
    # gap = (110-100)/100 * 100 = 10.0
    assert result["gap_next_open_pct"] == pytest.approx(10.0)
    # return_1d: index 1 (next open 110) → index 2 (close 130) → (130-110)/110*100 = 18.18
    assert result["return_1d"] == pytest.approx(18.18, abs=0.01)
    # return_3d: index 1 (110) → index 4 (140) → (140-110)/110*100 = 27.27
    assert result["return_3d"] == pytest.approx(27.27, abs=0.01)
    assert result["delisting_flag"] is False


def test_detect_delisting_when_hist_ends_within_30d():
    """signal_date+30d 이전에 history 끝나면 delisting_flag=True."""
    signal_date = datetime(2026, 1, 1)
    # 15일치만 · 30일 이내에 끝남
    closes = [100.0] * 15
    hist = _make_hist_from_prices(signal_date, closes)
    client = lambda sym: _FakeTicker(hist)

    result = bt_mod.backtest_signal(
        {"id": "sig-del", "ticker": "DEAD", "extracted_at": signal_date},
        ticker_client=client,
    )
    assert result is not None
    assert result["delisting_flag"] is True


def test_returns_none_when_empty_history():
    signal_date = datetime(2026, 1, 1)
    hist = pd.DataFrame()
    client = lambda sym: _FakeTicker(hist)

    result = bt_mod.backtest_signal(
        {"id": "sig-empty", "ticker": "GONE", "extracted_at": signal_date},
        ticker_client=client,
    )
    assert result is None
