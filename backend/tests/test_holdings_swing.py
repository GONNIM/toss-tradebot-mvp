"""1108-02 · 보유 종목 사실 (스윙 2단계) — 계획 5절 「만들 것」 시험 + 검토 1108-02-07 권고 (ㄹ).

티커·수량·평단은 모두 가짜 값이다 (실제 보유 종목 아님). 시각은 시험 안에서 고정한다 (교훈 #5 — 요일·시각에 기대지 않음).
"""
from __future__ import annotations

import ast
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
        for m in (HoldingSnapshot, HoldingHorizon, KrOfficialClose, SwingReference):
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
    monkeypatch.setattr(hs, "refresh_references", refs)
    monkeypatch.setattr(cron, "_alert_job_failure", no_alert)
    await cron.run_swing_followup("KR", 15, 50)
    assert order == ["official", "alert", "refs"]  # 앞 단계가 실패해도 다음 단계는 돈다
    order.clear()
    await cron.run_swing_followup("US", 7, 10)
    assert order == ["refs"]  # 미국은 공식 종가 단계 없음


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
    assert gone.json()["horizon"] is None
    async with __import__("backend.services.db", fromlist=["get_session"]).get_session() as s:
        assert (await s.execute(select(HoldingHorizon))).scalars().all() == []


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
    assert c["status"] == "ok" and [m["note"] for m in c["ma"]] == [None, None, "자료 부족"]


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
    assert all(m["distance_pct"] == 0.0 for m in c["ma"])  # 평균 거리는 공식 종가로 계산
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

FORBIDDEN = re.compile(r"buy|sell|stop|trailing|추가 매수|손절|이익 보호|추적|사십시오|파십시오|장기로 하십시오|물타기", re.I)


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
    for rel in ("components/account/HoldingSwing.tsx", "lib/holdings-swing.ts"):
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
