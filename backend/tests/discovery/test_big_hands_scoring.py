"""1119-03 ① · 채점 엔진 · 장부 단위 시험 (지어낸 자료만 · 바깥 호출 없음)."""
from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.discovery.big_hands import ledger, scoring
from backend.discovery.big_hands.models import SignalOutcome
from backend.services.db import get_session, init_db


# ─── 조건 가: t 기준값은 달 수에서 구한다 ──────────────────────
@pytest.mark.parametrize("months,expected", [(12, 2.59), (24, 2.40), (30, 2.36), (47, 2.32)])
def test_t_critical_from_month_count(months, expected):
    assert scoring.t_critical_pure(months) == pytest.approx(expected, abs=0.006)
    assert scoring.t_critical(months) == pytest.approx(expected, abs=0.006)     # scipy 없으면 같은 직접 구현


def test_t_critical_needs_two_months():
    assert scoring.t_critical(1) is None


def test_t_cdf_symmetry():
    assert scoring._t_cdf(0.0, 10) == pytest.approx(0.5)
    assert scoring._t_cdf(2.0, 10) + scoring._t_cdf(-2.0, 10) == pytest.approx(1.0)


# ─── 통계 ──────────────────────────────────────────────────────
def test_basic_stats():
    xs = [1.0, 2.0, 3.0, 4.0, 100.0]
    assert scoring._median(xs) == 3.0
    big = list(range(1, 201))
    assert scoring.trimmed_mean([float(x) for x in big]) == pytest.approx(100.5)     # 위아래 2개씩 잘라도 대칭
    assert scoring.trimmed_mean([1.0, 2.0, 1000.0]) == pytest.approx(334.3333, abs=1e-3)   # 3건은 자르지 않음


def test_clustered_and_calendar_t():
    by_month = {f"2023-{m:02d}": [1.0 + 0.1 * m, 2.0] for m in range(1, 13)}
    tc = scoring.clustered_t(by_month)
    tk = scoring.calendar_time_t(by_month)
    assert tc is not None and tk is not None and tc > 0 and tk > 0
    assert scoring.clustered_t({"2023-01": [1.0, 2.0]}) is None
    assert scoring.calendar_time_t({"2023-01": [1.0]}) is None


# ─── 성적 한 줄 ─────────────────────────────────────────────────
def _bars(start: date, n: int, open_: float, close_fn):
    out = {}
    d, i = start, 0
    while len(out) < n:
        if d.weekday() < 5:
            out[d] = {"open": open_, "close": close_fn(i)}
            i += 1
        d += timedelta(days=1)
    return out


def test_compute_outcome_example_like_plan():
    # 기획서 예시 1 모양 (지어낸 값): 진입 12,800 → 14,080 = +10% · 지수 +2% · 비용 0.3%
    o = scoring.compute_outcome(12800, 14080, 1000, 1020, 0.3)
    assert o["return_pct"] == pytest.approx(10.0)
    assert o["index_return_pct"] == pytest.approx(2.0)
    assert o["excess_pct"] == pytest.approx(7.7)


def test_compute_outcome_no_price():
    assert scoring.compute_outcome(None, 10, 1, 1, 0.3)["status"] == "no_price"


def test_build_outcome_enters_next_day_open_and_exits_nth_day_close():
    idx = _bars(date(2026, 3, 2), 40, 1000.0, lambda i: 1000.0 + i)
    stock = _bars(date(2026, 3, 2), 40, 50.0, lambda i: 50.0 + i)
    days = sorted(idx)
    est = days[2]
    out = scoring.build_outcome(est, 20, stock, idx, 0.3)
    assert out["entry_date"] == days[3]                # 성립 다음 거래일
    assert out["exit_date"] == days[3 + 20]            # 진입일에서 20번째 거래일
    assert out["entry_price"] == 50.0
    assert out["exit_price"] == stock[days[23]]["close"]
    assert out["status"] == "ok"


def test_build_outcome_delisted_uses_last_close_not_dropped():
    idx = _bars(date(2026, 3, 2), 40, 1000.0, lambda i: 1000.0)
    stock = _bars(date(2026, 3, 2), 10, 50.0, lambda i: 40.0)     # 10일 뒤 일봉이 끊김
    out = scoring.build_outcome(sorted(idx)[0], 20, stock, idx, 0.3)
    assert out["status"] == "delisted"
    assert out["exit_price"] == 40.0
    assert out["return_pct"] == pytest.approx(-20.0)


def test_build_outcome_no_stock_bars_is_no_price():
    idx = _bars(date(2026, 3, 2), 40, 1000.0, lambda i: 1000.0)
    assert scoring.build_outcome(sorted(idx)[0], 20, {}, idx, 0.3)["status"] == "no_price"


# ─── 「검증됨」 판정 (지어낸 자료) ──────────────────────────────
def _rows(months: int, per_month: int, excess: float, no_price: int = 0, spread: float = 3.0):
    rows = []
    for m in range(months):
        y, mo = 2023 + m // 12, m % 12 + 1
        wobble = 1.5 * ((m * 7) % 5 - 2)           # 달마다 평균이 조금씩 다르게 (표준편차 0 방지)
        for k in range(per_month):
            sign = 1 if k % 2 == 0 else -1
            rows.append({"entry_date": date(y, mo, 10 + k), "excess_pct": excess + wobble + sign * spread, "status": "ok"})
    for i in range(no_price):
        rows.append({"entry_date": date(2023, 1, 20 + i % 5), "excess_pct": None, "status": "no_price"})
    return rows


