"""1025-05 · 판정·후보 결과 자동 계산 (docs/plans/judgment-outcomes/README.md).

- 가격은 토스 일봉 하나 · 토스에 없으면 계산 불가 (다른 소스로 채우지 않음).
- 기준 시각 = 만들어진 시각 (UTC) → 현지 · 현지 장 마감 (KR 15:30 · US 16:00) 뒤면 그날 봉.
- T+N = 기준 봉 날짜 + N 달력일과 같거나 뒤인 첫 봉 · Moonshot 은 기준 봉 뒤 N번째 봉.
- 저널: 기준가 = 적은 진입가 → 없으면 기준 봉 종가 · 대체된 판정 · 청산 행 제외.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from backend.services import outcomes as oc
from backend.services.models import CrazyPick, MoonshotPick, UserJudgment


def test_base_date_respects_market_close():
    # 2026-10-23 (금) 06:30 KST = 10/22 21:30 UTC → 미국 10/22 17:30 EDT → 마감 뒤 = 10/22
    assert oc.base_date(datetime(2026, 10, 22, 21, 30), "US") == date(2026, 10, 22)
    # 미국 장중 (10/22 14:00 EDT = 18:00 UTC) → 전날
    assert oc.base_date(datetime(2026, 10, 22, 18, 0), "US") == date(2026, 10, 21)
    # 국내 10:00 KST = 01:00 UTC → 전날 · 16:50 KST = 07:50 UTC → 그날
    assert oc.base_date(datetime(2026, 10, 23, 1, 0), "KR") == date(2026, 10, 22)
    assert oc.base_date(datetime(2026, 10, 23, 7, 50), "KR") == date(2026, 10, 23)


def _bars(start: date, closes, lows=None, highs=None):
    out, d = [], start
    for i, c in enumerate(closes):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append(oc.Bar(d, close=c, low=(lows[i] if lows else c), high=(highs[i] if highs else c)))
        d += timedelta(days=1)
    return out


def test_parse_bars_ascending_with_high_low():
    resp = {"candles": [
        {"timestamp": "2026-10-23T00:00:00-04:00", "closePrice": "11", "highPrice": "12", "lowPrice": "10"},
        {"timestamp": "2026-10-22T00:00:00-04:00", "closePrice": "10", "highPrice": "10.5", "lowPrice": "9"},
        {"timestamp": "bad", "closePrice": "1"},
    ]}
    bars = oc.parse_bars(resp)
    assert [(b.d, b.close, b.high, b.low) for b in bars] == [
        (date(2026, 10, 22), 10.0, 10.5, 9.0), (date(2026, 10, 23), 11.0, 12.0, 10.0)]


def test_calendar_return_first_bar_on_or_after():
    bars = _bars(date(2026, 10, 1), [10, 11, 12, 13, 14, 15, 16, 17, 18])  # 10/1 목 … 주말 건너뜀
    base = oc.bar_on_or_before(bars, date(2026, 10, 1))
    r = oc.calendar_return(bars, base, 7, base.close)  # 10/8 (목) 이 첫 봉
    assert r == pytest.approx(15 / 10 - 1)  # 10/8 (목) 종가
    assert oc.calendar_return(bars, base, 30, base.close) is None  # 아직 만기 아님


def test_trading_day_returns_and_max_high():
    bars = _bars(date(2026, 10, 1), [10, 11, 9, 12, 13, 14], highs=[10, 11.5, 9.5, 12.5, 15, 14])
    base = bars[0]
    assert oc.nth_bar_return(bars, base, 1) == pytest.approx(0.1)
    assert oc.nth_bar_return(bars, base, 3) == pytest.approx(0.2)
    assert oc.nth_bar_return(bars, base, 5) == pytest.approx(0.4)
    assert oc.max_high_after(bars, base, 5) == 15
    assert oc.max_high_after(bars[:3], bars[0], 5) is None  # 5봉이 다 차야 채움


def test_invalidation_long_and_short():
    bars = _bars(date(2026, 10, 1), [10, 10, 9, 10], lows=[10, 9.5, 7.9, 9])
    hit = oc.invalidation_hit(bars, bars[0], bars[-1].d, base_price=10, invalidation=8, target=13)
    assert hit == (bars[2].d, 7.9)
    assert oc.invalidation_hit(bars, bars[0], bars[-1].d, base_price=10, invalidation=7, target=13) is None
    sbars = _bars(date(2026, 10, 1), [10, 11, 12], highs=[10, 11, 12.5])
    assert oc.invalidation_hit(sbars, sbars[0], sbars[-1].d, base_price=10, invalidation=12, target=8) == (sbars[2].d, 12.5)


# ─── DB 실행 ───
class _FakeToss:
    def __init__(self, by_symbol: dict, missing=()):
        self.by = by_symbol
        self.missing = set(missing)
        self.calls: list[str] = []

    def candles(self, symbol, count=200):
        self.calls.append(symbol)
        if symbol in self.missing:
            from backend.execution.exceptions import OrderRejected

            raise OrderRejected("stock-not-found", "없음")
        return {"candles": [{"timestamp": f"{b.d}T00:00:00-04:00", "closePrice": str(b.close),
                             "highPrice": str(b.high), "lowPrice": str(b.low)} for b in reversed(self.by.get(symbol, []))]}


@pytest.fixture
async def clean():
    from backend.services.db import get_session, init_db

    await init_db()
    async with get_session() as s:
        for m in (UserJudgment, CrazyPick, MoonshotPick):
            await s.execute(delete(m))
    yield


async def _add(*objs):
    from backend.services.db import get_session

    async with get_session() as s:
        for o in objs:
            s.add(o)


async def _all(model):
    from backend.services.db import get_session

    async with get_session() as s:
        return (await s.execute(select(model).order_by(model.id))).scalars().all()


def _j(**kw):
    base = dict(ts=datetime(2026, 10, 1, 21, 0), ticker="WEN", page_source="journal", hypothesis_id="h",
                thesis_md="t", horizon_days=7)
    base.update(kw)
    return UserJudgment(**base)


NOW = datetime(2026, 10, 26, 23, 10)  # 10/27 08:10 KST


@pytest.mark.asyncio
async def test_run_judgments(clean):
    bars = _bars(date(2026, 9, 30), [10, 10, 11, 11, 12, 12, 13, 13, 14, 14, 15, 15, 16, 16, 17, 17, 18, 18, 19],
                 lows=[10, 10, 11, 7, 12, 12, 13, 13, 14, 14, 15, 15, 16, 16, 17, 17, 18, 18, 19])
    await _add(
        _j(),                                                   # 기준 = 10/1 종가 (마감 뒤 작성)
        _j(entry_price=9.0, invalidation_price=8.0),            # 적은 진입가 · 손절 도달
        _j(horizon_days=60),                                    # 만기 아님 → 기준가만
        _j(superseded_by_id=99),                                # 대체됨 → 제외
        _j(page_source="close", horizon_days=1),                # 청산 행 → 제외
        _j(ticker="NOPE"),                                      # 토스에 없음
    )
    out = await oc.run_outcomes(client=_FakeToss({"WEN": bars}, missing={"NOPE"}), now=NOW)
    rows = await _all(UserJudgment)
    a, b, c, d, e, f = rows
    assert a.result_base_price == 10 and a.result_base_source == "t0_close"
    assert a.result_at_horizon == pytest.approx(13 / 10 - 1) and a.result_computed_at is not None  # 10/8 종가 13
    assert b.result_base_price == 9.0 and b.result_base_source == "entry"
    assert b.result_at_horizon == pytest.approx(13 / 9 - 1)
    assert b.invalidation_hit_low == 7 and b.invalidation_hit_ts is not None
    assert c.result_base_price == 10 and c.result_at_horizon is None
    assert d.result_base_price is None and e.result_base_price is None
    assert f.result_base_price is None and f.result_at_horizon is None
    assert out["judgments"] == {"computed": 2, "pending": 1, "unavailable": 1}


@pytest.mark.asyncio
async def test_run_picks_and_no_overwrite(clean):
    bars = _bars(date(2026, 9, 30), list(range(10, 50)), highs=[x + 0.5 for x in range(10, 50)])
    created = datetime(2026, 9, 30, 21, 30)  # 미국 9/30 마감 뒤
    await _add(
        CrazyPick(pick_date="2026-10-01", rank=1, ticker="WEN", created_at=created),
        CrazyPick(pick_date="2026-10-01", rank=2, ticker="TTD", created_at=created, perf_1w=0.5),  # 이미 값 → 그대로
        MoonshotPick(pick_date="2026-10-01", rank=1, ticker="WEN", created_at=created),
    )
    fake = _FakeToss({"WEN": bars, "TTD": bars})
    out = await oc.run_outcomes(client=fake, now=NOW)
    c1, c2 = await _all(CrazyPick)
    (m,) = await _all(MoonshotPick)
    assert c1.perf_1w == pytest.approx(15 / 10 - 1)  # 9/30 → 10/7 (5번째 봉)
    assert c1.perf_1m == pytest.approx(32 / 10 - 1)  # 10/30 (금) = 기준 뒤 22번째 봉
    assert c2.perf_1w == 0.5
    assert m.perf_1d == pytest.approx(0.1) and m.perf_3d == pytest.approx(0.3) and m.perf_5d == pytest.approx(0.5)
    assert m.max_price_after == 15.5
    assert sorted(set(fake.calls)) == ["TTD", "WEN"] and fake.calls.count("WEN") == 1  # 종목당 1회
    assert out["crazy"]["computed"] >= 1 and out["moonshot"]["computed"] == 1


@pytest.mark.asyncio
async def test_horizon_patch_clears_result(clean, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    token = "outcome_patch_test_token_32chars_0"
    monkeypatch.setenv("SNIPER_API_TOKEN", token)
    await _add(_j(result_at_horizon=0.1, result_computed_at=datetime(2026, 10, 9), result_base_price=10.0,
                  result_base_source="t0_close", invalidation_hit_ts=datetime(2026, 10, 5), invalidation_hit_low=7.0))
    (row,) = await _all(UserJudgment)
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.patch(f"/api/v1/judgments/{row.id}", json={"horizon_days": 30, "change_note": "기간 변경"},
                           headers={"X-API-Token": token})
    assert r.status_code == 200, r.text
    (row,) = await _all(UserJudgment)
    assert row.horizon_days == 30 and row.result_at_horizon is None and row.result_computed_at is None
    assert row.invalidation_hit_ts is None and row.result_base_price == 10.0  # 기준가는 그대로


@pytest.mark.asyncio
async def test_ensure_columns_is_idempotent(clean):
    from backend.services.db import ensure_columns

    await ensure_columns()
    await ensure_columns()


def test_outcomes_job_registered_0810():
    from backend.scheduler import cron

    jobs = {j.id: j for j in cron.build_scheduler().get_jobs()}
    t = str(jobs["outcomes_daily"].trigger)
    assert "hour='8'" in t and "minute='10'" in t


@pytest.mark.asyncio
async def test_outcomes_job_alerts_on_failure(monkeypatch):
    from backend.scheduler import cron

    alerts = []

    async def boom(client=None, now=None):
        raise RuntimeError("x")

    async def fake_alert(name, exc, hour=None, minute=None):
        alerts.append((name, hour, minute))

    monkeypatch.setattr(oc, "run_outcomes", boom)
    monkeypatch.setattr(cron, "_alert_job_failure", fake_alert)
    await cron.job_outcomes()
    assert alerts == [("판정·후보 결과 계산", 8, 10)]
