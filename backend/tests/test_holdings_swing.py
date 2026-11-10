"""1108-02 · 보유 종목 사실 (스윙 2단계) — 계획 5절 「만들 것」 시험 + 검토 1108-02-07 권고 (ㄹ).

티커·수량·평단은 모두 가짜 값이다 (실제 보유 종목 아님). 시각은 시험 안에서 고정한다 (교훈 #5 — 요일·시각에 기대지 않음).
"""
from __future__ import annotations

import ast
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from backend.services import holdings_swing as hs
from backend.services.models import (
    HoldingHorizon,
    HoldingSnapshot,
    KrOfficialClose,
    SwingLongClose,
    SwingReference,
)

TOKEN = "holdings_swing_test_token_32chars"
KR, US = "900001", "ZZZA"
# 금요일 16:00 KST 로 고정 (UTC 07:00)
NOW = datetime(2026, 11, 6, 7, 0, tzinfo=timezone.utc)
TODAY = date(2026, 11, 6)


@pytest.fixture
async def clean(monkeypatch):
    from backend.services.db import get_session, init_db

    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    await init_db()
    async with get_session() as s:
        for m in (HoldingSnapshot, HoldingHorizon, KrOfficialClose, SwingReference, SwingLongClose):
            await s.execute(delete(m))
    yield


@pytest.fixture
async def http(clean):
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _add(*objs):
    from backend.services.db import get_session

    async with get_session() as s:
        for o in objs:
            s.add(o)


def _hold(sym, market, d, qty=10.0, close=100.0, avg=100.0, cur="KRW", fx=None):
    return HoldingSnapshot(symbol=sym, market=market, trade_date=d, kind="holding", qty=qty, close=close,
                           avg_price=avg, currency=cur, fx_rate=fx, purchase_amount=avg * qty,
                           market_value=close * qty, saved_at=datetime(2026, 11, 1))


def _candle(sym, market, d, close):
    return HoldingSnapshot(symbol=sym, market=market, trade_date=d, kind="candle", close=close, saved_at=datetime(2026, 11, 1))


def _days(n, end=TODAY):
    """end 까지 거꾸로 n개 평일."""
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


def _frame(pairs):
    return pd.DataFrame({"종가": [c for _, c in pairs]}, index=pd.to_datetime([d for d, _ in pairs]))


async def _official(ticker=KR):
    from backend.services.db import get_session

    async with get_session() as s:
        return (await s.execute(select(KrOfficialClose).where(KrOfficialClose.ticker == ticker)
                                .order_by(KrOfficialClose.trade_date))).scalars().all()


# ─── 공식 종가 이어 받기 (조건 1) ───

@pytest.mark.asyncio
async def test_official_fill_is_idempotent(clean):
    await _add(_hold(KR, "KR", TODAY))
    calls = []

    async def fetch(t, start, end):
        calls.append((t, start, end))
        return _frame([(TODAY - timedelta(days=1), 99.0), (TODAY, 101.0)])

    r1 = await hs.fill_official_closes(NOW, fetch)
    r2 = await hs.fill_official_closes(NOW, fetch)
    rows = await _official()
    assert [(x.trade_date, x.close) for x in rows] == [(TODAY - timedelta(days=1), 99.0), (TODAY, 101.0)]
    assert r1["rows"] == 2
    assert calls[0][1] == TODAY - timedelta(days=hs.FIRST_FILL_CALENDAR_DAYS)  # 처음은 약 160거래일 치
    assert len(calls) == 1  # 이미 오늘까지 있으면 두 번째는 받지 않음 (행 1개 유지)
    assert r2["rows"] == 0


@pytest.mark.asyncio
async def test_official_fill_never_writes_today_when_source_has_older_last_row(clean):
    await _add(_hold(KR, "KR", TODAY))
    yesterday = TODAY - timedelta(days=1)

    async def fetch(t, start, end):
        return _frame([(yesterday, 99.0)])  # 15:50 에 오늘 값이 아직 없음

    await hs.fill_official_closes(NOW, fetch)
    assert [x.trade_date for x in await _official()] == [yesterday]  # 어제 값을 오늘로 적지 않음


@pytest.mark.asyncio
async def test_official_fill_ignores_future_rows_and_fills_gap_next_run(clean):
    await _add(_hold(KR, "KR", TODAY))
    d1, d2, d3 = TODAY - timedelta(days=3), TODAY - timedelta(days=2), TODAY - timedelta(days=1)
    await _add(KrOfficialClose(ticker=KR, trade_date=d1, close=90.0))
    seen = []

    async def fetch(t, start, end):
        seen.append(start)
        return _frame([(d2, 91.0), (d3, 92.0), (TODAY + timedelta(days=2), 1.0)])  # 미래 날짜는 버림

    await hs.fill_official_closes(NOW, fetch)
    assert seen == [d1 + timedelta(days=1)]  # 마지막 저장일 다음 날부터
    assert [x.trade_date for x in await _official()] == [d1, d2, d3]


@pytest.mark.asyncio
async def test_official_fill_uses_to_thread_loader_by_default(clean, monkeypatch):
    """조건 2: 기존 loader.fetch_daily_candles(asyncio.to_thread) 를 그대로 쓴다."""
    from backend.discovery.data_sources.krx_price import loader

    await _add(_hold(KR, "KR", TODAY))
    used = []

    def fake_sync(start, end, ticker):
        used.append((start, end, ticker))
        return _frame([(TODAY, 101.0)])

    monkeypatch.setattr(loader, "_fetch_ohlcv_sync", fake_sync)
    await hs.fill_official_closes(NOW)
    assert used and used[0][2] == KR and used[0][1] == "20261106"
    assert len(await _official()) == 1


# ─── 이어 받기가 실패해도 보유 기록은 남고, 경고는 하루 1회 (조건 2) ───

@pytest.mark.asyncio
async def test_followup_failure_keeps_holding_record_and_alerts_once(clean, monkeypatch):
    from backend.scheduler import cron
    from backend.services import notifier as nmod
    from backend.services import real_holdings as rh

    sent = []

    class _Notifier:
        async def send_warning(self, title, body, **kw):
            sent.append(title)
            return True

    async def fake_snapshot(market, client=None, now=None):  # 보유 기록은 먼저 저장됨
        from backend.services.db import get_session

        async with get_session() as s:
            if (await s.execute(select(HoldingSnapshot).where(HoldingSnapshot.kind == "holding"))).first() is None:
                s.add(_hold(KR, "KR", TODAY))
        return {"market": market}

    async def boom(*a, **k):
        raise RuntimeError("KRX 조회 막힘")

    async def refs_ok(*a, **k):
        return {}

    monkeypatch.setattr(nmod, "TelegramNotifier", _Notifier)
    monkeypatch.setattr(cron, "_failure_alerted", {})
    monkeypatch.setattr(rh, "snapshot_market", fake_snapshot)
    monkeypatch.setattr(hs, "fill_official_closes", boom)
    monkeypatch.setattr(hs, "refresh_references", refs_ok)
    monkeypatch.setattr(hs, "fill_long_closes", refs_ok)  # 외부 호출 없음
    await cron.job_holdings_snapshot_kr()
    await cron.job_holdings_snapshot_kr()  # 같은 날 두 번째 실패
    from backend.services.db import get_session

    async with get_session() as s:
        n = (await s.execute(select(HoldingSnapshot).where(HoldingSnapshot.kind == "holding"))).scalars().all()
    assert len(n) == 1  # 보유 기록 유지
    assert len(sent) == 1 and "공식 종가" in sent[0]  # 하루 1회


@pytest.mark.asyncio
async def test_followup_runs_separately_each_step(clean, monkeypatch):
    from backend.scheduler import cron

    order = []

    async def boom(*a, **k):
        order.append("official")
        raise RuntimeError("x")

    async def refs(market, *a, **k):
        order.append("refs")
        return {}

    async def no_alert(*a, **k):
        order.append("alert")

    monkeypatch.setattr(hs, "fill_official_closes", boom)
    async def longs(market, *a, **k):
        order.append("long")
        return {}

    monkeypatch.setattr(hs, "refresh_references", refs)
    monkeypatch.setattr(hs, "fill_long_closes", longs)
    monkeypatch.setattr(cron, "_alert_job_failure", no_alert)
    await cron.run_swing_followup("KR", 15, 50)
    assert order == ["official", "alert", "refs", "long"]  # 앞 단계가 실패해도 다음 단계는 돈다 · 긴 일봉은 맨 뒤
    order.clear()
    await cron.run_swing_followup("US", 7, 10)
    assert order == ["refs", "long"]  # 미국은 공식 종가 단계 없음


