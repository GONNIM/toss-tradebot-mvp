"""1128-01 ㉣ · 미국 비후보 종목 가격 칸 (관리자 전용 · 야후). 바깥 호출은 모두 가짜 함수 · 가짜 yfinance 로 바꾼다.

시험 자료의 숫자 · 종목 이름은 모두 지어낸 값이다 (교훈 #27: 공개 저장소에 실제 응답 값을 올리지 않음).
기준 시각: 2026-11-30(월) 20:00 UTC = 미국 동부 15:00 (정규장 중 · 오늘 봉은 덜 끝남) = KST 12/01(화) 05:00 (다른 야후 잡 시간대 밖).
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from backend.services import biotech_quotes as bq
from backend.services import us_quotes as uq
from backend.services.models import (CrazyPick, DiscoverySerenityScore, HoldingSnapshot, MemeUniverse, TickerUniverse,
                                     UsQuoteClose, UsQuoteDay, UserJudgment)

TOKEN = "us_quotes_test_token_32chars_000"
H = {"X-API-Token": TOKEN}
NOW = datetime(2026, 11, 30, 20, 0, tzinfo=timezone.utc)        # 월 15:00 ET · 화 05:00 KST
DAY = date(2026, 11, 30)                                          # 미국 동부 거래일 키
LAST_DONE = date(2026, 11, 27)                                    # 끝난 마지막 거래일 (오늘 11/30 봉은 덜 끝남 · 11/28~29 주말)
_ORIG_DEFAULT_FETCH = uq.default_fetch
CLOSE_LAST = 123.45                                               # 지어낸 값
INTRADAY = 999.99                                                 # 야후 info 의 장중 값 (화면 종가로 쓰이면 안 됨)


def _days(n: int, end: date) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def fake_raw(with_today: bool = True) -> dict:
    """야후 받기 결과 모양 (bq.default_fetch 와 같은 칸) · 값은 지어낸 것."""
    days = _days(300, LAST_DONE)
    closes = [(d, 100.0 + (i % 20)) for i, d in enumerate(days)]
    closes[-1] = (LAST_DONE, CLOSE_LAST)
    vols = {d: 1000.0 + i for i, (d, _c) in enumerate(closes)}
    if with_today:   # 정규장 중 받으면 오늘 덜 끝난 봉이 끼어 온다
        closes.append((DAY, 777.77))
        vols[DAY] = 5.0
    return {
        "info": {"exchange": "NMS", "currentPrice": INTRADAY, "regularMarketVolume": 424242, "averageVolume": 2000.0,
                 "marketCap": 3.0e9, "fiftyTwoWeekLow": 90.0, "fiftyTwoWeekHigh": 140.0, "totalCash": 1.5e8,
                 "numberOfAnalystOpinions": 4, "recommendationKey": "hold",
                 "targetMeanPrice": 130.0, "targetMedianPrice": 128.0, "targetHighPrice": 150.0, "targetLowPrice": 110.0},
        "dist": {"strongBuy": 1, "buy": 1, "hold": 2, "sell": 0, "strongSell": 0},
        "changes": [{"date": "2026-11-20", "firm": "가상증권", "to_grade": "Hold", "from_grade": "Buy", "action": "down",
                     "pt_now": 130.0, "pt_prior": 140.0}],
        "closes": closes, "volumes": vols,
    }


class Yahoo:
    """바깥 호출 세는 가짜 야후."""

    def __init__(self):
        self.calls: list[str] = []
        self.times: list[float] = []
        self.result: object = fake_raw()
        self.delay = 0.0

    async def fetch(self, ticker: str) -> dict:
        self.calls.append(ticker)
        self.times.append(asyncio.get_event_loop().time())
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class RateLimited(Exception):
    pass


@pytest.fixture
async def yh(monkeypatch):
    from backend.services.db import get_session, init_db

    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    await init_db()
    async with get_session() as s:
        for tbl in (UsQuoteDay, UsQuoteClose, TickerUniverse, MemeUniverse, DiscoverySerenityScore, HoldingSnapshot,
                    UserJudgment, CrazyPick):
            await s.execute(delete(tbl))
        s.add(TickerUniverse(symbol="ZQAA", market="NASDAQ", category="satellite"))
        s.add(TickerUniverse(symbol="ZQAB", market="NASDAQ", category="satellite"))
        s.add(TickerUniverse(symbol="ZQAC", market="NASDAQ", category="satellite"))
    y = Yahoo()
    uq._TICKER_LOCKS.clear()
    uq._LAST_CALL[0] = 0.0
    monkeypatch.setattr(uq, "MIN_GAP_SEC", 0.0)
    monkeypatch.setattr(uq, "default_fetch", y.fetch)
    monkeypatch.setattr(uq, "_now", lambda n=None: n or NOW)

    async def cands():
        return {"BIOX"}

    monkeypatch.setattr(bq, "candidate_set", cands)
    return y


@pytest.fixture
async def client(yh):
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _rows(model, *where):
    from backend.services.db import get_session

    async with get_session() as s:
        return (await s.execute(select(model).where(*where))).scalars().all()


# ── 허용 목록 (막음 ㄴ) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_allowed_sources_and_shapes(yh):
    from backend.services.db import get_session

    async with get_session() as s:
        s.add(MemeUniverse(market="US", ticker="ZQMU", name="가상밈"))
        s.add(MemeUniverse(market="KRX", ticker="ZQKR", name="국내밈"))            # 시장이 US 가 아니면 불허
        s.add(DiscoverySerenityScore(ticker="ZQSE"))
        s.add(HoldingSnapshot(symbol="ZQHD", market="US", trade_date=DAY, kind="holding"))
        s.add(HoldingSnapshot(symbol="ZQHK", market="KR", trade_date=DAY, kind="holding"))
        s.add(UserJudgment(ticker="zqjd", page_source="manual", hypothesis_id="h", thesis_md="가상"))   # 소문자 저장
        s.add(UserJudgment(ticker="005930", page_source="manual", hypothesis_id="h", thesis_md="가상"))  # 국내 코드
        s.add(CrazyPick(ticker="ZQCR", pick_date="2026-11-27", rank=1, composite_score=1.0))
    for ok in ("ZQAA", "zqaa", "ZQMU", "ZQSE", "ZQHD", "ZQJD", "ZQCR"):
        assert await uq.lookup_allowed(ok) == ok.upper(), ok
    for no in ("ZQKR", "ZQHK", "005930", "00593O", "ZQNONE", "", "../x", "123", "한글", "A" * 20):
        assert await uq.lookup_allowed(no) is None, no


# ── 인증 · 목록 밖 · 후보 · 국내 = 바깥 호출 0 ─────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{}, {"X-API-Token": "wrong-token-value-xxxxxxxxxxxxxxxx"}])
async def test_non_admin_is_401_zero_calls(client, yh, headers):
    for t in ("ZQAA", "ZQNONE", "BIOX"):
        assert (await client.get(f"/api/v1/stock/{t}/quote", headers=headers)).status_code == 401
    assert yh.calls == [] and await _rows(UsQuoteDay) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("t", ["ZQNONE", "BIOX", "123", "A" * 20])
async def test_unlisted_and_candidate_are_404_zero_calls(client, yh, t):
    r = await client.get(f"/api/v1/stock/{t}/quote", headers=H)
    assert r.status_code in (400, 404)
    assert yh.calls == [] and await _rows(UsQuoteDay) == []


@pytest.mark.asyncio
async def test_candidate_in_table_still_404_and_not_fetched_twice(client, yh):
    from backend.services.db import get_session

    async with get_session() as s:
        s.add(TickerUniverse(symbol="BIOX", market="NASDAQ", category="satellite"))   # 허용 표에도 있는 후보
    r = await client.get("/api/v1/stock/BIOX/quote", headers=H)
    assert r.status_code == 404 and "바이오" in r.json()["detail"]
    assert yh.calls == []                                                             # 권고 ㅁ · 새 길로 받지 않음


@pytest.mark.asyncio
async def test_empty_candidate_set_blocks_fetch(client, yh, monkeypatch):
    async def none():
        return set()

    monkeypatch.setattr(bq, "candidate_set", none)
    assert (await client.get("/api/v1/stock/ZQAA/quote", headers=H)).status_code == 404
    assert yh.calls == []


@pytest.mark.asyncio
async def test_public_overview_makes_zero_yahoo_calls_and_sets_flag(client, yh, monkeypatch):
    """공개 GET /stock/{ticker}: 야후 · yfinance 어느 쪽도 부르지 않는다 (막음 ㄹ ⑤)."""
    boom = types.ModuleType("yfinance")

    def _no(*a, **k):
        raise AssertionError("공개 종목 API 가 yfinance 를 불렀음")

    boom.Ticker = _no
    monkeypatch.setitem(sys.modules, "yfinance", boom)

    async def _default(*a, **k):
        raise AssertionError("공개 종목 API 가 야후 받기를 불렀음")

    monkeypatch.setattr(bq, "default_fetch", _default)
    monkeypatch.setattr(uq, "default_fetch", _default)
    for t, flag in (("ZQAA", True), ("ZQNONE", False), ("BIOX", False), ("005930", False)):
        r = await client.get(f"/api/v1/stock/{t}")          # 토큰 없음 = 비로그인
        assert r.status_code == 200, t
        assert r.json()["us_quote_available"] is flag, t
    assert yh.calls == [] and await _rows(UsQuoteDay) == []


# ── 받기 · 종가 날짜 (막음 ㄷ) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_first_request_fetches_once_and_uses_last_completed_close(client, yh):
    r = await client.get("/api/v1/stock/zqaa/quote", headers=H)
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    b = r.json()
    assert yh.calls == ["ZQAA"]
    assert b["ticker"] == "ZQAA" and b["kind"] == "us_stored"
    # 종가 = 끝난 마지막 거래일 일봉 (장중 값 · 덜 끝난 오늘 봉이 아님) + 그 날짜
    assert b["basics"]["price_close"] == CLOSE_LAST and b["basics"]["price_close"] != INTRADAY
    assert b["close_date"] == LAST_DONE.isoformat() and b["asof"] == DAY.isoformat()
    assert b["basics"]["volume"] == 1000.0 + 299 and b["basics"]["volume"] != 424242
    assert (b["basics"]["avg_volume"], b["basics"]["market_cap"]) == (2000.0, 3.0e9)
    # 그림: 오늘 봉 제외 · 거래량 v 포함
    ch = b["chart"]
    assert ch["daily"][-1]["v"] == 1000.0 + 299 and all(p["v"] is not None for p in ch["daily"])
    assert ch["daily_source"]["to"] == LAST_DONE.isoformat()
    assert ch["week40"]["series"][-1]["v"] is not None
    # 응답 모양 (권고 ㅂ · ㅅ)
    assert b["live"] is None and b["summary"] is None and b["sec8k"] is None
    assert "실시간 실패" not in json.dumps(b, ensure_ascii=False) and "바이오 후보만" in b["live_note"]
    op = b["opinion"]
    assert op["head"] == "전문가 의견 모음 · 추정 · 보장 아님" and op["source"] == "야후 (yfinance)"
    assert op["asof"] == DAY.isoformat() and "표시 전용" in op["use_note"] and op["n_opinions"] == 4
    assert b["notes"] == []


@pytest.mark.asyncio
async def test_after_close_today_bar_is_used(yh):
    after = datetime(2026, 11, 30, 21, 50, tzinfo=timezone.utc)     # 16:50 ET · 정규장 끝남 · 06:50 KST (막는 시간 밖)
    assert uq.last_complete_date(after) == DAY
    assert uq.last_complete_date(NOW) == LAST_DONE
    assert uq.last_complete_date(datetime(2026, 12, 5, 15, 0, tzinfo=timezone.utc)) == date(2026, 12, 4)   # 토요일 → 금요일
    assert uq.trading_day(datetime(2026, 12, 5, 15, 0, tzinfo=timezone.utc)) == date(2026, 12, 4)
    assert uq.trading_day(datetime(2026, 12, 6, 15, 0, tzinfo=timezone.utc)) == date(2026, 12, 4)
    b = await uq.quote_view("ZQAA", fetch=yh.fetch, now=after)
    assert b["close_date"] == DAY.isoformat() and b["basics"]["price_close"] == 777.77


@pytest.mark.asyncio
async def test_same_day_second_request_not_fetched_again(client, yh):
    for _ in range(3):
        assert (await client.get("/api/v1/stock/ZQAA/quote", headers=H)).status_code == 200
    assert yh.calls == ["ZQAA"]
    assert len(await _rows(UsQuoteDay)) == 1
    # 다음 거래일에는 다시 받는다
    nxt = NOW + timedelta(days=1)
    await uq.quote_view("ZQAA", fetch=yh.fetch, now=nxt)
    assert yh.calls == ["ZQAA", "ZQAA"] and len(await _rows(UsQuoteDay)) == 2


@pytest.mark.asyncio
async def test_failed_fetch_is_recorded_counted_and_not_retried(client, yh):
    yh.result = RuntimeError("가짜 실패")
    b = (await client.get("/api/v1/stock/ZQAA/quote", headers=H)).json()
    assert b["basics"] is None and b["chart"] is None
    assert any("가격을 받지 못했습니다" in n for n in b["notes"])
    rows = await _rows(UsQuoteDay)
    assert [(r.ticker, r.status, r.error) for r in rows] == [("ZQAA", "failed", "RuntimeError")]
    b2 = (await client.get("/api/v1/stock/ZQAA/quote", headers=H)).json()
    assert yh.calls == ["ZQAA"]                                     # 같은 날 다시 받지 않음
    assert any("내일 다시" in n for n in b2["notes"])


@pytest.mark.asyncio
async def test_empty_history_is_failure_row(client, yh):
    raw = fake_raw()
    raw["closes"] = []
    yh.result = raw
    b = (await client.get("/api/v1/stock/ZQAA/quote", headers=H)).json()
    assert b["basics"] is None
    assert [(r.status, r.error) for r in await _rows(UsQuoteDay)] == [("failed", "empty_history")]


@pytest.mark.asyncio
async def test_timeout_is_failure_row(yh, monkeypatch):
    monkeypatch.setattr(uq, "FETCH_TIMEOUT", 0.05)
    yh.delay = 0.5
    b = await uq.quote_view("ZQAA", fetch=yh.fetch, now=NOW)
    assert b["basics"] is None and any("받지 못했습니다" in n for n in b["notes"])
    assert [r.status for r in await _rows(UsQuoteDay)] == ["failed"]


# ── 하루 상한 50 (막음 ㄴ) ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_daily_cap_counts_rows_including_failed(client, yh):
    from backend.services.db import get_session

    async with get_session() as s:
        for i in range(uq.DAILY_TICKER_CAP - 1):
            s.add(UsQuoteDay(ticker=f"FILL{i}", fetch_day=DAY, status="failed" if i % 2 else "ok"))
        s.add(UsQuoteDay(ticker="OLDX", fetch_day=DAY - timedelta(days=1), status="ok"))   # 다른 날 행은 세지 않음
    assert (await client.get("/api/v1/stock/ZQAA/quote", headers=H)).status_code == 200   # 50번째
    assert yh.calls == ["ZQAA"]
    r = await client.get("/api/v1/stock/ZQAB/quote", headers=H)                            # 51번째
    b = r.json()
    assert r.status_code == 200 and yh.calls == ["ZQAA"] and b["basics"] is None
    assert any("상한(50종목)을 넘었습니다" in n and "내일 다시 보입니다" in n for n in b["notes"])
    # 상한은 DB 행 수라 재시작(메모리 초기화)해도 이어진다
    uq._TICKER_LOCKS.clear()
    await client.get("/api/v1/stock/ZQAC/quote", headers=H)
    assert yh.calls == ["ZQAA"]
    # 이미 받은 종목은 상한이어도 저장 값을 보여 준다
    assert (await client.get("/api/v1/stock/ZQAA/quote", headers=H)).json()["basics"]["price_close"] == CLOSE_LAST


# ── 시간대 · 429 (막음 ㄹ ③ ④) ────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("utc,blocked", [
    ((2026, 11, 30, 21, 0), True),    # 화 06:00 KST
    ((2026, 11, 30, 21, 44), True),   # 화 06:44
    ((2026, 11, 30, 21, 45), False),  # 화 06:45
    ((2026, 11, 30, 22, 0), True),    # 화 07:00
    ((2026, 12, 1, 0, 29), True),     # 화 09:29
    ((2026, 12, 1, 0, 30), False),    # 화 09:30
    ((2026, 11, 29, 22, 30), False),  # 월 07:30 KST (월요일은 화~토 창이 아님)
    ((2026, 11, 29, 21, 10), True),   # 월 06:10 KST (06:00 창은 매일)
    ((2026, 12, 4, 22, 30), True),    # 토 07:30
    ((2026, 12, 5, 22, 30), False),   # 일 07:30
])
async def test_block_windows(utc, blocked):
    assert uq.in_block_window(datetime(*utc, tzinfo=timezone.utc)) is blocked


@pytest.mark.asyncio
async def test_block_window_shows_stored_only_zero_calls(yh):
    first = await uq.quote_view("ZQAA", fetch=yh.fetch, now=NOW)            # 05:00 KST · 받음
    assert first["basics"]["price_close"] == CLOSE_LAST and yh.calls == ["ZQAA"]
    win = datetime(2026, 12, 1, 22, 30, tzinfo=timezone.utc)                # 수 07:30 KST · 미국 동부 12/01 17:30 = 다음 거래일 키
    assert uq.in_block_window(win)
    b = await uq.quote_view("ZQAA", fetch=yh.fetch, now=win)                # 다음 날이지만 막는 시간 → 저장 값만
    assert yh.calls == ["ZQAA"] and b["basics"]["price_close"] == CLOSE_LAST
    assert any("다른 시세 수집 시간" in n for n in b["notes"])
    b2 = await uq.quote_view("ZQAB", fetch=yh.fetch, now=win)               # 저장 값도 없는 종목
    assert yh.calls == ["ZQAA"] and b2["basics"] is None and b2["empty_note"]
    assert await _rows(UsQuoteDay, UsQuoteDay.ticker == "ZQAB") == []       # 행도 만들지 않음 (상한에 안 셈)


@pytest.mark.asyncio
async def test_429_stops_screen_fetches_for_the_day(client, yh):
    yh.result = RateLimited("429 Too Many Requests")
    b = (await client.get("/api/v1/stock/ZQAA/quote", headers=H)).json()
    assert b["basics"] is None and [r.status for r in await _rows(UsQuoteDay)] == ["rate_limited"]
    yh.result = fake_raw()
    b2 = (await client.get("/api/v1/stock/ZQAB/quote", headers=H)).json()
    assert yh.calls == ["ZQAA"] and b2["basics"] is None                    # 다른 종목도 그날은 받지 않음
    assert any("호출을 제한" in n for n in b2["notes"])
    # 다음 거래일에는 다시 받는다
    await uq.quote_view("ZQAB", fetch=yh.fetch, now=NOW + timedelta(days=1))
    assert yh.calls == ["ZQAA", "ZQAB"]


def test_is_rate_limit_detection():
    class YFRateLimitError(Exception):
        pass

    assert uq.is_rate_limit(YFRateLimitError("x")) and uq.is_rate_limit(RuntimeError("HTTP 429"))
    assert uq.is_rate_limit(RuntimeError("Too Many Requests. Rate limited"))
    assert not uq.is_rate_limit(RuntimeError("boom")) and not uq.is_rate_limit(TimeoutError())


# ── 잠금 · 간격 · 세션 밖 받기 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_same_ticker_fetches_once(client, yh):
    yh.delay = 0.05
    rs = await asyncio.gather(*[client.get("/api/v1/stock/ZQAA/quote", headers=H) for _ in range(6)])
    assert all(r.status_code == 200 for r in rs)
    assert yh.calls == ["ZQAA"]
    assert all(r.json()["basics"] is not None for r in rs)


@pytest.mark.asyncio
async def test_global_lock_serializes_and_keeps_gap(yh, monkeypatch):
    monkeypatch.setattr(uq, "MIN_GAP_SEC", 0.3)
    yh.delay = 0.05
    await asyncio.gather(*[uq.quote_view(t, fetch=yh.fetch, now=NOW) for t in ("ZQAA", "ZQAB", "ZQAC")])
    assert sorted(yh.calls) == ["ZQAA", "ZQAB", "ZQAC"]
    gaps = [b - a for a, b in zip(yh.times, yh.times[1:])]
    assert all(g >= 0.3 + 0.05 - 0.02 for g in gaps), gaps               # 받기 끝 → 다음 받기 시작 사이 0.3초 이상


@pytest.mark.asyncio
async def test_fetch_runs_outside_db_session(yh, monkeypatch):
    depth = [0]
    real = uq._session

    class Tracked:
        def __init__(self):
            self.cm = real()

        async def __aenter__(self):
            depth[0] += 1
            return await self.cm.__aenter__()

        async def __aexit__(self, *a):
            depth[0] -= 1
            return await self.cm.__aexit__(*a)

    seen = []

    async def fetch(t):
        seen.append(depth[0])
        return fake_raw()

    monkeypatch.setattr(uq, "_session", lambda: Tracked())
    b = await uq.quote_view("ZQAA", fetch=fetch, now=NOW)
    assert seen == [0] and b["basics"] is not None                       # 받는 동안 열린 세션 0 (1102-08)


# ── 보존 (권고 ㅇ) · 표 분리 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retention_prunes_old_rows_and_orphan_closes_only_in_new_tables(yh):
    from backend.services.db import get_session
    from backend.services.models import BiotechLongClose, BiotechQuoteDaily

    old = DAY - timedelta(days=uq.KEEP_DAYS + 1)
    async with get_session() as s:
        s.add(UsQuoteDay(ticker="OLDA", fetch_day=old, status="ok"))
        s.add(UsQuoteClose(ticker="OLDA", trade_date=old, close=1.0))
        s.add(UsQuoteDay(ticker="KEEP", fetch_day=DAY - timedelta(days=5), status="ok"))
        s.add(UsQuoteClose(ticker="KEEP", trade_date=DAY - timedelta(days=5), close=2.0))
        s.add(BiotechLongClose(ticker="OLDA", trade_date=old, close=3.0))     # 바이오 표는 건드리지 않음
        s.add(BiotechQuoteDaily(ticker="OLDA", asof_date=old))
    await uq.quote_view("ZQAA", fetch=yh.fetch, now=NOW)
    assert {r.ticker for r in await _rows(UsQuoteDay)} == {"KEEP", "ZQAA"}
    assert {r.ticker for r in await _rows(UsQuoteClose)} == {"KEEP", "ZQAA"}
    assert len(await _rows(BiotechLongClose, BiotechLongClose.ticker == "OLDA")) == 1
    assert len(await _rows(BiotechQuoteDaily, BiotechQuoteDaily.ticker == "OLDA")) == 1


@pytest.mark.asyncio
async def test_new_fetch_replaces_ticker_closes_wholesale(yh):
    await uq.quote_view("ZQAA", fetch=yh.fetch, now=NOW)
    n1 = len(await _rows(UsQuoteClose, UsQuoteClose.ticker == "ZQAA"))
    assert n1 == 300 and max(r.trade_date for r in await _rows(UsQuoteClose)) == LAST_DONE   # 오늘 봉은 저장하지 않음
    raw = fake_raw(with_today=False)
    raw["closes"] = raw["closes"][-50:]
    yh.result = raw
    await uq.quote_view("ZQAA", fetch=yh.fetch, now=NOW + timedelta(days=1))
    assert len(await _rows(UsQuoteClose, UsQuoteClose.ticker == "ZQAA")) == 50


# ── 가짜 yfinance 모듈로 기본 받기 함수까지 ────────────────────────────────

@pytest.mark.asyncio
async def test_default_fetch_with_fake_yfinance_module(yh, monkeypatch):
    import pandas as pd

    raw = fake_raw()
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in raw["closes"]])
    hist = pd.DataFrame({"Close": [c for _, c in raw["closes"]], "Volume": [raw["volumes"][d] for d, _ in raw["closes"]]}, index=idx)
    asked: list = []

    class FakeTicker:
        def __init__(self, sym):
            asked.append(sym)
            self.info = raw["info"]
            self.recommendations_summary = pd.DataFrame([{"period": "0m", **raw["dist"]}])
            self.upgrades_downgrades = pd.DataFrame()

        def history(self, period, auto_adjust):
            asked.append(period)
            return hist

    fake = types.ModuleType("yfinance")
    fake.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    monkeypatch.setattr(uq, "default_fetch", _ORIG_DEFAULT_FETCH)   # 가짜 야후 함수를 걷어내고 진짜 받기 함수를 탄다
    b = await uq.quote_view("ZQAA", now=NOW)                                    # 기본 받기 함수 = bq.default_fetch(6y)
    assert asked == ["ZQAA", "6y"]
    assert b["basics"]["price_close"] == CLOSE_LAST and b["close_date"] == LAST_DONE.isoformat()
    assert b["opinion"]["n_opinions"] == 4 and b["opinion"]["dist"]["hold"] == 2


@pytest.mark.asyncio
async def test_overview_flag_hides_private_tables_from_non_admin(client, yh):
    """Fable 병합 막음 ㄱ · 보유 · 판단 기록만 있는 기호는 비관리자에게 false, 관리자에게 true."""
    from backend.services.db import get_session

    async with get_session() as s:
        s.add(HoldingSnapshot(symbol="ZQHO", market="US", trade_date=DAY, kind="holding"))
        s.add(UserJudgment(ticker="ZQJO", page_source="manual", hypothesis_id="h", thesis_md="가상"))
    for t in ("ZQHO", "ZQJO"):
        pub = (await client.get(f"/api/v1/stock/{t}")).json()
        adm = (await client.get(f"/api/v1/stock/{t}", headers=H)).json()
        assert pub["us_quote_available"] is False, t
        assert adm["is_admin"] is True and adm["us_quote_available"] is True, t
    pub = (await client.get("/api/v1/stock/ZQAA")).json()          # 공개 표(universe)는 비관리자에게도 true
    assert pub["us_quote_available"] is True
    assert await uq.lookup_allowed("ZQHO", public=True) is None and await uq.lookup_allowed("ZQHO") == "ZQHO"
