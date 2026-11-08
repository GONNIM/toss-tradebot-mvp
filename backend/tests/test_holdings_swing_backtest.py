"""보유 종목 스윙 백테스트 규칙 판정 시험 (작은 가짜 가격열 · 날짜·시각·네트워크 의존 없음)."""
import numpy as np
import pytest

from backend.scripts import holdings_swing_backtest as m

T0 = 59  # 60일 평균이 처음 계산되는 날
KR_BUY, KR_SELL = m.COSTS["KR"]["buy"], m.COSTS["KR"]["sell"]


def hist(n=60):
    """흔들림이 있는 평평한 과거: 101, 100, 101, ... 마지막(59번)은 100."""
    return [101.0 if (i % 2 == 0) else 100.0 for i in range(n)]


def series(tail):
    return hist() + list(tail)


def high(n):
    """108 근처에서 흔들리는 구간 (108.0, 108.5 번갈아) · 추가 매수 뒤에도 평단 대비 +5% 를 넘도록 높게 잡음."""
    return [108.0 if i % 2 == 0 else 108.5 for i in range(n)]


def sim(prices, rules, market="KR", hold_days=m.HOLD_DAYS):
    return m.simulate(m.indicators(prices), T0, market, set(rules), hold_days=hold_days)


def first_a_signal(prices):
    """A 조건을 시험 안에서 따로 풀어 첫 신호일을 찾는다 (평단 = 100 × (1+매수수수료) 고정)."""
    ind = m.indicators(prices)
    avg = 100 * (1 + KR_BUY)
    for i in range(T0, len(prices)):
        if prices[i] / avg - 1 >= 0.05 and prices[i] > ind.ma20[i] > ind.ma60[i] and prices[i] / ind.ma20[i] - 1 <= ind.sig20[i]:
            return i
    return None


# ── 비용 · 그대로 들고 있기 ──
def test_hold_flat_kr_cost():
    r = sim(series([100.0] * 61), set())
    assert r.ret == pytest.approx((1 - KR_SELL) / (1 + KR_BUY) - 1)
    assert r.total_in == 1.0


def test_hold_flat_us_cost_includes_fx_both_ways():
    c = m.COSTS["US"]
    r = sim(series([100.0] * 61), set(), "US")
    expected = (1 - c["fx"]) / (1 + c["buy"]) * (1 - c["sell"]) * (1 - c["fx"]) - 1
    assert r.ret == pytest.approx(expected)


def test_hold_with_reserve_uses_total_in_166():
    r = m.simulate(m.indicators(series([100.0] * 61)), T0, "KR", set(), reserve=True)
    qty = 1 / (100 * (1 + KR_BUY))
    assert r.total_in == pytest.approx(1.66)
    assert r.ret == pytest.approx((qty * 100 * (1 - KR_SELL) + 0.66) / 1.66 - 1)


# ── A 흑자 추가 ──
def test_a_executes_next_day_close_with_third_of_initial_qty():
    p = series(high(61))
    sig = first_a_signal(p)
    assert sig is not None
    r = sim(p, {"A_L"})
    a_events = [e for e in r.events if e[1] == "A"]
    assert a_events[0][0] == sig + 1  # 신호 다음 거래일 종가에 체결


def test_a_max_two_adds_per_uptrend_and_gap():
    r = sim(series(high(61)), {"A_L"})
    idx = [i for i, k in r.events if k == "A"]
    assert len(idx) == 2
    assert idx[1] - idx[0] >= m.ADD_GAP_DAYS


def test_a_cap_is_66_percent_of_initial_amount():
    r = sim(series(high(61)), {"A_L"})
    # 처음 투입금 1.0 · 상한 0.66 (두 번째 추가는 상한에 맞춰 줄어든다)
    assert r.add_spent == pytest.approx(0.66, abs=1e-9)
    assert r.total_in == pytest.approx(1.66)


def test_a_requires_profit_of_5_percent():
    r = sim(series([103.0] * 61), {"A_L"})  # +3%
    assert r.fired == set()