@pytest.mark.asyncio
async def test_all_tickers_failing_raises(clean):
    await _add(_hold(KR, "KR", TODAY))

    async def fetch(*a):
        raise ConnectionError("blocked")

    with pytest.raises(RuntimeError):
        await hs.fill_official_closes(NOW, fetch)


# ─── 인증 · PATCH 값 제한 ───

@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [("get", "/api/v1/account/swing"), ("patch", f"/api/v1/account/swing/KR/{KR}")])
async def test_swing_requires_token(http, method, path):
    kw = {"json": {"horizon": "long"}} if method == "patch" else {}
    assert (await getattr(http, method)(path, **kw)).status_code in (401, 403)
    bad = await getattr(http, method)(path, headers={"X-API-Token": "wrong"}, **kw)
    assert bad.status_code in (401, 403)


@pytest.mark.asyncio
async def test_patch_horizon_values_limited_and_roundtrip(http):
    h = {"X-API-Token": TOKEN}
    url = f"/api/v1/account/swing/KR/{KR}"
    for bad in ("buy", "sell", "", "LONG", None):
        assert (await http.patch(url, json={"horizon": bad}, headers=h)).status_code == 422
    assert (await http.patch("/api/v1/account/swing/JP/X1", json={"horizon": "long"}, headers=h)).status_code == 422
    assert (await http.patch("/api/v1/account/swing/KR/bad%20ticker!", json={"horizon": "long"}, headers=h)).status_code == 422
    ok = await http.patch(url, json={"horizon": "short"}, headers=h)
    assert ok.status_code == 200 and ok.json()["horizon"] == "short"
    await http.patch(url, json={"horizon": "long"}, headers=h)
    async with __import__("backend.services.db", fromlist=["get_session"]).get_session() as s:
        assert [r.horizon for r in (await s.execute(select(HoldingHorizon))).scalars().all()] == ["long"]
    gone = await http.patch(url, json={"horizon": "unset"}, headers=h)
    assert gone.json()["horizon"] is None  # 응답은 unset → null
    async with __import__("backend.services.db", fromlist=["get_session"]).get_session() as s:
        assert [r.horizon for r in (await s.execute(select(HoldingHorizon))).scalars().all()] == ["unset"]  # 행은 보존


# ─── 사실 계산 · 보류 ───

def test_ma_distance_values_and_missing_120():
    closes = [100.0] * 60 + [110.0] * 20
    m = {x["days"]: x for x in hs.ma_distances(closes)}
    assert m[20]["distance_pct"] == 0.0 + round((110 / 110 - 1) * 100, 2)  # 최근 20일 평균 110
    assert m[60]["distance_pct"] == round((110 / (sum(closes[-60:]) / 60) - 1) * 100, 2)
    assert m[120]["distance_pct"] is None and m[120]["note"] == "자료 부족"  # 일봉 < 120 이면 120일 평균만


async def _seed_card(market, sym, closes, horizon="short", official=True, hold_rows=None):
    days = _days(len(closes))
    objs = [_candle(sym, market, d, c) for d, c in zip(days, closes)]
    if market == "KR" and official:
        objs += [KrOfficialClose(ticker=sym, trade_date=d, close=c) for d, c in zip(days, closes)]
    objs += hold_rows if hold_rows is not None else [_hold(sym, market, days[-1], close=closes[-1],
                                                           cur="KRW" if market == "KR" else "USD")]
    if horizon:
        objs.append(HoldingHorizon(market=market, ticker=sym, horizon=horizon))
    await _add(*objs)


async def _cards():
    from backend.services.db import get_session

    async with get_session() as s:
        return {(c["market"], c["symbol"]): c for c in await hs.build_cards(s, TODAY)}


@pytest.mark.asyncio
async def test_card_holds_when_horizon_unset(clean):
    await _seed_card("US", US, [10.0 + i * 0.01 for i in range(130)], horizon=None)
    c = (await _cards())[("US", US)]
    assert c["status"] == "hold" and "보유 성격을 정하면 보여 드립니다" in c["hold_reason"] and c["ma"] == []


@pytest.mark.asyncio
async def test_card_holds_under_20_bars_and_partial_under_120(clean):
    await _seed_card("US", US, [10.0] * 19)
    assert (await _cards())[("US", US)]["status"] == "hold"
    await _add(HoldingHorizon(market="US", ticker="ZZZB", horizon="long"))
    days = _days(60)
    await _add(*[_candle("ZZZB", "US", d, 10.0 + i * 0.01) for i, d in enumerate(days)], _hold("ZZZB", "US", days[-1], cur="USD"))
    c = (await _cards())[("US", "ZZZB")]
    assert c["status"] == "ok" and [m["note"] for m in c["ma"]] == [None, None, "자료 부족", "200일 자료 부족"]


@pytest.mark.asyncio
async def test_card_holds_on_split_suspect(clean):
    closes = [100.0] * 40 + [50.0] + [50.0] * 40
    await _seed_card("US", US, closes)
    c = (await _cards())[("US", US)]
    assert c["status"] == "hold" and "±30%" in c["hold_reason"]


@pytest.mark.asyncio
async def test_kr_card_holds_without_official_and_never_falls_back_to_toss(clean):
    await _seed_card("KR", KR, [100.0 + i for i in range(130)], official=False)
    c = (await _cards())[("KR", KR)]
    assert c["status"] == "hold" and "공식 종가" in c["hold_reason"] and c["ma"] == []


@pytest.mark.asyncio
async def test_kr_card_holds_when_official_lags_behind_toss_day(clean):
    days = _days(130)
    objs = [_candle(KR, "KR", d, 100.0 + i) for i, d in enumerate(days)]
    objs += [KrOfficialClose(ticker=KR, trade_date=d, close=100.0 + i) for i, d in enumerate(days[:-1])]  # 오늘 값 빠짐
    await _add(*objs, _hold(KR, "KR", days[-1]), HoldingHorizon(market="KR", ticker=KR, horizon="long"))
    assert (await _cards())[("KR", KR)]["status"] == "hold"


@pytest.mark.asyncio
async def test_kr_card_uses_official_for_averages_and_flags_gap_over_2pct(clean):
    days = _days(130)
    await _add(*[KrOfficialClose(ticker=KR, trade_date=d, close=100.0) for d in days],
               *[_candle(KR, "KR", d, 100.0) for d in days[:-1]], _candle(KR, "KR", days[-1], 103.0),  # 토스 종가만 3% 다름
               _hold(KR, "KR", days[-1], close=103.0), HoldingHorizon(market="KR", ticker=KR, horizon="long"))
    c = (await _cards())[("KR", KR)]
    assert c["status"] == "ok" and c["close_source"] == "krx"
    assert all(m["distance_pct"] == 0.0 for m in c["ma"][:3])  # 평균 거리는 공식 종가로 계산
    assert c["source_gap"]["flag"] is True and c["source_gap"]["gap_pct"] == 3.0
    assert c["real_avg"]["text"] == "보류 · 판 값 기록 없음"  # 조건 4


@pytest.mark.asyncio
async def test_kr_gap_within_2pct_not_flagged(clean):
    days = _days(130)
    await _add(*[KrOfficialClose(ticker=KR, trade_date=d, close=100.0) for d in days],
               *[_candle(KR, "KR", d, 101.5) for d in days], _hold(KR, "KR", days[-1]),
               HoldingHorizon(market="KR", ticker=KR, horizon="long"))
    assert (await _cards())[("KR", KR)]["source_gap"]["flag"] is False


