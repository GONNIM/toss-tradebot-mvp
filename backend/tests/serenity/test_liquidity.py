"""liquidity.py · compute_avg_dollar_volume 유닛 테스트."""
from __future__ import annotations

import pandas as pd
import pytest

from backend.discovery.serenity.liquidity import compute_avg_dollar_volume


def _make_hist(closes: list[float], volumes: list[int]) -> pd.DataFrame:
    return pd.DataFrame({"Close": closes, "Volume": volumes})


def test_returns_none_when_empty():
    assert compute_avg_dollar_volume(pd.DataFrame()) is None
    assert compute_avg_dollar_volume(None) is None


def test_returns_none_when_less_than_window():
    hist = _make_hist([100.0] * 10, [1_000_000] * 10)
    assert compute_avg_dollar_volume(hist, window=20) is None


def test_computes_average_over_last_window():
    # 25 개 · 마지막 20 개 만 사용
    closes = [100.0] * 25
    volumes = [1_000_000] * 25
    result = compute_avg_dollar_volume(_make_hist(closes, volumes), window=20)
    assert result == pytest.approx(100.0 * 1_000_000)


def test_uses_only_last_window_rows():
    closes = [999.0] * 5 + [50.0] * 20
    volumes = [999_999] * 5 + [10_000] * 20
    result = compute_avg_dollar_volume(_make_hist(closes, volumes), window=20)
    assert result == pytest.approx(50.0 * 10_000)


def test_handles_variable_values():
    closes = list(range(1, 21))          # 1..20
    volumes = [100_000] * 20
    result = compute_avg_dollar_volume(_make_hist(closes, volumes), window=20)
    # mean(1..20) = 10.5 · × 100_000
    assert result == pytest.approx(10.5 * 100_000)