def test_a_long_has_no_stop_up_but_short_does():
    # 106 에서 두 번 추가한 뒤 100 으로 떨어짐 (합산 평단 아래)
    p = series(high(31) + [100.0] * 30)
    short = sim(p, {"A_S"})
    long_ = sim(p, {"A_L"})
    stops = [e for e in short.events if e[1] == "STOP"]
    assert len(stops) == 1 and short.qty_end == 0
    assert not [e for e in long_.events if e[1] == "STOP"] and long_.qty_end > 0
    # 손절 체결은 신호 다음 날
    first_below = next(i for i in range(60, len(p)) if p[i] == 100.0)
    assert stops[0][0] == first_below + 1


# ── B 적자 일부 매도 · B1 · B2 ──
def b_series(after):
    # 100 근처에서 90 으로 내려 20일 머문 뒤 91 로 살짝 반등 (손실 · 60일 평균 아래 · 20일 평균 이상) 그다음 after
    return series([90.0] * 20 + [91.0] + list(after))


def test_b_sells_one_third_next_day():
    p = b_series([91.0] * 40)
    r = sim(p, {"B1"}, hold_days=25)
    b = [e for e in r.events if e[1] == "B"]
    assert len(b) == 1
    # 20일 평균 이상으로 처음 닿는 날(79번: 90 이 20번째) 종가 판정 → 다음 날 종가 체결
    assert b[0][0] == 80
    assert r.qty_end == pytest.approx(r.qty0 * 2 / 3)


def test_b1_rebuys_after_5_percent_drop_within_20_days():
    p = b_series([91.0] * 3 + [85.0] * 37)  # 팔린 값 91 → 5% 아래 86.45 이하로 내려감
    r = sim(p, {"B1"}, hold_days=30)
    kinds = [k for _, k in r.events]
    assert kinds[:2] == ["B", "REBUY"]
    assert r.qty_end == pytest.approx(r.qty0)  # 판 수량만큼 다시 삼


def test_b1_does_not_rebuy_on_4_percent_drop():
    p = b_series([91.0] * 3 + [87.5] * 37)  # 91 → 87.5 는 -3.8% (5% 미만)
    r = sim(p, {"B1"}, hold_days=43)
    assert "REBUY" not in [k for _, k in r.events]


def test_b1_gives_up_after_20_days():
    p = b_series([91.0] * 40)  # 안 내려감
    r = sim(p, {"B1"}, hold_days=43)  # 판 날(80)+21 = 101 에 기한 끝 · 창은 102 에서 끝남
    assert [k for _, k in r.events] == ["B"]
    assert r.qty_end == pytest.approx(r.qty0 * 2 / 3)


def test_b2_rebuys_on_two_closes_above_ma60():
    p = b_series([91.0] * 3 + [101.0] * 3 + [101.0] * 34)  # 60일 평균 위 연속
    r = sim(p, {"B2"})
    assert [k for _, k in r.events][:2] == ["B", "REBUY"]


def test_b2_has_no_deadline_but_waits_without_signal():
    p = b_series([91.0] * 40)
    r = sim(p, {"B2"}, hold_days=25)
    assert [k for _, k in r.events] == ["B"]  # 신호 없으면 재매수 없음 (현금 보유)


# ── D 이익 보호 ──
def test_d_sells_all_at_next_close_after_drawdown_below_ma20():
    up = list(np.linspace(100, 120, 20))
    p = series(up + [120.0] * 5 + [108.0] + [95.0] * 35)  # 고점 120 → 108 (-10%) 이고 20일 평균 아래
    r = sim(p, {"D"})
    d = [e for e in r.events if e[1] == "D"]
    assert len(d) == 1 and r.qty_end == 0
    sig = 60 + 20 + 5  # 108 이 처음 나온 날
    assert d[0][0] == sig + 1


def test_d_requires_profit():
    p = series([100.0] * 10 + [85.0] * 51)  # 손실 구간에서는 D 없음
    r = sim(p, {"D"})
    assert "D" not in r.fired