@pytest.mark.asyncio
async def test_peak_reuses_holding_facts_with_basis(clean):
    """조건 3: 최고 종가 대비 하락은 holding_facts 값 그대로 + 기준일·완전 여부."""
    days = _days(130)
    closes = [10.0 + i * 0.01 for i in range(130)]
    closes[127] = 12.5
    await _seed_card("US", US, closes, hold_rows=[_hold(US, "US", d, close=closes[i], cur="USD") for i, d in enumerate(days)][-5:])
    p = (await _cards())[("US", US)]["peak"]
    assert p["peak_close"] == 12.5 and p["basis_source"] == "record" and p["basis_date"] == days[-5]
    assert p["peak_complete"] is True  # 일봉이 기준일보다 먼저 시작하므로 기록 전 기간 제외 표시는 필요 없음
    from backend.services.db import get_session
    from backend.services.real_holdings import HoldingRow, holding_facts

    async with get_session() as s:
        row = HoldingRow(US, None, "US", "USD", 10, 100, closes[-1], None, 1000, None, None, "computed")
        f = await holding_facts(s, row, TODAY)
    assert f["from_peak_pct"] == p["from_peak_pct"]


# ─── 대형·대표 N/3 ───

@pytest.mark.asyncio
async def test_blue_chip_counts_and_missing_is_no_data(clean):
    closes = [100.0 + (i % 2) * 0.1 for i in range(130)]  # 변동성 작음
    await _seed_card("US", US, closes, horizon="long")
    await _add(SwingReference(market="US", ticker=US, item="size", value=150e9, as_of=TODAY),
               SwingReference(market="US", ticker=US, item="earnings", value=-1.0, as_of=TODAY))
    bc = (await _cards())[("US", US)]["blue_chip"]
    st = {i["key"]: i["state"] for i in bc["items"]}
    assert st == {"size": "met", "earnings": "not_met", "vol": "met"} and bc["met"] == 2


@pytest.mark.asyncio
async def test_blue_chip_no_reference_rows_is_no_data_not_zero(clean):
    await _seed_card("US", US, [100.0 + (i % 2) * 0.1 for i in range(130)], horizon="long")
    st = {i["key"]: i["state"] for i in (await _cards())[("US", US)]["blue_chip"]["items"]}
    assert st["size"] == "none" and st["earnings"] == "none"  # 「자료 없음」 — 충족 아님으로 세지 않고 그렇게 적음


def test_us_constants_have_dates_and_source():
    assert hs.US_VOL_AS_OF == date(2026, 11, 6) and 1.0 < hs.US_VOL_MEDIAN < 3.0 and hs.US_VOL_SAMPLE == 99
    assert "AAPL" in hs.US_SP100 and len(hs.US_SP100) == 100


# ─── 흑자 전환일 (조건 5) ───

def _streak(market, nets, avg=100.0, fx_list=None):
    """net % 가 주어진 값이 되도록 종가를 만든 보유 행 (비용 반영 전 종가 = avg*(1+net)/(1-cost))."""
    c = hs.SELL_COST[market]
    days = _days(len(nets))
    return [_hold("S", market, d, close=avg * (1 + n / 100) / (1 - c), avg=avg, cur="KRW" if market == "KR" else "USD",
                  fx=(fx_list[i] if fx_list else None)) for i, (d, n) in enumerate(zip(days, nets))]


def test_profit_turn_boundary_prev_le_zero_and_cur_gt_zero():
    t = hs.profit_turn(_streak("KR", [-1.0, 0.0, 0.01]), "KR")
    assert t and t["turn_date"] == _days(3)[2]  # 직전 0.00 (≤0) → 그날 +0.01 (>0)
    assert hs.profit_turn(_streak("KR", [-1.0, 0.0, 0.0]), "KR") is None  # 0 은 흑자 아님
    assert hs.profit_turn(_streak("KR", [1.0, 2.0, 3.0]), "KR") is None  # 기록 시작부터 흑자면 없음


def test_profit_turn_costs_matter():
    # 비용 전 +0.1% 라도 비용(0.215%)을 빼면 적자 → 전환 아님
    c = hs.SELL_COST["KR"]
    days = _days(2)
    rows = [_hold("S", "KR", days[0], close=99.0, avg=100.0), _hold("S", "KR", days[1], close=100.1, avg=100.0)]
    assert hs.net_pnl_pct(100.1, 100.0, "KR") < 0 < hs.net_pnl_pct(100.0 / (1 - c) + 0.01, 100.0, "KR")
    assert hs.profit_turn(rows, "KR") is None


def test_profit_turn_window_is_five_rows_after_and_latest_turn_wins():
    nets = [-1.0, 1.0] + [2.0] * 5          # 전환 뒤 보유 기록 5개
    assert hs.profit_turn(_streak("US", nets), "US")["rows_since"] == 5
    assert hs.profit_turn(_streak("US", nets + [2.0]), "US") is None  # 6개째부터 사라짐
    again = hs.profit_turn(_streak("US", [-1.0, 1.0, 2.0, -0.5, 0.5]), "US")  # 여러 번이면 그때마다
    assert again["rows_since"] == 0 and again["turn_date"] == _days(5)[4]


def test_profit_turn_us_uses_dollars_not_won():
    """달러 손익은 흑자인데 원화 손익은 적자인 경우 — 판정은 달러 기준 (환율이 내려도 전환으로 본다)."""
    rows = _streak("US", [-1.0, 1.0], fx_list=[1500.0, 1300.0])
    t = hs.profit_turn(rows, "US")
    assert t is not None
    won_prev = rows[0].close * rows[0].fx_rate
    won_cur = rows[1].close * rows[1].fx_rate
    avg_won = 100.0 * 1500.0
    assert won_cur < avg_won < won_prev * 2 and (won_cur - avg_won) < 0  # 원화로는 적자


@pytest.mark.asyncio
async def test_card_third_layer_only_for_short_and_has_required_parts(clean):
    days = _days(130)
    closes = [100.0] * 128 + [100.0, 112.0]
    holds = [_hold(US, "US", d, close=closes[i], avg=105.0, cur="USD") for i, d in enumerate(days)][-6:]
    await _seed_card("US", US, closes, horizon="short", hold_rows=holds)
    t = (await _cards())[("US", US)]["profit_turn"]
    assert t and t["layer"]["sample"] == "표본 225창" and "대형주 표본 · 이 종목 자료 아님" in t["layer"]["caveat"]
    assert "추정 · 보장 아님" in t["layer"]["caveat"]
    assert "비교 ②" in t["layer"]["source"]
    assert t["layer"]["mean"] == "평균 1.8% / 4.4%" and t["layer"]["median_diff"] == "중앙값 차이 +1.38%p"
    assert t["layer"]["bottom5"] == "가장 나쁜 5% -2.2% / -9.5%" and t["cost_note"].startswith("비용 추정")
    kr = hs.third_layer_lines("KR")
    assert kr["mean"] == "평균 2.5% / 4.4%" and kr["median_diff"] == "중앙값 차이 -0.77%p" and kr["sample"] == "표본 180창"
    assert kr["bottom5"] == "가장 나쁜 5% -3.3% / -28.5%"
    # 장기로 바꾸면 3층 없음
    async with __import__("backend.services.db", fromlist=["get_session"]).get_session() as s:
        await hs.set_horizon(s, "US", US, "long")
    assert (await _cards())[("US", US)]["profit_turn"] is None


# ─── 금지 낱말 · 면책 문구 (정적 + 실제 출력) ───

FORBIDDEN = re.compile(r"buy|sell|stop|trailing|추가 매수|손절|이익 보호|추적|사십시오|파십시오|장기로 하십시오|물타기"
                       r"|골든|데드|크로스|교차|정배열|역배열|신호|40주선 매매|위면 보유|아래면 현금|현금으로|사라(?!지)|팔라|매도하|매수하", re.I)


def _module_string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            d = ast.get_docstring(n, clean=False)
            if d:
                docstrings.add(d)
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value not in docstrings]


def test_no_forbidden_words_in_backend_strings():
    literals = _module_string_literals(Path(hs.__file__))
    bad = [s for s in literals if FORBIDDEN.search(s)]
    assert bad == [], bad


