"""WP17-4 · H5 백테스트 엔진 fixture 3건."""
from __future__ import annotations

from backend.scripts import biotech_h5_backtest as mod


def test_pit_eligible_before_and_after():
    assert mod.pit_eligible("2024Q3", "2021Q1") is True
    assert mod.pit_eligible("2020Q4", "2021Q1") is False
    assert mod.pit_eligible("2021Q1", "2021Q1") is True
    assert mod.pit_eligible("", "2021Q1") is False


def test_quarter_of_boundaries():
    assert mod.quarter_of("2024-01-01") == "2024Q1"
    assert mod.quarter_of("2024-03-31") == "2024Q1"
    assert mod.quarter_of("2024-04-01") == "2024Q2"
    assert mod.quarter_of("2024-12-31") == "2024Q4"


def test_window_return_costs_bench():
    # D-day = 2024-06-30 · offset -5 → 2024-06-25 (start) · offset -1 → 2024-06-29 (부재 → -2 06-28)
    prices = {
        "2024-06-25": 100.0,  # D-5 (start)
        "2024-06-26": 102.0,
        "2024-06-27": 103.0,
        "2024-06-28": 105.0,  # D-2 (end · D-1 부재)
        "2024-06-30": 108.0,  # D-day (거래 없음 이해)
        "2024-07-01": 110.0,  # D+1 (start)
        "2024-07-05": 115.0,  # D+5 (end)
    }
    r_pre, note_pre = mod.window_return(prices, "2024-06-30", -5, -1)
    assert note_pre == "ok"
    assert round(r_pre, 4) == round(105.0 / 100.0 - 1, 4)
    r_imm, note_imm = mod.window_return(prices, "2024-06-30", 1, 5)
    assert note_imm == "ok"
    assert round(r_imm, 4) == round(115.0 / 110.0 - 1, 4)