# ── 체결 시점 ──
def test_no_trade_scheduled_on_last_day():
    p = series([106.0] * 61)
    r = sim(p, {"A_L", "B1", "D"})
    assert all(i <= T0 + m.HOLD_DAYS for i, _ in r.events)


# ── 통계 · 판정 ──
def test_bootstrap_constant_diffs_collapse_to_value():
    lo, hi = m.bootstrap_mean_ci({"a": [0.02, 0.02], "b": [0.02]}, n_boot=200)
    assert lo == pytest.approx(0.02) and hi == pytest.approx(0.02)


def test_verdict_requires_all_conditions_and_sample_200():
    ins = {"n": 150, "mean_diff": 0.01, "ci_lo": -0.005, "p5_diff": -0.01}
    out = {"n": 50, "mean_diff": 0.002}
    assert m.verdict(ins, out, 200)["pass"] is True
    assert m.verdict(ins, out, 199)["pass"] is False  # 표본 부족
    assert m.verdict({**ins, "ci_lo": -0.012}, out, 300)["pass"] is False  # (나)
    assert m.verdict({**ins, "p5_diff": -0.021}, out, 300)["pass"] is False  # (다)
    assert m.verdict(ins, {"n": 50, "mean_diff": -0.001}, 300)["pass"] is False  # (라)
    assert m.verdict({**ins, "mean_diff": -0.001}, out, 300)["pass"] is False  # (가)


def test_final_label_marks_sample_shortage():
    vd = {"ga": True, "na": True, "da": True, "ra": True, "n_ok": False, "pass": False}
    assert m.final_label("A_L", vd) == "미통과 (표본 부족)"


def test_compare_b1_b2_picks_in_sample_winner():
    def row(r1, r2, h):
        return {
            "B1": m.SimResult(ret=r1, mdd=0, fired={"B"}),
            "B2": m.SimResult(ret=r2, mdd=0, fired={"B"}),
            "hold_plain": m.SimResult(ret=h, mdd=0),
        }

    ins = [row(0.02, 0.0, 0.0)] * 3
    out = [row(0.01, 0.03, 0.0)] * 2
    res = m.compare_b1_b2(ins, out)
    assert res["pick"] == "B1"
    assert res["out_pick_vs_hold"] == pytest.approx(0.01)
    assert res["out_pick_vs_other"] == pytest.approx(-0.02)
    assert res["keep"] is False  # 표본 밖에서는 다른 쪽(B2)이 더 나아 선택이 뒤집힘


def test_breakeven_vs_d_sells_next_close_vs_keeps_holding():
    # 100 에 매수 → 94 까지 내림 → 평단 회복(103) → 이후 상승 지속
    p = series([94.0] * 5 + [103.0] + [110.0] * 55)
    r = m.breakeven_vs_d(m.indicators(p), T0, "KR")
    assert r is not None
    x, y = r
    qty = 1 / (100 * (1 + KR_BUY))
    assert x == pytest.approx(qty * 110 * (1 - KR_SELL) - 1)  # 회복 신호 다음 날 110 에 매도
    assert y == pytest.approx(x)  # 이후 낙폭이 없어 D 도 끝까지 보유 후 같은 값 (110 청산)


def test_breakeven_requires_5_percent_dip():
    p = series([97.0] * 5 + [103.0] + [110.0] * 55)  # -3% 만 내려감
    assert m.breakeven_vs_d(m.indicators(p), T0, "KR") is None


def test_drawdown_frequency_counts_8_percent_in_calendar_year():
    dates = [f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(60)]
    drop = ([100.0] * 30) + ([90.0] * 30)
    flat = [100.0] * 60
    res = m.drawdown_frequency({"a": (dates, np.array(drop)), "b": (dates, np.array(flat))})
    assert res[2025] == {"n": 2, "share": 0.5}


def test_window_starts_nonoverlap_and_fit():
    s = list(m.window_starts(300, 60))
    assert s[0] == 59 and all(b - a == 60 for a, b in zip(s, s[1:])) and s[-1] + 60 <= 299