def test_no_forbidden_words_in_frontend_component():
    root = Path(hs.__file__).resolve().parents[2] / "frontend"
    for rel in ("components/account/HoldingSwing.tsx", "components/account/Week40Chart.tsx", "lib/holdings-swing.ts",
                "components/account/CrossMarks.tsx", "components/account/MaChart.tsx"):
        text = (root / rel).read_text(encoding="utf-8")
        assert FORBIDDEN.search(text) is None, rel


@pytest.mark.asyncio
async def test_every_card_text_is_free_of_forbidden_words_and_has_disclaimer(clean):
    import json

    days = _days(130)
    closes = [100.0] * 128 + [100.0, 112.0]
    holds = [_hold(US, "US", d, close=closes[i], avg=105.0, cur="USD") for i, d in enumerate(days)][-6:]
    await _seed_card("US", US, closes, horizon="short", hold_rows=holds)
    await _seed_card("KR", KR, [100.0 + i for i in range(130)], horizon="long", official=False)
    for c in (await _cards()).values():
        assert hs.DISCLAIMER == c["disclaimer"] == "추정 · 보장 아님"
        assert FORBIDDEN.search(json.dumps(c, ensure_ascii=False, default=str)) is None


def test_holdings_swing_frontend_helpers_check():
    import shutil
    import subprocess

    fe = Path(hs.__file__).resolve().parents[2] / "frontend"
    if shutil.which("npx") is None or not (fe / "node_modules").exists():
        pytest.skip("npx 또는 node_modules 없음")
    r = subprocess.run(["npx", "--yes", "tsx", "lib/holdings-swing.check.ts"], cwd=fe, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    assert "holdings-swing ok" in r.stdout


# ═══════════════════════════════════════════════════════════════
# 3단계 · 목표까지 거리 · 기한 · 메모 (계획 6절 · 검토 1108-02-12 막음 1~6)
# 종목 기호·가격은 모두 가짜 값이다.
# ═══════════════════════════════════════════════════════════════

from statistics import NormalDist  # noqa: E402


def _long_dates(n, end=TODAY):
    return _days(n, end)


async def _seed_long(market, sym, closes, end=TODAY, source="yfinance close"):
    days = _long_dates(len(closes), end)
    await _add(*[SwingLongClose(market=market, ticker=sym, trade_date=d, close=c, source=source) for d, c in zip(days, closes)])
    return days


def _wave(n, base=100.0, amp=1.0):
    """작은 가짜 계열: 위아래로 번갈아 움직임."""
    return [base + (amp if i % 2 else -amp) + i * 0.01 for i in range(n)]


async def _short_card(avg=110.0, last=100.0, long_closes=None, horizon="short", market="US", sym=US, **kw):
    closes = [100.0] * 129 + [last]
    cur = "USD" if market == "US" else "KRW"
    days = _days(len(closes))
    holds = [_hold(sym, market, days[-1], close=last, avg=avg, cur=cur)]
    await _seed_card(market, sym, closes, horizon=horizon, hold_rows=holds, **kw)
    if long_closes is not None:
        await _seed_long(market, sym, long_closes)
    return (await _cards())[(market, sym)]


# ─── 계산 (순수 함수) ───

def test_need_rise_and_breakeven_edges():
    r = hs.need_rise(110.0, 100.0, "US")
    assert r == pytest.approx(110.0 / (100.0 * 0.998) - 1)  # 미국 비용 0.2%
    assert hs.need_rise(110.0, 100.0, "KR") == pytest.approx(110.0 / (100.0 * (1 - 0.00215)) - 1)  # 국내 0.215%
    assert hs.need_rise(100.0, 101.0, "US") < 0  # 본전 위


def test_weekdays_between_counts_weekdays_only():
    fri = date(2026, 11, 6)
    assert hs.weekdays_between(fri, fri) == 0
    assert hs.weekdays_between(fri, date(2026, 11, 8)) == 0  # 토·일
    assert hs.weekdays_between(fri, date(2026, 11, 9)) == 1
    assert hs.weekdays_between(fri, date(2026, 11, 13)) == 5
    assert hs.weekdays_between(fri, date(2027, 11, 6)) == 260  # 365일 = 52주 + 토요일 하루
    assert hs.weekdays_between(date(2026, 11, 9), fri) == 0  # 지났으면 0


def test_reflect_hit_prob_known_value():
    sigma, days = 0.02, 100
    r = math.exp(sigma * math.sqrt(days)) - 1  # ln(1+R) = σ√T → 2(1 − Φ(1))
    assert hs.reflect_hit_prob(r, sigma, days) == pytest.approx(2 * (1 - NormalDist().cdf(1.0)), abs=1e-12)
    assert hs.reflect_hit_prob(r, sigma, days) == pytest.approx(0.3173, abs=1e-4)
    assert hs.reflect_hit_prob(0.0, sigma, days) is None and hs.reflect_hit_prob(r, 0.0, days) is None


def test_own_history_hit_on_small_fake_series():
    closes = [100, 101] * 5  # 100,101,100,101,...
    frac, n = hs.own_history_hit(closes, 0.005, 2)
    assert n == 7 and frac == pytest.approx(4 / 7)  # 100 에서 산 날만 2일 안 +0.5% 이상
    assert hs.own_history_hit([100.0] * 3, 0.01, 5) == (None, 0)


def test_drawdown_events_ended_and_ongoing():
    closes = [100, 100, 60, 50, 70, 100, 90, 60, 55]
    ev = hs.drawdown_events(closes)
    assert [(e["start_idx"], e["days"]) for e in ev] == [(2, 3), (7, None)]  # 앞 고점 회복까지 3거래일 · 두 번째는 진행 중
    assert ev[0]["depth"] == pytest.approx(-0.5) and ev[1]["depth"] == pytest.approx(-0.45)
    g = hs.long_goal(closes, _long_dates(len(closes)), avg=120.0, close=55.0)
    d = g["drawdowns"]
    assert (d["ended"], d["recovered"], d["days_min"], d["days_max"], d["days_median"]) == (1, 1, 3, 3, 3)
    assert d["ongoing"]["depth_pct"] == -45.0 and d["ongoing"]["start"] == _long_dates(len(closes))[7]
    assert g["cushion_pct"] == pytest.approx((120 / 55 - 1) * 100, abs=0.01)
    assert g["ath"]["close"] == 100 and g["ath"]["from_ath_pct"] == -45.0


def test_default_deadline_is_basis_plus_one_year():
    assert hs.default_deadline(date(2026, 11, 6)) == date(2027, 11, 6)
    assert hs.default_deadline(date(2028, 2, 29)) == date(2029, 2, 28)
    assert hs.default_deadline(None) is None


# ─── 카드 · 목표 (DB 만 읽음) ───

@pytest.mark.asyncio
async def test_short_goal_values_and_default_deadline_with_basis(clean):
    c = await _short_card(long_closes=_wave(400))
    g = c["goal"]
    assert g["kind"] == "short" and g["above_breakeven"] is False
    assert g["need_pct"] == round((110.0 / (100.0 * 0.998) - 1) * 100, 2)
    assert g["cost_pct"] == 0.2 and g["basis"] == {"close": 100.0, "date": TODAY, "source": "toss"}
    assert g["deadline"] == date(2027, 11, 6) and g["deadline_source"] == "default"
    assert g["deadline_basis_date"] == TODAY and g["deadline_basis_source"] == "record"
    assert g["days_left"] == 260 and g["past_deadline"] is False
    assert [w["label"] for w in g["windows"]] == ["3개월", "6개월", "기한까지"]
    assert [w["days"] for w in g["windows"]] == [63, 126, 260]
    assert len(g["limits"]) == 4 and g["disclaimer"] == "추정 · 보장 아님"
    assert c["deadline"] is None and c["memo"] is None  # 사용자 값은 비어 있음
    assert all(w["own"]["pct"] is not None and w["model"]["pct"] is not None for w in g["windows"][:2])


@pytest.mark.asyncio
async def test_long_goal_card_has_cushion_ath_drawdowns_and_no_short_fields(clean):
    long_closes = [100.0, 100.0, 60.0, 50.0, 70.0, 100.0, 90.0] * 60
    c = await _short_card(avg=120.0, last=100.0, long_closes=long_closes, horizon="long")
    g = c["goal"]
    assert g["kind"] == "long" and g["cushion_pct"] == 20.0
    assert g["ath"]["close"] == 100.0 and g["ath"]["from_ath_pct"] == 0.0
    assert g["drawdowns"]["threshold_pct"] == 30 and g["drawdowns"]["ended"] >= 1
    assert "windows" not in g and "need_pct" not in g
    assert g["long_series"]["n"] == len(long_closes) and g["long_series"]["source"] == "yfinance close"


@pytest.mark.asyncio
async def test_goal_dates_basis_uses_card_close_not_long_series(clean):
    """막음 4: 수준 비교는 카드 기준 종가(국내 공식 · 미국 토스) — 긴 계열의 마지막 값을 쓰지 않는다."""
    c = await _short_card(avg=120.0, last=100.0, long_closes=[50.0] * 300, horizon="long")
    g = c["goal"]
    assert g["basis"]["close"] == 100.0 and g["cushion_pct"] == 20.0  # 긴 계열 마지막 50 이 아님
    assert g["ath"]["close"] == 50.0 and g["ath"]["from_ath_pct"] == 100.0  # 역대 최고는 긴 계열의 최고
    kr = await _short_card(avg=120.0, last=100.0, long_closes=[50.0] * 300, horizon="long", market="KR", sym=KR)
    assert kr["goal"]["basis"]["source"] == "krx"


# ─── 경계 (막음 5) ───

@pytest.mark.asyncio
async def test_boundaries_above_breakeven_past_deadline_and_missing_series(clean):
    above = await _short_card(avg=99.0, last=100.0, long_closes=_wave(400))
    g = above["goal"]
    assert g["above_breakeven"] is True and g["need_pct"] is None and g["windows"] == []  # 이미 본전 위
    # 기한 지남 (본전 아래 종목)
    await _short_card(avg=110.0, last=100.0, long_closes=_wave(400), sym="ZZZB")
    async with __import__("backend.services.db", fromlist=["get_session"]).get_session() as s:
        row = (await s.execute(select(HoldingHorizon).where(HoldingHorizon.ticker == "ZZZB"))).scalars().one()
        row.deadline = TODAY - timedelta(days=3)
    past = (await _cards())[("US", "ZZZB")]["goal"]
    assert past["past_deadline"] is True and past["days_left"] == 0 and past["deadline_source"] == "user"
    assert [w["label"] for w in past["windows"]] == ["3개월", "6개월"]  # 기한 창은 없음
    assert past["deadline_basis_date"] is None


@pytest.mark.asyncio
async def test_no_long_series_only_goal_cells_say_no_data(clean):
    c = await _short_card(avg=110.0, last=100.0, long_closes=None)
    g = c["goal"]
    assert c["status"] == "ok" and c["ma"]  # 앞 칸은 그대로
    assert g["long_series"] is None and g["sigma120_pct"] is None
    for w in g["windows"]:
        assert w["own"]["pct"] is None and w["own"]["note"] == "자료 없음" and w["model"]["note"] == "자료 없음" and w["diff_pp"] is None
    longc = await _short_card(avg=110.0, last=100.0, long_closes=None, horizon="long", sym="ZZZB")
    assert longc["goal"]["ath"] is None and longc["goal"]["drawdowns"] is None and longc["goal"]["cushion_pct"] == 10.0


@pytest.mark.asyncio
async def test_under_120_bars_model_no_data_and_small_sample_flag(clean):
    c = await _short_card(avg=105.0, last=100.0, long_closes=_wave(100))
    g = c["goal"]
    assert g["sigma120_pct"] is None
    w = g["windows"][0]
    assert w["model"] == {"pct": None, "note": "자료 없음"} and w["diff_pp"] is None
    assert w["own"]["note"] == "표본 적음" and w["own"]["n"] < 250 and w["own"]["pct"] is not None  # 표본 적음이어도 값은 함께


@pytest.mark.asyncio
async def test_enough_history_has_both_methods_and_diff_from_unrounded(clean):
    import random

    rnd = random.Random(7)
    closes = [100.0]
    for _ in range(1500):
        closes.append(closes[-1] * math.exp(rnd.gauss(0, 0.02)))
    c = await _short_card(avg=106.0, last=100.0, long_closes=closes)
    g = c["goal"]
    assert g["sigma120_pct"] is not None and g["long_series"]["n"] == 1501
    w = g["windows"][0]
    assert w["own"]["note"] is None and w["own"]["n"] == 1501 - 63 - 1
    frac, _ = hs.own_history_hit(closes, hs.need_rise(106.0, 100.0, "US"), 63)
    prob = hs.reflect_hit_prob(hs.need_rise(106.0, 100.0, "US"), hs.sigma_daily(closes), 63)
    assert w["diff_pp"] == round(abs(frac - prob) * 100, 1)  # 반올림 전 값의 차이


# ─── 저장 · 화면 요청 때 외부 호출 없음 (막음 1 · 6) ───

@pytest.mark.asyncio
async def test_build_cards_makes_no_external_call_and_deadline_change_applies_at_once(clean, monkeypatch):
    from backend.discovery.data_sources.krx_price import loader

    await _short_card(long_closes=_wave(400))

    def boom(*a, **k):
        raise AssertionError("화면 요청 때 외부 호출 금지")

    monkeypatch.setattr(loader, "_fetch_ohlcv_sync", boom)
    monkeypatch.setattr(hs, "_default_long_fetch", boom)
    monkeypatch.setitem(__import__("sys").modules, "yfinance", None)  # import 하면 실패
    before = (await _cards())[("US", US)]["goal"]["days_left"]
    async with __import__("backend.services.db", fromlist=["get_session"]).get_session() as s:
        await hs.save_horizon(s, "US", US, "short", deadline=TODAY + timedelta(days=7), today=TODAY)
    after = (await _cards())[("US", US)]["goal"]
    assert before == 260 and after["days_left"] == 5 and after["deadline_source"] == "user"  # 같은 요청 흐름에서 바로 반영


@pytest.mark.asyncio
async def test_fill_long_closes_stores_replaces_and_skips_failed_ticker(clean):
    await _add(_hold(US, "US", TODAY, cur="USD"), _hold("ZZZB", "US", TODAY, cur="USD"))
    days = _days(5)

    async def fetch(market, t):
        if t == "ZZZB":
            raise ConnectionError("blocked")
        return [(d, 10.0 + i) for i, d in enumerate(days)]

    r = await hs.fill_long_closes("US", NOW, fetch)
    assert r["rows"] == 5 and r["failures"] == 1
    from backend.services.db import get_session

    async def stored():
        async with get_session() as s:
            return (await s.execute(select(SwingLongClose).order_by(SwingLongClose.trade_date))).scalars().all()

    rows = await stored()
    assert len(rows) == 5 and {x.ticker for x in rows} == {US} and rows[0].source == "yfinance close"
    await hs.fill_long_closes("US", NOW, fetch)  # 두 번째 받기도 행 수가 늘지 않는다
    assert len(await stored()) == 5

    async def fail(market, t):
        raise ConnectionError("blocked")

    with pytest.raises(RuntimeError):  # 모두 실패 → 경고 대상 · 기존 행은 그대로
        await hs.fill_long_closes("US", NOW, fail)
    assert len(await stored()) == 5


@pytest.mark.asyncio
async def test_fill_long_closes_timeout_per_ticker_is_that_ticker_only(clean, monkeypatch):
    import asyncio

    await _add(_hold(US, "US", TODAY, cur="USD"), _hold("ZZZB", "US", TODAY, cur="USD"))
    monkeypatch.setattr(hs, "LONG_FETCH_TIMEOUT", 0.05)
    assert hs.LONG_FETCH_TIMEOUT == 0.05
    days = _days(3)

    async def fetch(market, t):
        if t == US:
            await asyncio.sleep(5)  # 초과
        return [(d, 5.0) for d in days]

    r = await hs.fill_long_closes("US", NOW, fetch)
    assert r["failures"] == 1 and r["rows"] == 3


def test_long_fetch_timeout_constant_is_60_seconds():
    assert hs.LONG_FETCH_TIMEOUT == 60


@pytest.mark.asyncio
async def test_default_long_fetch_sources_kr_pykrx_from_2000_and_us_yfinance_unadjusted(clean, monkeypatch):
    """막음 4: 국내 = loader.fetch_daily_candles 재사용 · 2000-01-01~ / 미국 = yfinance auto_adjust=False 10년 Close."""
    import sys
    import types

    from backend.discovery.data_sources.krx_price import loader

    seen = {}

    def fake_sync(start, end, ticker):
        seen["kr"] = (start, ticker)
        return _frame([(TODAY, 101.0)])

    monkeypatch.setattr(loader, "_fetch_ohlcv_sync", fake_sync)
    assert await hs._default_long_fetch("KR", KR) == [(TODAY, 101.0)]
    assert seen["kr"] == ("20000101", KR)

    def fake_download(sym, **kw):
        seen["us"] = (sym, kw)
        return pd.DataFrame({"Close": [10.0, 11.0]}, index=pd.to_datetime(["2026-11-05", "2026-11-06"]))

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=fake_download))
    out = await hs._default_long_fetch("US", "ZZZ.B")
    assert out == [(date(2026, 11, 5), 10.0), (date(2026, 11, 6), 11.0)]
    assert seen["us"][0] == "ZZZ-B" and seen["us"][1]["auto_adjust"] is False and seen["us"][1]["period"] == "10y"


