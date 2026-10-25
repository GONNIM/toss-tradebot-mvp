"""1025-08 · 토스 실계좌 보유 기록과 매도 판단 재료 (보유 일수 · 최고가 대비).

규칙 (Fable 1025-08 막음 2·3):
- 기록 키 = (종목 · 시장 · 거래일) · 15:50 은 국내만 · 07:10 은 미국만 · 같은 키는 갱신.
- 거래일은 토스 일봉의 최신 봉 날짜 (휴장일에 날짜가 밀리지 않게).
- 팔린 종목은 수량 0 기록을 남기고, 다시 사면 보유 일수를 새로 센다.
- 보유 일수 = 달력일 차이 · 기준일 = 첫 저널 판정일 → 없으면 기록이 처음 잡힌 날.
- 최고가 = 기준일부터 종가 (일봉) + 오늘 현재가.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import delete, select

from backend.services import real_holdings as rh
from backend.services.models import HoldingSnapshot, UserJudgment


def _item(sym, qty, avg, last, cur, country, **kw):
    it = {"symbol": sym, "name": kw.get("name", sym), "marketCountry": country, "currency": cur,
          "quantity": str(qty), "averagePurchasePrice": str(avg), "lastPrice": str(last)}
    if "mv" in kw:
        it["marketValue"] = {"purchaseAmount": str(kw["cost"]), "amount": str(kw["mv"]), "amountAfterCost": str(kw["mv"])}
    if "pl" in kw:
        it["profitLoss"] = {"amount": str(kw["pl"]), "amountAfterCost": str(kw["pl"]), "rate": "0", "rateAfterCost": "0"}
    return it


def test_parse_items_original_first():
    rows = rh.parse_items({"items": [
        _item("005930", 10, 60000, 70000, "KRW", "KR", mv=700100, cost=600000, pl=100100, name="삼성전자"),
        _item("WEN", 5, 10, 12, "USD", "US"),
        _item("ZERO", 0, 1, 1, "USD", "US"),
        "junk",
    ]})
    kr, us = rows
    assert [r.symbol for r in rows] == ["005930", "WEN"]
    assert kr.market == "KR" and kr.market_value == 700100 and kr.purchase_amount == 600000
    assert kr.pnl == 100100 and kr.pnl_source == "api" and kr.pnl_pct == round(100100 / 600000 * 100, 2)
    assert us.market == "US" and us.market_value == 60 and us.purchase_amount == 50
    assert us.pnl == 10 and us.pnl_source == "computed" and us.pnl_pct == 20.0


def test_parse_items_market_from_currency_when_country_missing():
    it = _item("0101N0", 1, 1, 1, "KRW", None)
    it.pop("marketCountry")
    assert rh.parse_items({"items": [it]})[0].market == "KR"


class _FakeToss:
    def __init__(self, items, candles=None):
        self.items = items
        self.candles_by = candles or {}
        self.candle_calls: list[tuple[str, int]] = []

    def holdings(self, symbol=None):
        return {"items": self.items}

    def candles(self, symbol, count=200):
        self.candle_calls.append((symbol, count))
        bars = self.candles_by.get(symbol, [])
        return {"candles": [{"timestamp": f"{d}T00:00:00-04:00", "closePrice": str(c)} for d, c in bars][:count]}

    def get(self, path, *, params=None, use_account_header=True):  # 환율
        return {"rate": "1400", "validFrom": "2026-10-26T07:10:00+09:00"}


@pytest.fixture
async def clean():
    from backend.services import fx
    from backend.services.db import get_session, init_db

    fx.reset_cache()
    await init_db()
    async with get_session() as s:
        await s.execute(delete(HoldingSnapshot))
        await s.execute(delete(UserJudgment))
    yield
    fx.reset_cache()


async def _snaps(**where):
    from backend.services.db import get_session

    async with get_session() as s:
        q = select(HoldingSnapshot).order_by(HoldingSnapshot.trade_date, HoldingSnapshot.kind)
        for k, v in where.items():
            q = q.where(getattr(HoldingSnapshot, k) == v)
        return (await s.execute(q)).scalars().all()


@pytest.mark.asyncio
async def test_us_snapshot_only_us_and_uses_latest_candle_date(clean):
    fake = _FakeToss(
        [_item("005930", 1, 1, 1, "KRW", "KR"), _item("WEN", 5, 10, 12, "USD", "US")],
        {"WEN": [("2026-10-24", 12.0), ("2026-10-23", 13.0)]},
    )
    out = await rh.snapshot_market("US", client=fake)
    hold = await _snaps(kind="holding")
    assert [(r.symbol, r.trade_date, r.qty) for r in hold] == [("WEN", date(2026, 10, 24), 5.0)]
    assert hold[0].fx_rate == 1400.0 and hold[0].fx_source == "toss" and hold[0].close == 12.0
    assert [(r.trade_date, r.close) for r in await _snaps(kind="candle")] == [(date(2026, 10, 23), 13.0), (date(2026, 10, 24), 12.0)]
    assert fake.candle_calls == [("WEN", 200)]  # 처음은 200봉으로 과거를 채움
    assert out == {"market": "US", "held": 1, "sold": 0, "candles": 2}


@pytest.mark.asyncio
async def test_same_key_updates_and_next_run_asks_few_candles(clean):
    fake = _FakeToss([_item("WEN", 5, 10, 12, "USD", "US")], {"WEN": [("2026-10-24", 12.0)]})
    await rh.snapshot_market("US", client=fake)
    fake.items = [_item("WEN", 7, 10, 12.5, "USD", "US")]
    fake.candles_by = {"WEN": [("2026-10-24", 12.5)]}
    await rh.snapshot_market("US", client=fake)
    hold = await _snaps(kind="holding")
    assert len(hold) == 1 and hold[0].qty == 7.0 and hold[0].close == 12.5
    assert len(await _snaps(kind="candle")) == 1 and fake.candle_calls[-1] == ("WEN", 5)


@pytest.mark.asyncio
async def test_kr_run_does_not_touch_us_and_marks_sold(clean):
    fake = _FakeToss([_item("005930", 1, 1, 70000, "KRW", "KR")], {"005930": [("2026-10-23", 70000)]})
    await rh.snapshot_market("KR", client=fake)
    fake.items = [_item("WEN", 5, 10, 12, "USD", "US")]  # 국내 종목을 팔았음
    fake.candles_by = {"WEN": [("2026-10-24", 12.0)]}
    out = await rh.snapshot_market("KR", client=fake)
    rows = await _snaps(symbol="005930", kind="holding")
    assert [(r.trade_date, r.qty) for r in rows][-1][1] == 0.0
    assert out["sold"] == 1 and out["held"] == 0
    assert await _snaps(symbol="WEN") == []


def _row(sym="WEN", market="US", last=12.0):
    return rh.HoldingRow(symbol=sym, name=sym, market=market, currency="USD", qty=5, avg_price=10, last_price=last,
                         market_value=5 * last, purchase_amount=50, pnl=5 * last - 50, pnl_pct=None, pnl_source="computed")


async def _add(*objs):
    from backend.services.db import get_session

    async with get_session() as s:
        for o in objs:
            s.add(o)


def _snap(d, kind="holding", qty=5.0, close=12.0, sym="WEN", market="US"):
    return HoldingSnapshot(symbol=sym, market=market, trade_date=d, kind=kind, qty=qty if kind == "holding" else None,
                           close=close, currency="USD", saved_at=datetime(2026, 10, 26))


def _judg(ts, sym="WEN"):
    return UserJudgment(ts=ts, ticker=sym, page_source="journal", hypothesis_id="h", thesis_md="t")


@pytest.mark.asyncio
async def test_facts_basis_journal_first_and_peak_from_candles(clean):
    await _add(
        _judg(datetime(2026, 9, 1, 9)), _judg(datetime(2026, 9, 20, 9)),
        _snap(date(2026, 8, 29), "candle", close=20.0),  # 기준일 전 → 최고가에서 뺌
        _snap(date(2026, 9, 2), "candle", close=15.0),
        _snap(date(2026, 10, 1), "candle", close=11.0),
        _snap(date(2026, 10, 24)),
    )
    from backend.services.db import get_session

    async with get_session() as s:
        f = await rh.holding_facts(s, _row(last=12.0), today=date(2026, 10, 26))
    assert f["basis_date"] == date(2026, 9, 1) and f["basis_source"] == "journal"
    assert f["days_held"] == 55
    assert f["peak_close"] == 15.0 and f["peak_date"] == date(2026, 9, 2)
    assert f["from_peak_pct"] == round((12.0 / 15.0 - 1) * 100, 2)
    assert f["peak_complete"] is True  # 일봉이 기준일 이전부터 있음


@pytest.mark.asyncio
async def test_facts_rebuy_after_sold_restarts_count(clean):
    await _add(
        _judg(datetime(2026, 8, 1, 9)),  # 지난 보유 때 판정 → 쓰지 않음
        _snap(date(2026, 10, 1)), _snap(date(2026, 10, 2), qty=0.0),
        _snap(date(2026, 10, 10)), _snap(date(2026, 10, 20)),  # 사이 기록 빠짐은 끊김이 아님
    )
    from backend.services.db import get_session

    async with get_session() as s:
        f = await rh.holding_facts(s, _row(), today=date(2026, 10, 26))
    assert f["basis_date"] == date(2026, 10, 10) and f["basis_source"] == "record" and f["days_held"] == 16


@pytest.mark.asyncio
async def test_facts_no_history_counts_from_today_and_peak_is_now(clean):
    from backend.services.db import get_session

    async with get_session() as s:
        f = await rh.holding_facts(s, _row(last=9.0), today=date(2026, 10, 26))
    assert f["basis_date"] is None and f["days_held"] is None
    assert f["peak_close"] == 9.0 and f["from_peak_pct"] == 0.0 and f["peak_complete"] is False


@pytest.mark.asyncio
async def test_facts_peak_incomplete_when_candles_start_after_basis(clean):
    await _add(_judg(datetime(2026, 1, 5, 9)), _snap(date(2026, 3, 2), "candle", close=10.0))
    from backend.services.db import get_session

    async with get_session() as s:
        f = await rh.holding_facts(s, _row(last=12.0), today=date(2026, 10, 26))
    assert f["peak_complete"] is False and f["peak_close"] == 12.0 and f["from_peak_pct"] == 0.0


@pytest.mark.asyncio
async def test_broken_response_does_not_mark_everything_sold(clean):
    fake = _FakeToss([_item("WEN", 5, 10, 12, "USD", "US")], {"WEN": [("2026-10-24", 12.0)]})
    await rh.snapshot_market("US", client=fake)
    fake.holdings = lambda symbol=None: {"error": "x"}  # items 없음 = 응답 이상
    with pytest.raises(RuntimeError):
        await rh.snapshot_market("US", client=fake)
    assert [r.qty for r in await _snaps(kind="holding")] == [5.0]


# ─── 하루 기록 잡 (cron) ───
@pytest.mark.asyncio
async def test_job_retries_once_on_token_error_then_alerts(monkeypatch):
    from backend.execution.exceptions import BrokerCommunicationError
    from backend.scheduler import cron

    calls, alerts = [], []

    async def flaky(market, client=None, now=None):
        calls.append(market)
        raise BrokerCommunicationError("토큰 만료 — 재시도 필요")

    async def fake_alert(name, exc, hour=None, minute=None):
        alerts.append((name, hour, minute))

    monkeypatch.setattr(rh, "snapshot_market", flaky)
    monkeypatch.setattr(cron, "_alert_job_failure", fake_alert)
    await cron.job_holdings_snapshot_us()
    assert calls == ["US", "US"] and alerts == [("토스 보유 기록 (미국)", 7, 10)]


@pytest.mark.asyncio
async def test_job_kr_success_no_alert(monkeypatch):
    from backend.scheduler import cron

    alerts = []

    async def ok(market, client=None, now=None):
        return {"market": market}

    async def fake_alert(*a, **k):
        alerts.append(a)

    monkeypatch.setattr(rh, "snapshot_market", ok)
    monkeypatch.setattr(cron, "_alert_job_failure", fake_alert)
    await cron.job_holdings_snapshot_kr()
    assert alerts == []


def test_jobs_registered_on_market_days():
    from backend.scheduler import cron

    jobs = {j.id: j for j in cron.build_scheduler().get_jobs()}
    kr, us = str(jobs["holdings_snapshot_kr"].trigger), str(jobs["holdings_snapshot_us"].trigger)
    assert "hour='15'" in kr and "minute='50'" in kr and "day_of_week='mon-fri'" in kr
    assert "hour='7'" in us and "minute='10'" in us and "day_of_week='tue-sat'" in us