def test_verified_when_all_criteria_pass():
    s = scoring.summarize_type(_rows(24, 4, 2.0), total_events=150)
    assert s["verified"], s["fail_reasons"]
    assert s["months"] == 24 and s["t_critical"] == pytest.approx(2.40, abs=0.006)


def test_not_verified_if_t_between_old_and_new_threshold():
    # 예전 큰 표본 기준(2.24)은 넘지만 24개월 기준(2.40) 미만인 값이 보관함으로 가야 한다
    rows = _rows(24, 4, 0.0)
    lo, hi = 0.0, 3.0
    for _ in range(60):          # 달력 시간 t 가 약 2.3 이 되도록 평균을 이분법으로 맞춘다
        mid = (lo + hi) / 2
        s = scoring.summarize_type(_rows(24, 4, mid), 150)
        if s["t_used"] < 2.3:
            lo = mid
        else:
            hi = mid
    s = scoring.summarize_type(_rows(24, 4, hi), 150)
    assert 2.24 <= s["t_used"] < s["t_critical"]
    assert not s["verified"] and "t 값이 기준값 미만" in s["fail_reasons"]


def test_not_verified_if_fewer_than_12_months_or_few_events_or_no_price():
    assert "사건이 있는 달 부족" in scoring.summarize_type(_rows(11, 6, 2.0), 150)["fail_reasons"]
    assert "판정 기간 사건 부족" in scoring.summarize_type(_rows(12, 3, 2.0), 150)["fail_reasons"]
    assert "전체 사건 부족" in scoring.summarize_type(_rows(24, 4, 2.0), 99)["fail_reasons"]
    s = scoring.summarize_type(_rows(24, 4, 2.0, no_price=8), 150)       # 8/104 = 7.7% > 5%
    assert "가격 없음 비율 초과" in s["fail_reasons"] and not s["verified"]


def test_conservative_line_counts_missing_as_minus_100():
    s = scoring.summarize_type(_rows(24, 4, 0.5, no_price=4), 150)       # 4/100 = 4% 이하지만 보수 줄이 깨짐
    assert s["no_price_ratio"] <= 0.05
    assert s["conservative_mean_pct"] < 0
    assert "보수 줄 평균 0 이하" in s["fail_reasons"]


def test_rule_period_rows_are_not_used_for_judgement():
    rows = _rows(24, 4, 2.0) + [{"entry_date": date(2020, 5, 1), "excess_pct": -50.0, "status": "ok"}] * 30
    assert scoring.summarize_type(rows, 180)["n_judge"] == 96


# ─── 사건 묶음 · 성립 날짜 ──────────────────────────────────────
def _tdays():
    d, out = date(2026, 3, 2), []
    while len(out) < 80:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_event_window_fixed_on_first_signal_date():
    td = _tdays()
    # 0일차 첫 신호 · 4일차 · 6일차(창 밖) → 6일차는 새 사건 (창은 4일차 신호로 늘어나지 않는다)
    evs = scoring.__dict__  # noqa: F841 (모듈 상수 확인용)
    out = ledger.group_events([("AAA111", td[0]), ("AAA111", td[4]), ("AAA111", td[6]), ("BBB222", td[1])], td)
    by = {(e["code"], e["first_signal_date"]): e for e in out}
    assert len(out) == 3
    assert by[("AAA111", td[0])]["signals"] == [td[0], td[4]]
    assert ("AAA111", td[6]) in by and ("BBB222", td[1]) in by


def test_kr_i2_establish_is_second_person_receipt_date():
    d0 = date(2026, 3, 10)
    assert ledger.kr_i2_establish_date([("p1", d0), ("p2", d0 + timedelta(days=12))]) == d0 + timedelta(days=12)
    assert ledger.kr_i2_establish_date([("p1", d0), ("p1", d0 + timedelta(days=5))]) is None      # 같은 사람
    assert ledger.kr_i2_establish_date([("p1", d0), ("p2", d0 + timedelta(days=31))]) is None     # 30일 밖


def test_kr_i2_third_buy_does_not_create_new_establishment():
    d0 = date(2026, 3, 10)
    buys = [("p1", d0), ("p2", d0 + timedelta(days=3)), ("p3", d0 + timedelta(days=9))]
    assert ledger.kr_i2_establish_date(buys) == d0 + timedelta(days=3)     # 셋째는 같은 성립 (rules-v1)


# ─── 조건 마: 성립 하나는 성적 한 줄 ────────────────────────────
@pytest_asyncio.fixture
async def _db():
    await init_db()
    async with get_session() as session:
        from sqlalchemy import delete
        await session.execute(delete(SignalOutcome))
    yield


@pytest.mark.asyncio
async def test_outcome_unique_key_counts_once(_db):
    kw = dict(market="KR", code="AAA111", signal_type="KR-I2", horizon_days=20, entry_date=date(2026, 3, 11))
    assert await ledger.upsert_outcome(**kw, event_id=1, excess_pct=1.0) is True
    assert await ledger.upsert_outcome(**kw, event_id=2, excess_pct=1.0) is False     # 다른 사건이 같은 성립을 또 세지 못함
    assert await ledger.upsert_outcome(**{**kw, "signal_type": "KR-I1"}) is True       # 유형이 다르면 별도
    assert await ledger.upsert_outcome(**{**kw, "horizon_days": 5}) is True
    async with get_session() as session:
        n = len((await session.execute(select(SignalOutcome))).scalars().all())
    assert n == 3