@pytest.mark.asyncio
async def test_followup_long_step_failure_keeps_earlier_steps(clean, monkeypatch):
    from backend.scheduler import cron

    done, alerts = [], []

    async def official(*a, **k):
        done.append("official")

    async def refs(*a, **k):
        done.append("refs")

    async def long_boom(*a, **k):
        raise RuntimeError("긴 일봉 막힘")

    async def alert(name, *a, **k):
        alerts.append(name)

    monkeypatch.setattr(hs, "fill_official_closes", official)
    monkeypatch.setattr(hs, "refresh_references", refs)
    monkeypatch.setattr(hs, "fill_long_closes", long_boom)
    monkeypatch.setattr(cron, "_alert_job_failure", alert)
    await cron.run_swing_followup("KR", 15, 50)
    assert done == ["official", "refs"] and alerts == ["긴 일봉 받기 (국내)"]


# ─── 보유 성격 미지정 · 기한 · 메모 (막음 2) ───

@pytest.mark.asyncio
async def test_unset_keeps_row_deadline_memo_and_card_holds_like_unspecified(clean):
    c = await _short_card(long_closes=_wave(400))
    async with __import__("backend.services.db", fromlist=["get_session"]).get_session() as s:
        await hs.save_horizon(s, "US", US, "short", deadline=date(2027, 3, 5), memo="내 메모", today=TODAY)
    async with __import__("backend.services.db", fromlist=["get_session"]).get_session() as s:
        out = await hs.save_horizon(s, "US", US, "unset", today=TODAY)
    assert out == {"horizon": None, "deadline": date(2027, 3, 5), "memo": "내 메모"}
    card = (await _cards())[("US", US)]
    assert card["horizon"] is None and card["status"] == "hold" and card["goal"] is None  # 미지정과 같게 보류
    assert card["deadline"] == date(2027, 3, 5) and card["memo"] == "내 메모"
    async with __import__("backend.services.db", fromlist=["get_session"]).get_session() as s:
        rows = (await s.execute(select(HoldingHorizon))).scalars().all()
    assert [(r.horizon, r.deadline, r.memo) for r in rows] == [("unset", date(2027, 3, 5), "내 메모")]
    async with __import__("backend.services.db", fromlist=["get_session"]).get_session() as s:
        await hs.save_horizon(s, "US", US, "long", today=TODAY)  # 다시 정하면 기한·메모가 살아 있다
    again = (await _cards())[("US", US)]
    assert again["horizon"] == "long" and again["memo"] == "내 메모" and c["status"] == "ok"


