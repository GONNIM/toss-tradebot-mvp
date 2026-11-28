"""1128-01 · 국내 종목 가격 · 증권사 의견 칸 (관리자 전용 · 네이버) + 거래량 막대 자료.

바깥 호출(네이버 일봉 · 종합 · 현재가 · 야후)은 모두 가짜 함수로 바꾼다. 응답 모양은 2026-11-28 에 확인한 응답 모양(칸 이름 · 날짜 · 문자열 모양)을 본떠 숫자 · 종목명을 지어낸 값으로 채워
backend/tests/fixtures/naver_kr/ 에 그대로 옮긴 것이다 (교훈 #26: 날짜 모양 — 일봉 'YYYYMMDD' · 의견 작성일 'YYYY-MM-DD').
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from backend.discovery.data_sources.naver_quote.client import Quote
from backend.services import biotech_quotes as bq
from backend.services import holdings_swing as hs
from backend.services import kr_quotes as kq
from backend.services.models import (BiotechLongClose, DartCorpCodeMap, KrQuoteCallLog, KrQuoteDaily, KrxStockMeta)

FIX = Path(__file__).parent / "fixtures" / "naver_kr"
TOKEN = "kr_quotes_test_token_32chars_000"
H = {"X-API-Token": TOKEN}
NOW = datetime(2026, 11, 28, 1, 0, tzinfo=timezone.utc)   # 11/28(토) 10:00 KST


def _fx(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _naver_daily(n: int = 1400, end: date = date(2026, 11, 27)) -> list[dict]:
    """실제 응답과 같은 줄 모양 (localDate 'YYYYMMDD' · 가격은 float · 거래량은 int)."""
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.sort()
    return [{"localDate": d.strftime("%Y%m%d"), "closePrice": 50000.0 + (i % 40) * 100, "openPrice": 50000.0,
             "highPrice": 51000.0, "lowPrice": 49000.0, "accumulatedTradingVolume": 1_000_000 + i,
             "foreignRetentionRate": 55.7} for i, d in enumerate(days)]


class Net:
    """바깥 호출 세는 가짜 네이버."""

    def __init__(self):
        self.daily = self.integ = self.live = self.http = 0
        self.daily_result: object = _naver_daily()
        self.integ_result: object = _fx("integration_900001.json")
        self.delay = 0.0

    async def daily_fetch(self, code, start, end):
        self.daily += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.daily_result, Exception):
            raise self.daily_result
        return self.daily_result

    async def integ_fetch(self, code):
        self.integ += 1
        if isinstance(self.integ_result, Exception):
            raise self.integ_result
        return self.integ_result

    async def live_fetch(self, code):
        self.live += 1
        return Quote(ticker=code, current_price=12800.0, prev_close=12300.0, change_rate=4.07,
                     market_status="CLOSE", fetched_at=0.0)

    @property
    def total(self):
        return self.daily + self.integ + self.live + self.http


@pytest.fixture
async def net(monkeypatch):
    from backend.services.db import get_session, init_db

    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    await init_db()
    async with get_session() as s:
        for tbl in (KrQuoteDaily, KrQuoteCallLog, KrxStockMeta, DartCorpCodeMap):
            await s.execute(delete(tbl))
        s.add(KrxStockMeta(ticker="900001", name="가상전자", market="KOSPI"))
        s.add(KrxStockMeta(ticker="900002", name="시험바이오", market="KOSDAQ"))
        s.add(DartCorpCodeMap(corp_code="00000001", corp_name="가상홀딩스", stock_code="900003"))
        s.add(DartCorpCodeMap(corp_code="00000002", corp_name="비상장회사", stock_code=None))
        s.add(DartCorpCodeMap(corp_code="00000003", corp_name="빈칸회사", stock_code=""))
    kq._CACHE.clear()
    kq._LOCKS.clear()
    n = Net()
    monkeypatch.setattr(kq, "default_daily_fetch", n.daily_fetch)
    monkeypatch.setattr(kq, "default_integ_fetch", n.integ_fetch)
    monkeypatch.setattr(kq, "default_live_fetch", n.live_fetch)

    import httpx

    real_get = httpx.AsyncClient.get

    async def guard(self, url, *a, **kw):
        if "naver" in str(url):
            n.http += 1
            raise AssertionError(f"네이버 직접 호출 {url}")
        return await real_get(self, url, *a, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "get", guard)
    return n


@pytest.fixture
async def client(net):
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ── 값 읽기 (실제 응답 · 시험 자료는 fixtures/naver_kr) ───────────────────────

def test_parse_daily_real_fixture_split_days_and_zero_volume():
    items = _fx("daily_900001_2018_split.json")
    rows, received, dropped = kq.parse_daily(items)
    assert (received, len(rows), dropped) == (8, 8, 0)
    assert rows[0] == {"d": date(2018, 4, 25), "o": rows[0]["o"], "h": rows[0]["h"], "l": rows[0]["l"],
                       "c": 12300.0, "v": 41230.0}
    halt = [r for r in rows if r["d"] == date(2018, 4, 30)][0]   # 거래정지 구간 · 종가는 이어지고 거래량 0
    assert halt["c"] == 13000.0 and halt["v"] == 0.0


def test_parse_daily_recent_fixture_has_all_fields():
    rows, received, dropped = kq.parse_daily(_fx("daily_900002_recent.json"))
    assert received == len(rows) > 0 and dropped == 0
    assert all(r["o"] and r["h"] and r["l"] and r["c"] and r["v"] is not None for r in rows)
    assert rows[0]["d"] == date(2026, 11, 20)


def test_parse_date_dashed_and_undashed():
    assert kq.parse_date("20261127") == date(2026, 11, 27)        # 일봉 localDate
    assert kq.parse_date("2026-11-26") == date(2026, 11, 26)      # 의견 createDate
    for bad in (None, "", "2026/11/26", "20261301", "2026-13-01", "abc", 20261127.5):
        assert kq.parse_date(bad) is None


def test_parse_daily_counts_dropped_rows():
    items = [
        {"localDate": "20261126", "closePrice": 100.0, "openPrice": 99.0, "highPrice": 101.0, "lowPrice": 98.0,
         "accumulatedTradingVolume": 10},
        {"localDate": "2026-11-27", "closePrice": 101.0, "accumulatedTradingVolume": "-"},   # 대시 날짜 · 거래량 못 읽음 → 줄은 살림
        {"localDate": None, "closePrice": 100.0},          # 날짜 없음 → 버림
        {"localDate": "20261125", "closePrice": 0},        # 종가 0 → 버림
        {"localDate": "20261124", "closePrice": "-"},      # 종가 못 읽음 → 버림
        "not-a-dict",
        {"localDate": "20261126", "closePrice": 102.0},    # 같은 날 두 줄 → 뒤 줄이 이김
    ]
    rows, received, dropped = kq.parse_daily(items)
    assert received == 7 and dropped == 4 and len(rows) == 2
    assert rows[0]["c"] == 102.0 and rows[1]["d"] == date(2026, 11, 27) and rows[1]["v"] is None
    assert kq.parse_daily(None) == ([], 0, 0)


def test_parse_won_and_numbers():
    assert kq.parse_won("2,468조 1,357억") == pytest.approx(2.4681357e15)
    assert kq.parse_won("321억") == pytest.approx(3.21e10)
    assert kq.parse_won("44.4억") == pytest.approx(4.44e9)
    assert kq.parse_won("-") is None and kq.parse_won("N/A") is None and kq.parse_won(None) is None
    assert kq.parse_number("33.33%") == 33.33 and kq.parse_number("-123원") == -123.0
    assert kq.parse_number("N/A") is None and kq.parse_number("-") is None and kq.parse_number(True) is None


def test_parse_integration_with_consensus():
    r = kq.parse_integration(_fx("integration_900001.json"))
    b = r["basics"]
    assert b["market_cap"] == pytest.approx(2.4681357e15) and b["foreign_rate"] == 33.33
    assert (b["low_52w"], b["high_52w"]) == (8800.0, 20000.0)
    assert r["opinion"] == {"mean_rating": 3.75, "mean_target": 15432.0, "created": "2026-11-26"}


def test_parse_integration_without_consensus_prefers_adjusted_52w():
    r = kq.parse_integration(_fx("integration_900002_noconsensus.json"))
    assert r["opinion"] is None
    assert (r["basics"]["low_52w"], r["basics"]["high_52w"]) == (777.0, 4321.0)   # Adjusted 칸 (일봉 그림과 같음)
    assert r["basics"]["market_cap"] == pytest.approx(3.21e10)


def test_parse_integration_dash_fields_counted_not_crash():
    r = kq.parse_integration(_fx("integration_900003_dashes.json"))
    assert r["opinion"]["mean_target"] == 3000.0 and r["basics"]["market_cap"] == pytest.approx(2.468e11)
    assert kq.parse_integration(None) == {"basics": {}, "opinion": None, "dropped": 0}
    assert kq.parse_integration({"consensusInfo": {"createDate": "2026-11-26"}})["opinion"] is None


# ── 허용 목록 · 인증 · 바깥 호출 0 ────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["999999", "AAPL", "12345", "1234567", "00593O", "../etc", "비상장"])
async def test_unknown_code_is_404_with_zero_external_calls(client, net, code):
    r = await client.get(f"/api/v1/stock/{code}/quote", headers=H)
    assert r.status_code == 404
    assert net.total == 0
    assert await kq.calls_today() == 0


@pytest.mark.asyncio
async def test_dart_row_without_stock_code_is_not_allowed(client, net):
    assert await kq.lookup_allowed("000000") is None
    assert await kq.lookup_allowed("900003") == {"name": "가상홀딩스", "market": None}
    r = await client.get("/api/v1/stock/900003/quote", headers=H)
    assert r.status_code == 200 and net.daily == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{}, {"X-API-Token": "wrong-token-value-xxxxxxxxxxxxxxxx"}])
async def test_non_admin_is_401_with_zero_naver_calls(client, net, headers):
    for code in ("900001", "999999", "AAPL"):
        r = await client.get(f"/api/v1/stock/{code}/quote", headers=headers)
        assert r.status_code == 401
    assert net.total == 0
    assert await kq.calls_today() == 0


@pytest.mark.asyncio
async def test_overview_api_makes_no_external_calls(client, net):
    for code in ("900001", "900002", "999999"):
        assert (await client.get(f"/api/v1/stock/{code}")).status_code == 200
    assert net.total == 0


# ── 응답 모양 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_response_shape_and_volume_bars(client, net):
    r = await client.get("/api/v1/stock/900001/quote", headers=H)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "private, no-store"
    b = r.json()
    assert set(b) == {"ticker", "name", "market_label", "asof", "live", "live_note", "basics", "chart", "opinion",
                      "opinion_status", "opinion_note", "plan_hints", "notes", "use_note"}
    assert b["ticker"] == "900001" and b["name"] == "가상전자" and b["market_label"] == "KOSPI"
    assert b["asof"] == "2026-11-27" and b["notes"] == []
    assert b["live"] == {"price": 12800.0, "change_pct": 4.07, "market_status": "CLOSE", "traded_at": None,
                         "source": "네이버 실시간"}
    # 숫자 칸
    bs = b["basics"]
    assert bs["price_close"] == 50000.0 + (1399 % 40) * 100 and bs["volume"] == 1_000_000 + 1399
    assert bs["avg_volume"] == round(sum(1_000_000 + i for i in range(1380, 1400)) / 20)
    assert bs["market_cap"] == pytest.approx(2.4681357e15) and bs["foreign_rate"] == 33.33
    assert (bs["low_52w"], bs["high_52w"]) == (8800.0, 20000.0) and bs["source"] == "네이버 증권"
    # 그림: 일봉 점마다 v · 주봉 점마다 그 주 합계 v · 출처 문장
    ch = b["chart"]
    assert len(ch["daily"]) == 252 and all(p["v"] is not None for p in ch["daily"])
    assert ch["daily"][-1]["v"] == 1_000_000 + 1399 and ch["daily"][-1]["m200"] is not None
    assert "네이버 일봉 · 수정주가 여부 확인 전" == ch["daily_source"]["source"]
    wk = ch["week40"]
    assert len(wk["series"]) == 260 and wk["series"][-1]["m"] is not None
    assert wk["series"][-1]["v"] == sum(1_000_000 + i for i in range(1395, 1400))   # 마지막 주 월~금 합계
    # 의견
    op = b["opinion"]
    assert b["opinion_status"] == "ok" and b["opinion_note"] is None
    assert op["head"] == "전문가 의견 모음 · 추정 · 보장 아님" and op["source"] == "네이버 증권"
    assert (op["mean_rating"], op["mean_target"], op["created"]) == (3.75, 15432.0, "2026-11-26")
    assert "표시 전용" in op["use_note"] and "title" not in json.dumps(op) and "summary" not in b
    # 계획으로 옮기기 준비값 (표시 전용)
    ph = b["plan_hints"]
    assert ph["last_close"] == bs["price_close"] and ph["week40_line"] == wk["series"][-1]["m"]
    assert (ph["low_52w"], ph["high_52w"], ph["asof"]) == (8800.0, 20000.0, "2026-11-27")
    assert "표시 전용" in ph["note"]
    # 저장도 됨
    async with kq._session() as s:
        n = (await s.execute(select(func.count()).select_from(KrQuoteDaily).where(KrQuoteDaily.ticker == "900001"))).scalar()
    assert n == 1400


@pytest.mark.asyncio
async def test_no_opinion_shows_none_note(client, net):
    net.integ_result = _fx("integration_900002_noconsensus.json")
    b = (await client.get("/api/v1/stock/900002/quote", headers=H)).json()
    assert b["opinion"] is None and b["opinion_status"] == "none" and b["opinion_note"] == "증권사 의견 없음"
    assert b["market_label"] == "KOSDAQ"


# ── 캐시 · 잠금 · 하루 상한 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ten_minute_cache_one_refresh_per_code(client, net):
    for _ in range(3):
        assert (await client.get("/api/v1/stock/900001/quote", headers=H)).status_code == 200
    assert (net.daily, net.integ) == (1, 1)
    assert await kq.calls_today() == 2
    # 다른 종목은 따로 받음
    await client.get("/api/v1/stock/900002/quote", headers=H)
    assert (net.daily, net.integ) == (2, 2)
    # 캐시가 지나면 다시 받음
    kq._CACHE["900001"] = (0.0, kq._CACHE["900001"][1])
    await client.get("/api/v1/stock/900001/quote", headers=H)
    assert (net.daily, net.integ) == (3, 3)


@pytest.mark.asyncio
async def test_concurrent_requests_same_code_fetch_once(client, net):
    net.delay = 0.05
    rs = await asyncio.gather(*[client.get("/api/v1/stock/900001/quote", headers=H) for _ in range(6)])
    assert all(r.status_code == 200 for r in rs)
    assert (net.daily, net.integ) == (1, 1)


@pytest.mark.asyncio
async def test_daily_cap_blocks_external_calls_and_shows_stored(client, net):
    await client.get("/api/v1/stock/900001/quote", headers=H)           # 저장 · 장부 2
    net.daily = net.integ = 0
    async with kq._session() as s:
        row = (await s.execute(select(KrQuoteCallLog))).scalar_one()
        row.calls = 299                                                   # 남은 1번 < 한 번에 쓰는 2번
    kq._CACHE.clear()
    r = await client.get("/api/v1/stock/900001/quote", headers=H)
    b = r.json()
    assert r.status_code == 200 and (net.daily, net.integ) == (0, 0)
    assert any("한도" in n for n in b["notes"])
    assert b["chart"] is not None and b["asof"] == "2026-11-27"          # 저장된 일봉은 그대로
    assert b["opinion_status"] == "failed" and b["opinion_note"] == "의견을 받지 못했습니다"
    assert await kq.calls_today() == 299
    # 상한에 막힌 결과는 캐시하지 않음 → 장부가 비면 바로 받음
    async with kq._session() as s:
        (await s.execute(select(KrQuoteCallLog))).scalar_one().calls = 298
    await client.get("/api/v1/stock/900001/quote", headers=H)
    assert (net.daily, net.integ) == (1, 1) and await kq.calls_today() == 300
    kq._CACHE.clear()
    await client.get("/api/v1/stock/900001/quote", headers=H)
    assert (net.daily, net.integ) == (1, 1)                              # 300 도달 → 더 못 받음


@pytest.mark.asyncio
async def test_reserve_calls_resets_next_kst_day(net):
    d1 = datetime(2026, 11, 28, 14, 59, tzinfo=timezone.utc)   # 11/28 23:59 KST
    d2 = datetime(2026, 11, 28, 15, 1, tzinfo=timezone.utc)    # 11/29 00:01 KST
    assert await kq.reserve_calls(300, d1) is True
    assert await kq.reserve_calls(2, d1) is False
    assert await kq.reserve_calls(2, d2) is True


# ── 칸마다 따로 실패 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_integration_failure_keeps_chart_and_basics(client, net):
    net.integ_result = RuntimeError("boom")
    b = (await client.get("/api/v1/stock/900001/quote", headers=H)).json()
    assert b["chart"] is not None and b["basics"]["price_close"] is not None
    assert b["basics"]["market_cap"] is None and b["opinion"] is None and b["opinion_status"] == "failed"
    assert "종합 정보를 받지 못했습니다" in b["notes"]


@pytest.mark.asyncio
async def test_daily_failure_keeps_opinion_and_old_rows(client, net):
    net.daily_result = RuntimeError("boom")
    b = (await client.get("/api/v1/stock/900001/quote", headers=H)).json()
    assert b["chart"] is None and b["opinion_status"] == "ok" and "일봉을 받지 못했습니다" in b["notes"]
    assert b["basics"]["market_cap"] is not None and b["basics"]["price_close"] is None
    # 실패는 1분만 기억 → 만료 뒤 다시 받아 저장
    net.daily_result = _naver_daily(300)
    kq._CACHE.clear()
    b2 = (await client.get("/api/v1/stock/900001/quote", headers=H)).json()
    assert b2["chart"] is not None and b2["notes"] == []
    # 이후 일봉 받기가 실패해도 저장된 옛 일봉은 남는다
    net.daily_result = None
    kq._CACHE.clear()
    b3 = (await client.get("/api/v1/stock/900001/quote", headers=H)).json()
    assert b3["chart"] is not None and "일봉을 받지 못했습니다" in b3["notes"]


@pytest.mark.asyncio
async def test_received_saved_dropped_counts_are_logged(client, net, caplog):
    bad = _naver_daily(40)
    bad.append({"localDate": None, "closePrice": 1.0})
    bad.append({"localDate": "20261127", "closePrice": 0})
    net.daily_result = bad
    with caplog.at_level(logging.INFO, logger="backend.services.kr_quotes"):
        await client.get("/api/v1/stock/900001/quote", headers=H)
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "일봉 받음 42 · 저장 40 · 버림 2" in msg


@pytest.mark.asyncio
async def test_all_rows_dropped_warns_shape_change(client, net, caplog):
    net.daily_result = [{"date": "20261127", "close": 1.0}] * 5   # 칸 이름이 바뀐 응답
    with caplog.at_level(logging.WARNING, logger="backend.services.kr_quotes"):
        b = (await client.get("/api/v1/stock/900001/quote", headers=H)).json()
    assert "하나도 저장하지 못함" in " ".join(r.getMessage() for r in caplog.records)
    assert b["chart"] is None and "일봉이 비어 있습니다" in b["notes"]


@pytest.mark.asyncio
async def test_no_db_session_open_during_network(client, net, monkeypatch):
    open_sessions = {"n": 0, "during_net": 0}
    real = kq._session

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def watched():
        open_sessions["n"] += 1
        try:
            async with real() as s:
                yield s
        finally:
            open_sessions["n"] -= 1

    monkeypatch.setattr(kq, "_session", watched)
    orig = net.daily_fetch

    async def spy(code, start, end):
        open_sessions["during_net"] += open_sessions["n"]
        return await orig(code, start, end)

    monkeypatch.setattr(kq, "default_daily_fetch", spy)
    await client.get("/api/v1/stock/900001/quote", headers=H)
    assert open_sessions["during_net"] == 0


# ── 종목 개요 (시장 표시 · quote_available) ───────────────────────────────

@pytest.mark.asyncio
async def test_overview_market_label_and_quote_available(client, net):
    a = (await client.get("/api/v1/stock/900001")).json()
    assert (a["market"], a["market_label"], a["quote_available"]) == ("KR", "KOSPI", True)
    k = (await client.get("/api/v1/stock/900002")).json()
    assert (k["market_label"], k["quote_available"]) == ("KOSDAQ", True)
    d = (await client.get("/api/v1/stock/900003")).json()          # DART 상장 행 · 시장 표시는 저장값이 없어 None
    assert (d["market_label"], d["quote_available"]) == (None, True)
    u = (await client.get("/api/v1/stock/123456")).json()          # 저장 목록 밖
    assert (u["market_label"], u["quote_available"]) == (None, False)
    us = (await client.get("/api/v1/stock/ZZNONE")).json()
    assert us["market"] == "US" and us["market_label"] is None
    assert net.total == 0


# ── 그림 자료 (거래량 v) ──────────────────────────────────────────────────

def _series(n=300, end=date(2026, 11, 27)):
    ds, d = [], end
    while len(ds) < n:
        if d.weekday() < 5:
            ds.append(d)
        d -= timedelta(days=1)
    ds.sort()
    return ds, [10.0 + (i % 5) for i in range(n)]


def test_build_chart_without_volumes_is_unchanged():
    ds, cs = _series()
    ch = hs.build_chart("US", (ds, cs, "yahoo"), ds[-1])
    assert "v" not in ch["daily"][-1]
    assert all("v" not in w for w in ch["week40"]["series"])
    assert ch["daily_source"]["source"] == hs.LONG_TEXT_SOURCE["US"]


def test_build_chart_with_volumes_daily_and_weekly_sum():
    ds, cs = _series()
    vs = [100 + i for i in range(len(ds))]
    ch = hs.build_chart("US", (ds, cs, "yahoo"), ds[-1], volumes=vs)
    assert ch["daily"][-1]["v"] == vs[-1] and ch["daily"][-252]["v"] == vs[-252]
    assert ch["week40"]["series"][-1]["v"] == sum(vs[-5:])


def test_weekly_volume_is_none_when_a_day_is_missing_and_old_points_stay_null():
    ds, cs = _series(60)
    vs = [100] * len(ds)
    vs[-3] = None                                   # 마지막 주 수요일 거래량 없음
    vs[0] = None                                    # 옛 점도 None 이면 v null (그림은 그대로)
    ch = hs.build_chart("US", (ds, cs, "yahoo"), ds[-1], volumes=vs)
    assert ch["week40"]["series"][-1]["v"] is None
    assert ch["week40"]["series"][-2]["v"] == 500
    assert ch["daily"][-3]["v"] is None and ch["daily"][0]["v"] is None and ch["daily"][1]["v"] == 100
    ch2 = hs.build_chart("US", (ds, cs, "yahoo"), ds[-1], volumes=[None] * len(ds))
    assert all(p["v"] is None for p in ch2["daily"])


# ── 미국 바이오 거래량 열 ─────────────────────────────────────────────────

TODAY = date(2026, 11, 12)
UNOW = datetime(2026, 11, 11, 23, 45, tzinfo=timezone.utc)


def _closes_vols(n, end=date(2026, 11, 11), with_vol=True):
    ds, d = [], end
    while len(ds) < n:
        if d.weekday() < 5:
            ds.append(d)
        d -= timedelta(days=1)
    ds.sort()
    closes = [(d, 10.0 + i % 7) for i, d in enumerate(ds)]
    vols = {d: 1000.0 + i for i, d in enumerate(ds)} if with_vol else {}
    return closes, vols


def _raw(n=400, with_vol=True):
    closes, vols = _closes_vols(n, with_vol=with_vol)
    return {"info": {"exchange": "NMS", "currentPrice": 12.5}, "dist": {}, "changes": [], "closes": closes,
            "volumes": vols}


async def _no_sec(t, prev, budget):
    return None


async def _no_llm(t, system, user):
    return {"text": "", "provider": "test", "model": "none"}


@pytest.fixture
async def us_clean(monkeypatch):
    from backend.services.db import get_session, init_db

    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    await init_db()
    async with get_session() as s:
        await s.execute(delete(BiotechLongClose))
    bq._LIVE.clear()


def test_volume_column_registered_for_production_tables():
    from backend.services.db import _ADDED_COLUMNS

    assert ("biotech_long_close", "volume", "FLOAT") in _ADDED_COLUMNS


@pytest.mark.asyncio
async def test_us_long_close_stores_volume_and_chart_has_v(us_clean):
    async def fetch(t, period):
        return _raw(400)

    await bq.run_quotes(now=UNOW, fetch=fetch, sec_fetch=_no_sec, summarize=_no_llm, candidates=["ZZQA"], pause=0,
                        budget=bq.SecBudget(None))
    async with bq._session() as s:
        n_vol = (await s.execute(select(func.count()).select_from(BiotechLongClose).where(
            BiotechLongClose.volume.is_not(None)))).scalar()
        n_all = (await s.execute(select(func.count()).select_from(BiotechLongClose))).scalar()
    assert n_all == 400 and n_vol == 400
    v = await bq.quote_view("ZZQA", live_fetch=lambda c: asyncio.sleep(0), now=UNOW)
    assert v["chart"]["daily"][-1]["v"] == 1000 + 399
    assert v["chart"]["week40"]["series"][-1]["v"] == sum(1000 + i for i in range(392, 397))  # 끝난 마지막 주(11/2~11/6) · 11/9~11/11 은 아직 안 끝난 주


@pytest.mark.asyncio
async def test_us_old_rows_without_volume_still_render_with_null_v(us_clean):
    closes, _ = _closes_vols(300)
    async with bq._session() as s:
        s.add_all([BiotechLongClose(ticker="ZZQB", trade_date=d, close=c) for d, c in closes])   # 열 추가 전 옛 행
    v = await bq.quote_view("ZZQB", live_fetch=lambda c: asyncio.sleep(0), now=UNOW)
    assert v["chart"]["daily"] and all(p["v"] is None for p in v["chart"]["daily"])


@pytest.mark.asyncio
async def test_refill_volumes_fills_only_missing_and_is_not_run_by_daily_job(us_clean):
    closes, vols = _closes_vols(300)
    async with bq._session() as s:
        s.add_all([BiotechLongClose(ticker="ZZQC", trade_date=d, close=c, volume=(5.0 if i >= 280 else None))
                   for i, (d, c) in enumerate(closes)])
        s.add_all([BiotechLongClose(ticker="ZZQD", trade_date=d, close=c, volume=7.0) for d, c in closes])
    calls: list[tuple[str, str]] = []

    async def fetch(t, period):
        calls.append((t, period))
        return {"closes": closes, "volumes": vols}

    res = await bq.refill_volumes(candidates=["ZZQC", "ZZQD"], fetch=fetch, pause=0)
    assert calls == [("ZZQC", bq.FIRST_PERIOD)]                        # 빈 행이 있는 종목만 · 종목당 1번
    assert res["targets"] == 1 and res["ok"] == 1 and res["filled"] == 280
    async with bq._session() as s:
        rows = {r.trade_date: r.volume for r in (await s.execute(select(BiotechLongClose).where(
            BiotechLongClose.ticker == "ZZQC"))).scalars()}
    assert rows[closes[0][0]] == vols[closes[0][0]] and rows[closes[-1][0]] == 5.0   # 있던 값은 덮지 않음
    # 하루 잡(run_quotes)은 이 함수를 부르지 않는다
    import inspect

    assert "refill_volumes" not in inspect.getsource(bq.run_quotes)