@pytest.mark.asyncio
async def test_patch_deadline_and_memo_semantics_and_422(http):
    h = {"X-API-Token": TOKEN}
    await _add(_hold(US, "US", TODAY, cur="USD"))
    url = f"/api/v1/account/swing/US/{US}"
    ok = await http.patch(url, json={"horizon": "short", "deadline": "2027-02-01", "memo": "  첫 메모\n둘째 줄  "}, headers=h)
    assert ok.status_code == 200 and ok.json() == {"market": "US", "ticker": US, "horizon": "short",
                                                    "deadline": "2027-02-01", "memo": "첫 메모\n둘째 줄"}
    keep = await http.patch(url, json={"horizon": "long"}, headers=h)  # 보내지 않은 칸은 그대로
    assert keep.json()["deadline"] == "2027-02-01" and keep.json()["memo"] == "첫 메모\n둘째 줄"
    reset = await http.patch(url, json={"horizon": "long", "deadline": None}, headers=h)  # null = 기본값으로
    assert reset.json()["deadline"] is None and reset.json()["memo"] == "첫 메모\n둘째 줄"
    wipe = await http.patch(url, json={"horizon": "long", "memo": ""}, headers=h)  # "" = 지움
    assert wipe.json()["memo"] is None
    # 422: 형식 · 길이 · 제어 문자 · 기준일보다 앞선 기한
    for body in ({"horizon": "long", "deadline": "내일"}, {"horizon": "long", "deadline": "2027-13-40"},
                 {"horizon": "long", "memo": "가" * 201}, {"horizon": "long", "memo": "a\x00b"},
                 {"horizon": "long", "memo": "a\x1bb"}, {"horizon": "long", "memo": "a\tb"},
                 {"horizon": "long", "memo": 123}, {"horizon": "long", "deadline": "2026-11-05"}):
        r = await http.patch(url, json=body, headers=h)
        assert r.status_code == 422, body
    assert (await http.patch(url, json={"horizon": "long", "memo": "가" * 200}, headers=h)).status_code == 200  # 경계 200자
    assert (await http.patch(url, json={"horizon": "long", "deadline": "2026-11-06"}, headers=h)).status_code == 200  # 기준일 당일은 통과
    # 422 뒤에도 저장값은 그대로
    async with __import__("backend.services.db", fromlist=["get_session"]).get_session() as s:
        row = (await s.execute(select(HoldingHorizon))).scalars().one()
    assert row.deadline == date(2026, 11, 6) and row.memo == "가" * 200


@pytest.mark.asyncio
async def test_patch_unset_via_http_keeps_row_and_returns_null(http):
    h = {"X-API-Token": TOKEN}
    url = f"/api/v1/account/swing/KR/{KR}"
    await http.patch(url, json={"horizon": "short", "memo": "남길 글"}, headers=h)
    r = await http.patch(url, json={"horizon": "unset"}, headers=h)
    assert r.json()["horizon"] is None and r.json()["memo"] == "남길 글"
    cards = await http.get("/api/v1/account/swing", headers=h)
    assert cards.status_code == 200


# ─── 금지 낱말: 메모는 사용자 글이라 뺀다 (계획 6절 시험) ───

@pytest.mark.asyncio
async def test_memo_with_forbidden_words_passes_but_other_fields_still_checked(clean):
    import json

    await _short_card(long_closes=_wave(400))
    async with __import__("backend.services.db", fromlist=["get_session"]).get_session() as s:
        await hs.save_horizon(s, "US", US, "short", memo="sell 손절 물타기 사십시오", today=TODAY)
    card = (await _cards())[("US", US)]
    assert card["memo"] == "sell 손절 물타기 사십시오"  # 통과
    assert FORBIDDEN.search(json.dumps(card, ensure_ascii=False, default=str)) is not None  # 메모를 넣으면 걸림
    without = {k: v for k, v in card.items() if k != "memo"}
    assert FORBIDDEN.search(json.dumps(without, ensure_ascii=False, default=str)) is None  # 다른 칸은 깨끗
    tainted = {**without, "goal": {**card["goal"], "limits": ["지금 손절 하십시오"]}}
    assert FORBIDDEN.search(json.dumps(tainted, ensure_ascii=False, default=str)) is not None  # 다른 칸에 있으면 여전히 걸림


@pytest.mark.asyncio
async def test_goal_and_cards_text_free_of_forbidden_words_and_no_command_words(clean):
    import json

    await _short_card(long_closes=_wave(400))
    await _short_card(long_closes=_wave(400), horizon="long", sym="ZZZB")
    for c in (await _cards()).values():
        dump = json.dumps({k: v for k, v in c.items() if k != "memo"}, ensure_ascii=False, default=str)
        assert FORBIDDEN.search(dump) is None
        assert not re.search(r"팔라|사라|매도 쪽|장기로 하라|강철", dump)


@pytest.mark.asyncio
async def test_memo_does_not_change_any_other_value(clean):
    await _short_card(long_closes=_wave(400))
    base = (await _cards())[("US", US)]
    async with __import__("backend.services.db", fromlist=["get_session"]).get_session() as s:
        await hs.save_horizon(s, "US", US, "short", memo="아무 글이나 길게 적은 메모입니다", today=TODAY)
    withm = (await _cards())[("US", US)]
    assert withm["memo"] and {k: v for k, v in withm.items() if k != "memo"} == {k: v for k, v in base.items() if k != "memo"}


# ─── 이행 · 열 추가 (막음 3) ───

def _alembic(db_path, *args):
    import os
    import subprocess
    import sys

    backend = Path(hs.__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path}"}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=backend, env=env, capture_output=True, text=True, timeout=120)


def test_alembic_migration_noop_without_table_adds_columns_and_is_idempotent(tmp_path):
    import sqlite3

    backend = Path(hs.__file__).resolve().parents[1]
    src = (backend / "alembic" / "versions" / "d4a9c7e15b82_holding_horizon_deadline_memo.py").read_text(encoding="utf-8")
    assert 'down_revision: Union[str, Sequence[str], None] = "b7e2a9c41d05"' in src and "has_table" in src

    empty = tmp_path / "empty.db"  # 표 없음 → 아무것도 안 함 (create_all 이 만든다)
    assert _alembic(empty, "stamp", "b7e2a9c41d05").returncode == 0
    r = _alembic(empty, "upgrade", "head")
    assert r.returncode == 0, r.stderr[-600:]
    assert "d4a9c7e15b82" in _alembic(empty, "current").stdout
    assert sqlite3.connect(empty).execute("select count(*) from sqlite_master where name='holding_horizon'").fetchone()[0] == 0

    old = tmp_path / "old.db"  # 옛 모양 표 → 두 칸 추가 · 기존 행 보존
    con = sqlite3.connect(old)
    con.execute("create table holding_horizon(market varchar(2), ticker varchar(16), horizon varchar(8), updated_at datetime, primary key(market, ticker))")
    con.execute("insert into holding_horizon values('KR','000000','long','2026-11-01')")
    con.commit()
    con.close()
    assert _alembic(old, "stamp", "b7e2a9c41d05").returncode == 0
    r = _alembic(old, "upgrade", "head")
    assert r.returncode == 0, r.stderr[-600:]
    con = sqlite3.connect(old)
    cols = {row[1] for row in con.execute("pragma table_info(holding_horizon)")}
    assert {"deadline", "memo"} <= cols and con.execute("select horizon from holding_horizon").fetchall() == [("long",)]
    con.close()

    full = tmp_path / "full.db"  # create_all 이 먼저 칸을 만든 경우 → 건너뜀
    con = sqlite3.connect(full)
    con.execute("create table holding_horizon(market varchar(2), ticker varchar(16), horizon varchar(8), updated_at datetime, deadline date, memo varchar(200), primary key(market, ticker))")
    con.commit()
    con.close()
    assert _alembic(full, "stamp", "b7e2a9c41d05").returncode == 0
    assert _alembic(full, "upgrade", "head").returncode == 0


@pytest.mark.asyncio
async def test_ensure_columns_adds_deadline_memo_to_old_sqlite_table(clean):
    from sqlalchemy import text

    from backend.services import db

    assert ("holding_horizon", "deadline", "DATE") in db._ADDED_COLUMNS
    assert ("holding_horizon", "memo", "VARCHAR(200)") in db._ADDED_COLUMNS
    async with db.engine.begin() as conn:
        await conn.execute(text("ALTER TABLE holding_horizon DROP COLUMN memo"))
        await conn.execute(text("ALTER TABLE holding_horizon DROP COLUMN deadline"))
    await db.ensure_columns()
    async with db.engine.begin() as conn:
        cols = {r[1] for r in (await conn.execute(text("PRAGMA table_info(holding_horizon)"))).all()}
    assert {"deadline", "memo"} <= cols


def test_swing_long_close_table_shape():
    t = SwingLongClose.__table__
    assert [c.name for c in t.primary_key.columns] == ["market", "ticker", "trade_date"]
    assert {"close", "source", "fetched_at"} <= set(t.columns.keys())


# ═══════════════════════════════════════════════════════════════
# 4단계 · 40주 평균선 (계획 7절 · 검토 1108-02-16 빠진 시험 ①~⑧) — 종목 기호·가격은 모두 가짜 값이다.
# ═══════════════════════════════════════════════════════════════

MON0 = date(2016, 1, 4)  # 월요일


def _week_days(n_weeks, start=MON0):
    """월~금 5일씩 n_weeks 주."""
    return [start + timedelta(days=7 * w + k) for w in range(n_weeks) for k in range(5)]


def _flat_weeks(values, start=MON0):
    """주마다 값이 같은 일봉 (월~금)."""
    d = _week_days(len(values), start)
    return d, [float(values[i // 5]) for i in range(len(d))]


def _ended(dates, today):
    return hs.ended_weeks(dates, [1.0] * len(dates), today)


def test_ended_week_rules_friday_monday_holiday_and_intraday():
    # ① 자료가 금요일에 끝나면 그 주가 끝난 주
    d = _week_days(3)
    assert _ended(d, d[-1])[-1]["w"] == date(2016, 1, 22)
    # 월요일까지만 있고 아직 그 주면 앞 주가 마지막 끝난 주
    d2 = d + [date(2016, 1, 25)]
    assert _ended(d2, date(2016, 1, 25))[-1]["w"] == date(2016, 1, 22)
    # 금요일 휴장: 목요일까지 자료 · 현지 토요일 → 그 주는 끝난 주
    d3 = d[:-1]
    assert _ended(d3, date(2016, 1, 23))[-1]["w"] == date(2016, 1, 22)
    # 현지 금요일 장중(자료는 목요일까지): 아직 끝나지 않음
    assert _ended(d3, date(2016, 1, 22))[-1]["w"] == date(2016, 1, 15)
    # 토요일 날짜는 다음 금요일 묶음 (W-FRI)
    assert hs.week_friday(date(2016, 1, 23)) == date(2016, 1, 29) and hs.week_friday(date(2016, 1, 22)) == date(2016, 1, 22)


@pytest.mark.asyncio
async def test_us_judged_by_new_york_time_and_kr_by_kst(clean):
    """② 같은 순간(UTC 11/07 03:00): 뉴욕은 아직 금요일 밤 · 서울은 이미 토요일."""
    thu = date(2026, 11, 5)
    for market, sym in (("KR", KR), ("US", US)):
        await _seed_card(market, sym, [100.0 + i * 0.1 for i in range(130)])
        await _seed_long(market, sym, [100.0 + i * 0.1 for i in range(300)], end=thu)
    from backend.services.db import get_session

    async with get_session() as s:
        cards = {c["market"]: c for c in await hs.build_cards(s, TODAY, now=datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc))}
    assert cards["KR"]["chart"]["week40"]["as_of_week"] == date(2026, 11, 6)
    assert cards["US"]["chart"]["week40"]["as_of_week"] == date(2026, 10, 30)
    assert cards["US"]["chart"]["week40"]["data_last_date"] == thu


@pytest.mark.asyncio
async def test_data_stopped_on_wednesday_reports_data_last_date(clean):
    """③ 수요일에 자료가 멈추고 현지 토요일 → 그 주는 끝난 주 · data_last_date 는 수요일 (화면이 「자료 11/4 까지」)."""
    wed = date(2026, 11, 4)
    await _seed_card("US", US, [100.0] * 130)
    await _seed_long("US", US, [100.0 + i * 0.1 for i in range(300)], end=wed)
    from backend.services.db import get_session

    async with get_session() as s:
        c = {x["symbol"]: x for x in await hs.build_cards(s, TODAY, now=datetime(2026, 11, 7, 17, 0, tzinfo=timezone.utc))}[US]
    assert c["chart"]["week40"]["as_of_week"] == date(2026, 11, 6) and c["chart"]["week40"]["data_last_date"] == wed


def test_streak_counts_over_300_weeks_and_series_is_cut_to_5_years():
    # ④ 끝난 주 전체에서 센다 — 표시 5년(260주)으로 자르지 않음
    d, c = _flat_weeks([100 + i for i in range(350)])
    w = hs.build_week40("US", d, c, d[-1])
    assert w["streak_weeks"] == 350 - 39 and w["side"] == "above" and len(w["series"]) == 260
    assert w["series"][-1]["w"] == w["as_of_week"] and w["series"][-1]["m"] is not None


def test_week_count_boundaries_slope_check_and_period():
    # ⑤ 끝난 주 39 → 선 없음 · 검증 없음
    d, c = _flat_weeks([100 + i for i in range(39)])
    w = hs.build_week40("US", d, c, d[-1])
    assert w["side"] is None and w["distance_pct"] is None and w["slope4w_pct"] is None and w["check"] is None
    assert w["note"] == "40주 자료 부족" and all(p["m"] is None for p in w["series"])
    # 40~43 → 선은 있고 기울기만 없음
    for n in (40, 43):
        d, c = _flat_weeks([100 + i for i in range(n)])
        w = hs.build_week40("US", d, c, d[-1])
        assert w["side"] == "above" and w["slope4w_pct"] is None and w["distance_pct"] is not None
    d, c = _flat_weeks([100 + i for i in range(44)])
    assert hs.build_week40("US", d, c, d[-1])["slope4w_pct"] is not None
    # 3년 미만이면 검증 없음 · 3년 이상 10년 미만이면 실제 기간 · 10년 넘으면 최근 10년
    d, c = _flat_weeks([100 + i * 0.1 for i in range(150)])  # 약 2.9년
    assert hs.build_week40("US", d, c, d[-1])["check"] is None
    d, c = _flat_weeks([100 + i * 0.1 for i in range(200)])  # 약 3.8년
    ck = hs.build_week40("US", d, c, d[-1])["check"]
    assert ck["from"] == d[0] and ck["to"] == d[-1] and ck["years"] == round((d[-1] - d[0]).days / 365.25, 1)
    d, c = _flat_weeks([100 + i * 0.1 for i in range(700)])  # 약 13.4년
    ck = hs.build_week40("US", d, c, d[-1])["check"]
    assert d[-1].year - ck["from"].year in (9, 10) and ck["years"] == 10.0 and ck["from"] > d[0]


def test_check_matches_hand_calculation_on_60_week_fake_series():
    """⑥ 주 0~39 = 100 · 40~49 = 110 · 50~59 = 90 (주마다 값이 같은 일봉).
    40주선: 주 40 = (39*100+110)/40 = 100.25 → 위 · 주 50 = (29*100+10*110+90)/40 = 102.25 → 아래 (주 39 는 100 = 100 이라 위 아님).
    체결 = 다음 거래일 종가: 주 41 월요일 110 에 사고(비용 0.25%) · 주 51 월요일 90 에 팔고(비용 0.25%).
    쉬는 쪽 = 0.9975 * 90/110 * 0.9975 = 0.814096 → 연 -16.5% · 최대 낙폭 18.6% (고점 1.0).
    그대로 = 처음 1번만 비용: 0.9975 * 90/100 = 0.89775 → 연 -9.0% · 낙폭 = 1 - 90/110 = 18.2% (고점 0.9975*1.1).
    기간 = 주 0 월요일 ~ 주 59 금요일 417일 = 1.1417년 · 바뀜 2번(주 40 · 50) 모두 4주 넘게 유지 → 되돌림 0%.
    """
    d, c = _flat_weeks([100] * 40 + [110] * 10 + [90] * 10)
    weeks = hs.ended_weeks(d, c, d[-1])
    means = hs.week_means(weeks)
    assert means[40] == pytest.approx(100.25) and means[50] == pytest.approx(102.25)
    ck = hs.week40_check(d, c, weeks, means, min_years=0.5)
    assert ck["years"] == 1.1 and ck["from"] == d[0] and ck["to"] == d[-1]
    assert ck["rule_cagr"] == -16.5 and ck["hold_cagr"] == -9.0
    assert ck["rule_mdd"] == 18.6 and ck["hold_mdd"] == 18.2
    assert ck["whipsaw_pct"] == 0.0 and ck["cost_pct"] == 0.25
    # 기본 기준(3년)이면 이 짧은 계열은 검증 없음
    assert hs.week40_check(d, c, weeks, means) is None


def test_whipsaw_ratio_counts_flips_back_within_4_weeks_and_skips_unseen_tail():
    # 바뀜 주 10 · 13(3주 뒤 되돌림) · 30 (뒤 30주를 봤고 더 바뀌지 않음)
    assert hs.whipsaw_ratio([10, 13, 30], 60, lambda k: True) == pytest.approx(33.3)  # 10→13 만 되돌림 · 13→30 아님 · 30 아님
    # 10→13 되돌림 · 13→30 아님 · 30→34 되돌림(4주 딱) · 34→56 아님 · 56 은 뒤가 3주뿐이라 뺌 = 2/4
    assert hs.whipsaw_ratio([10, 13, 30, 34, 56], 60, lambda k: True) == 50.0
    assert hs.whipsaw_ratio([56], 60, lambda k: True) is None
    assert hs.whipsaw_ratio([10, 13], 60, lambda k: k > 11) == 0.0  # 구간 밖 바뀜은 안 센다


@pytest.mark.asyncio
async def test_week40_source_says_dividends_excluded_for_kr_and_us(clean):
    # ⑦
    for market, sym in (("KR", KR), ("US", US)):
        await _seed_card(market, sym, [100.0] * 130)
        await _seed_long(market, sym, [100.0 + i * 0.05 for i in range(900)])
    cs = await _cards()
    for key in (("KR", KR), ("US", US)):
        ck = cs[key]["chart"]["week40"]["check"]
        assert ck is not None and "배당 미반영" in ck["source"]


@pytest.mark.asyncio
async def test_week40_makes_no_external_call_and_hold_cards_have_chart(clean, monkeypatch):
    # ⑧
    from backend.discovery.data_sources.krx_price import loader

    await _seed_card("US", US, [100.0] * 130)
    await _seed_long("US", US, [100.0 + i * 0.05 for i in range(900)])
    await _seed_card("KR", KR, [100.0] * 130, horizon=None)  # 보유 성격 미지정 = 보류
    await _seed_long("KR", KR, [100.0 + i * 0.05 for i in range(900)])

    def boom(*a, **k):
        raise AssertionError("화면 요청 때 외부 호출 금지")

    monkeypatch.setattr(loader, "_fetch_ohlcv_sync", boom)
    monkeypatch.setattr(hs, "_default_long_fetch", boom)
    monkeypatch.setitem(__import__("sys").modules, "yfinance", None)
    cs = await _cards()
    # 1110-02 · 뒤집음: 보유 성격 미지정(카드 보류)이어도 그림(chart)은 채워진다 (㉣②)
    assert cs[("US", US)]["chart"]["week40"]["series"] and cs[("KR", KR)]["status"] == "hold"
    assert cs[("KR", KR)]["chart"]["week40"]["series"] and cs[("KR", KR)]["chart"]["daily"]


@pytest.mark.asyncio
async def test_week40_null_without_long_series_and_output_has_no_forbidden_words(clean):
    import json

    await _seed_card("KR", KR, [100.0] * 130)  # 긴 일봉 없음
    await _seed_card("US", US, [100.0] * 130)
    await _seed_long("US", US, [100.0 + (i % 7) * 0.5 + i * 0.02 for i in range(900)])
    cs = await _cards()
    assert cs[("KR", KR)]["chart"] is None
    assert FORBIDDEN.search(json.dumps(cs[("US", US)]["chart"]["week40"], ensure_ascii=False, default=str)) is None
