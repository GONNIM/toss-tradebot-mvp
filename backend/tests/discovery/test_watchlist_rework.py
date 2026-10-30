"""1030-04 Watchlist 재료 재기획 단위 테스트 · 외부 네트워크·토스 호출 없음 (가짜 클라이언트).

P1 출처(파싱·URL 중복) · P2 뉴스 매칭 · P3 이름 · P4 순위 신호 · P4b DART · 화면용 근거·/sources.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.api.main import app
from backend.discovery.live_tape.params import SniperParams
from backend.discovery.watchlist import dart_events, rank_signals as rs
from backend.discovery.watchlist import matcher as matcher_mod
from backend.discovery.watchlist.dart_names import dart_names
from backend.discovery.watchlist.evidence import build_evidence
from backend.discovery.watchlist.finalize import finalize_watchlist, list_watchlist
from backend.discovery.watchlist.matcher import MatcherEntry, TickerMatcher
from backend.discovery.watchlist.news_rss import _parse_pub_str
from backend.discovery.watchlist.store import signals_for_date, upsert_signal
from backend.services.db import get_session, init_db
from backend.services.models import (
    MemeCatalystEvent, Watchlist, WatchlistRankDaily, WatchlistSignal,
)

_KST = timezone(timedelta(hours=9))


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        for model in (WatchlistSignal, WatchlistRankDaily, MemeCatalystEvent, Watchlist):
            await session.execute(delete(model))
    yield


def _matcher(*entries: tuple[str, str]) -> TickerMatcher:
    m = TickerMatcher()
    m._entries = [MatcherEntry(t, n, "KOSPI") for t, n in entries]
    m._entries.sort(key=lambda e: -len(e.name))
    m._name_index = [(e.name.lower(), e.ticker) for e in m._entries]
    m._aliases = {}   # 별칭 파일과 무관하게
    return m


# ═══════════════════════════════════════════════════════════════
# P1 · 발행시각 · URL 중복
# ═══════════════════════════════════════════════════════════════
def test_parse_pub_colon_offset_is_not_read_as_utc():
    dt = _parse_pub_str("Fri, 30 Oct 2026 17:46:01 +09:00")
    assert dt == datetime(2026, 10, 30, 8, 46, 1, tzinfo=timezone.utc)


def test_parse_pub_existing_formats_unchanged():
    assert _parse_pub_str("Fri,30 Oct 2026 06:00:00 +0900") == datetime(2026, 10, 29, 21, 0, tzinfo=timezone.utc)
    assert _parse_pub_str("2026-10-30 10:18:00") == datetime(2026, 10, 30, 1, 18, tzinfo=timezone.utc)
    assert _parse_pub_str("Fri, 30 Oct 2026 17:46:01 -0000") == datetime(2026, 10, 30, 17, 46, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_url_dedup_across_news_sources():
    url = "https://news.example.com/a/1"
    a = await upsert_signal(ticker="005930", source="news_yonhap", signal_type="headline",
                            intensity=1.0, dedup_url=url, payload={"url": url})
    b = await upsert_signal(ticker="005930", source="news_yna_market", signal_type="headline",
                            intensity=1.0, dedup_url=url, payload={"url": url},
                            detected_at=datetime.now(tz=timezone.utc) + timedelta(hours=1))
    other_ticker = await upsert_signal(ticker="000660", source="news_yna_market", signal_type="headline",
                                       intensity=1.0, dedup_url=url, payload={"url": url})
    assert a is not None
    assert b is None                      # 같은 ticker · 같은 URL · 다른 뉴스 출처 → skip
    assert other_ticker is not None       # 다른 종목은 별개


@pytest.mark.asyncio
async def test_url_dedup_does_not_cross_into_non_news_sources():
    key = "same-key"
    a = await upsert_signal(ticker="005930", source="news_mk", signal_type="headline",
                            intensity=1.0, dedup_url=key, payload={"key": key})
    b = await upsert_signal(ticker="005930", source="rank_toss_amount", signal_type="rank_new",
                            intensity=0.8, dedup_url=key, payload={"key": key},
                            detected_at=datetime.now(tz=timezone.utc) + timedelta(hours=1))
    assert a is not None and b is not None


# ═══════════════════════════════════════════════════════════════
# P2 · 뉴스 전용 매칭
# ═══════════════════════════════════════════════════════════════
def test_match_news_ascii_name_needs_non_alnum_neighbors():
    m = _matcher(("108320", "LS"), ("005930", "삼성전자"))
    assert m.match_news("ELS 상품 발행 급증") == []                 # ELS 안의 LS
    assert m.match_news("LS 그룹 실적 발표") == [("108320", 1.0)]
    # match_text(유튜브·화약고가 씀) 는 그대로 부분 일치
    assert m.match_text("ELS 상품") == ["108320"]


def test_match_news_two_char_name_title_only():
    m = _matcher(("000270", "기아"), ("005930", "삼성전자"))
    assert m.match_news("기아 신차 공개") == [("000270", 1.0)]
    assert m.match_news("자동차 업계 동향", "기아 의 신차 발표") == []        # 요약만이면 안 걸림
    assert m.match_news("삼성전자 반등", "기아 도 상승") == [("005930", 1.0)]


def test_match_news_summary_only_half_weight():
    m = _matcher(("005930", "삼성전자"), ("068270", "셀트리온"))
    assert m.match_news("증시 마감 시황", "셀트리온 이 올랐다") == [("068270", 0.5)]
    # 제목에서도 걸리면 제목 가중
    assert m.match_news("셀트리온 급등", "셀트리온 소식") == [("068270", 1.0)]


def test_match_news_many_tickers_split_evenly():
    m = _matcher(("1", "에이회사"), ("2", "비이회사"), ("3", "씨이회사"), ("4", "디이회사"))
    got = dict(m.match_news("에이회사 비이회사 씨이회사 디이회사 일제히"))
    assert set(got) == {"1", "2", "3", "4"}
    assert all(w == pytest.approx(0.25) for w in got.values())
    three = dict(m.match_news("에이회사 비이회사 씨이회사 소식"))
    assert all(w == 1.0 for w in three.values())     # 3종목까지는 분산 안 함


def test_match_news_alias_and_longest_first():
    m = _matcher(("005930", "삼성전자"), ("207940", "삼성바이오로직스"))
    m._aliases = {"삼전": "005930", "하이닉스": "000660"}
    assert ("005930", 1.0) in m.match_news("삼전 5만원 회복")
    assert ("000660", 1.0) in m.match_news("하이닉스 HBM 수주")
    got = m.match_news("삼성바이오로직스 수주")
    assert got == [("207940", 1.0)]                   # 긴 이름이 먼저 소비돼 「삼성」 부분 일치 없음


def test_default_aliases_file_or_seed_loads():
    m = TickerMatcher()
    aliases = m._alias_table()
    assert aliases["삼전"] == "005930" and aliases["LG엔솔"] == "373220"


@pytest.mark.asyncio
async def test_news_rss_uses_weight_as_intensity(monkeypatch):
    from backend.discovery.watchlist import news_rss as rss_mod

    m = _matcher(("005930", "삼성전자"))
    monkeypatch.setattr(rss_mod, "get_matcher", lambda: m)
    pub = (datetime.now(tz=timezone.utc) - timedelta(minutes=10)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    xml = (f'<?xml version="1.0"?><rss version="2.0"><channel><item><title>시황 점검</title>'
           f"<description>삼성전자 소식</description><link>https://x.test/1</link><pubDate>{pub}</pubDate>"
           f"</item></channel></rss>")

    class _Resp:
        status_code = 200
        text = xml

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, timeout=None, follow_redirects=True): return _Resp()

    monkeypatch.setattr(rss_mod.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(rss_mod, "RSS_SOURCES", {"news_mk": "u"})
    await rss_mod.poll_news_rss()
    async with get_session() as session:
        sig = (await session.execute(select(WatchlistSignal))).scalars().all()
    assert len(sig) == 1 and sig[0].intensity == 0.5      # 요약에서만 걸림 ×0.5


def test_rss_sources_changed():
    from backend.discovery.watchlist.news_rss import RSS_SOURCES
    from backend.discovery.watchlist.source_groups import NEWS_SOURCES

    assert "news_edaily" not in RSS_SOURCES
    assert {"news_mk", "news_sedaily", "news_yna_market", "news_etoday", "news_einfomax_all"} <= set(RSS_SOURCES)
    assert set(RSS_SOURCES) == NEWS_SOURCES


# ═══════════════════════════════════════════════════════════════
# P3 · 이름
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_reload_keeps_previous_kospi_on_failure_and_uses_file_after_restart(monkeypatch):
    calls = {"n": 0}

    async def _kospi(limit):
        calls["n"] += 1
        if calls["n"] == 1:
            return [MatcherEntry("005930", "삼성전자", "KOSPI")]
        raise RuntimeError("fdr down")

    monkeypatch.setattr(matcher_mod, "_load_kospi_top", _kospi)
    m = TickerMatcher()
    await m.reload()
    assert any(e.ticker == "005930" for e in m.entries())

    await m.reload()      # 두 번째는 실패 → 직전 코스피 유지 (코스닥만으로 덮지 않음)
    assert any(e.ticker == "005930" for e in m.entries())

    fresh = TickerMatcher()    # 재시작 · 메모리 없음 → 런타임 파일의 마지막 성공 목록
    await fresh.reload()
    assert any(e.ticker == "005930" and e.name == "삼성전자" for e in fresh.entries())


def test_dart_names_maps_stock_code_to_name(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"현대자동차": {"corp_code": "1", "stock_code": "005380"}, "비상장": {"corp_code": "2", "stock_code": ""}}',
                 encoding="utf-8")
    assert dart_names(p) == {"005380": "현대자동차"}
    assert dart_names(tmp_path / "none.json") == {}     # 파일 없음은 오류가 아니라 빈 표


@pytest.mark.asyncio
async def test_finalize_fills_blank_name_from_dart_table(monkeypatch):
    from backend.discovery.watchlist import finalize as fin

    monkeypatch.setattr(fin, "dart_names", lambda: {"900001": "이름표회사"})
    m = _matcher()
    m._loaded_at = datetime.now(tz=timezone.utc)
    monkeypatch.setattr(fin, "get_matcher", lambda: m)
    await upsert_signal(ticker="900001", source="news_mk", signal_type="headline", intensity=1.0,
                        trade_date="2026-10-30", payload={"title": "t"})
    await finalize_watchlist(trade_date="2026-10-30")
    items = await list_watchlist("2026-10-30")
    assert items and items[0]["name"] == "이름표회사"


# ═══════════════════════════════════════════════════════════════
# P4 · 순위 신호
# ═══════════════════════════════════════════════════════════════
def test_rank_intensity_new_entry_and_rise():
    assert rs.rank_intensity(1, None) == 1.0
    assert rs.rank_intensity(100, None) == pytest.approx(0.505)
    assert rs.rank_intensity(10, 15) is None               # 5계단 상승은 신호 아님
    up = rs.rank_intensity(10, 90)                         # 80계단 상승
    assert up is not None and up <= 0.8 < rs.rank_intensity(100, None) + 0.3
    assert 0.0 < up <= 0.8
    assert rs.rank_intensity(10, 90) > rs.rank_intensity(10, 40)


def test_is_chase_uses_percent_threshold():
    assert rs.is_chase(0.11, 10.0) is True
    assert rs.is_chase(0.10, 10.0) is False
    assert rs.is_chase(None, 10.0) is False


def test_params_new_defaults():
    p = SniperParams()
    assert p.watchlist_chase_max_change_pct == 10.0
    assert p.watchlist_min_composite_score == 0.5
    assert p.watchlist_execute_enabled is False


def _ranking(ranked_at, rows):
    """GET /rankings result · rows = [(symbol, rank, changeRate)]."""
    return {"rankedAt": ranked_at, "rankings": [
        {"rank": r, "symbol": s, "currency": "KRW",
         "price": {"lastPrice": "1000", "basePrice": "900", "changeRate": cr},
         "tradingVolume": "1", "tradingAmount": str(1000 - r)}
        for s, r, cr in rows]}


def _investor(ranked_at, rows):
    return {"individual": {"rankedAt": ranked_at, "netBuyRankings": [
        {"rank": r, "symbol": s, "currency": "KRW", "netBuyAmount": str(5000 - r)} for s, r in rows],
        "netSellRankings": []}, "foreigner": {"rankedAt": None, "netBuyRankings": [], "netSellRankings": []},
        "institution": {"rankedAt": None, "netBuyRankings": [], "netSellRankings": []}}


class FakeToss:
    """토스 클라이언트 대역 · 호출을 기록한다."""

    def __init__(self, daily=None, realtime=None, investor=None, prices=None, candles=None):
        self.daily = daily or {}
        self.realtime = realtime or {}
        self.investor = investor
        self._prices = prices or {}
        self._candles = candles or {}
        self.calls: list[tuple] = []

    def rankings(self, *, type, market="KR", duration="realtime", exclude_caution=True, count=100):
        self.calls.append(("rankings", type, duration))
        src = self.daily if duration == "1d" else self.realtime
        return SimpleNamespace(result=src.get(type, {"rankedAt": None, "rankings": []}))

    def investor_trading_rankings(self, *, count=100):
        self.calls.append(("investor", count))
        return SimpleNamespace(result=self.investor or {})

    def prices(self, symbols):
        self.calls.append(("prices", tuple(symbols)))
        return [{"symbol": s, "lastPrice": str(self._prices[s]), "currency": "KRW"} for s in symbols if s in self._prices]

    def candles(self, symbol, count=200):
        self.calls.append(("candles", symbol))
        return self._candles.get(symbol, [])


_DAY1 = datetime(2026, 10, 30, 20, 30, tzinfo=_KST)     # 금
_DAY2 = datetime(2026, 11, 2, 20, 30, tzinfo=_KST)      # 월


def _day_client(day: str, *, indiv, toss_amt, mkt_amt=None, changes=None):
    iso = f"{day}T20:30:00+09:00"
    changes = changes or {}
    return FakeToss(
        investor=_investor(iso, indiv),
        daily={
            "TOSS_SECURITIES_TRADING_AMOUNT": _ranking(iso, [(s, r, changes.get(s, "0.02")) for s, r in toss_amt]),
            "TOSS_SECURITIES_TRADING_VOLUME": _ranking(iso, []),
            "MARKET_TRADING_AMOUNT": _ranking(iso, [(s, r, changes.get(s, "0.02")) for s, r in (mkt_amt or [])]),
            "MARKET_TRADING_VOLUME": _ranking(iso, []),
        },
    )


async def _rank_signals_in_db():
    async with get_session() as session:
        rows = (await session.execute(select(WatchlistSignal).order_by(WatchlistSignal.id))).scalars().all()
    return rows


@pytest.mark.asyncio
async def test_first_day_saves_but_no_signals():
    c = _day_client("2026-10-30", indiv=[("005930", 1)], toss_amt=[("005930", 1)], mkt_amt=[("005930", 1)])
    stats = await rs.collect_rank_daily(c, now=_DAY1)
    assert stats["kinds"]["individual_netbuy"]["state"] == "saved"
    assert await _rank_signals_in_db() == []            # 전 거래일 저장분이 없으니 신호 없음
    async with get_session() as session:
        n = len((await session.execute(select(WatchlistRankDaily))).scalars().all())
    assert n == 3
    # TOP_GAINERS 는 부르지 않는다
    assert all(call[1] != "TOP_GAINERS" for call in c.calls if call[0] == "rankings")


@pytest.mark.asyncio
async def test_second_day_new_entry_and_chase_exclusion():
    await rs.collect_rank_daily(
        _day_client("2026-10-30", indiv=[("111111", 5)], toss_amt=[("111111", 5)], mkt_amt=[("111111", 5)]),
        now=_DAY1)
    c2 = _day_client(
        "2026-11-02",
        indiv=[("111111", 3), ("222222", 2), ("333333", 4)],
        toss_amt=[("111111", 3), ("222222", 2), ("333333", 4)],
        mkt_amt=[("222222", 1)],
        changes={"333333": "0.12"},     # +12% 추격 → 제외
    )
    stats = await rs.collect_rank_daily(c2, now=_DAY2)
    sigs = await _rank_signals_in_db()
    by = {(s.source, s.ticker): s for s in sigs}
    # 새 진입 222222 → 개인 관심 칸 2종 + 전일 칸 1종
    assert ("rank_individual_netbuy", "222222") in by
    assert ("rank_toss_amount", "222222") in by
    assert ("rank_market_amount", "222222") in by
    # 이미 있던 111111 은 5위→3위 (2계단) 이라 신호 아님
    assert not [k for k in by if k[1] == "111111"]
    # 333333: 추격 제외
    assert not [k for k in by if k[1] == "333333"]
    assert stats["signals"]["toss_amount"]["excluded_chase"] == 1
    assert by[("rank_toss_amount", "222222")].trade_date == "2026-11-03"    # 다음 거래일
    assert by[("rank_toss_amount", "222222")].intensity == rs.rank_intensity(2, None)


@pytest.mark.asyncio
async def test_individual_change_rate_filled_from_other_rankings_then_prices_candles():
    await rs.collect_rank_daily(
        _day_client("2026-10-30", indiv=[("111111", 5)], toss_amt=[("111111", 5)]), now=_DAY1)
    c2 = _day_client(
        "2026-11-02",
        indiv=[("222222", 2), ("444444", 3), ("555555", 4)],
        toss_amt=[("222222", 1)],              # 222222 는 다른 순위에 등락률 있음 (0.02)
        mkt_amt=[],
    )
    c2._prices = {"444444": 1200, "555555": 1300}
    c2._candles = {
        # 최신순 · 오늘(11-02) 봉은 건너뛰고 전일 종가 1000 기준 → 444444 +20% (추격 제외) · 555555 +1.5%
        "444444": [{"timestamp": "2026-11-02T00:00:00+09:00", "closePrice": "1200"},
                   {"timestamp": "2026-10-30T00:00:00+09:00", "closePrice": "1000"}],
        "555555": [{"timestamp": "2026-11-02T00:00:00+09:00", "closePrice": "1300"},
                   {"timestamp": "2026-10-30T00:00:00+09:00", "closePrice": "1280"}],
    }
    await rs.collect_rank_daily(c2, now=_DAY2)
    sigs = await _rank_signals_in_db()
    tickers = {(s.source, s.ticker) for s in sigs}
    assert ("rank_individual_netbuy", "222222") in tickers
    assert ("rank_individual_netbuy", "555555") in tickers
    assert ("rank_individual_netbuy", "444444") not in tickers
    # 시세 조회는 등락률을 모르는 새 진입 종목만 (222222 는 조회 안 함)
    price_calls = [c for c in c2.calls if c[0] == "prices"]
    assert price_calls and set(price_calls[0][1]) == {"444444", "555555"}


@pytest.mark.asyncio
async def test_no_data_when_ranked_at_missing_or_not_today():
    iso_old = "2026-10-29T20:30:00+09:00"
    c = FakeToss(
        investor=_investor(None, []),                                      # rankedAt null
        daily={"TOSS_SECURITIES_TRADING_AMOUNT": _ranking(iso_old, [("005930", 1, "0.01")])},   # 어제 값
    )
    stats = await rs.collect_rank_daily(c, now=_DAY1)
    assert stats["kinds"]["individual_netbuy"]["state"] == "no_data"
    assert stats["kinds"]["toss_amount"]["state"] == "no_data"
    async with get_session() as session:
        assert (await session.execute(select(WatchlistRankDaily))).scalars().all() == []
    assert rs.read_status()["daily"]["kinds"]["toss_amount"]["state"] == "no_data"


@pytest.mark.asyncio
async def test_realtime_accumulates_best_rank_and_substitutes_when_daily_missing():
    # 1일차: 20:30 정상 저장 (비교 기준)
    await rs.collect_rank_daily(
        _day_client("2026-10-30", indiv=[("111111", 5)], toss_amt=[("111111", 5)]), now=_DAY1)

    # 2일차 장중: 매시 조회 · 순위가 오르내림 → 그날 최고(작은 숫자)만 남는다
    def _rt(rows):
        return FakeToss(realtime={"TOSS_SECURITIES_TRADING_AMOUNT": _ranking(None, rows)})

    t = datetime(2026, 11, 2, 9, 5, tzinfo=_KST)
    await rs.collect_rank_realtime(_rt([("222222", 30, "0.03")]), now=t)
    await rs.collect_rank_realtime(_rt([("222222", 7, "0.04")]), now=t + timedelta(hours=1))
    await rs.collect_rank_realtime(_rt([("222222", 50, "0.05")]), now=t + timedelta(hours=2))
    async with get_session() as session:
        rows = (await session.execute(select(WatchlistRankDaily).where(
            WatchlistRankDaily.kind == "toss_amount_rt"))).scalars().all()
    assert len(rows) == 1 and rows[0].rank == 7

    # 20:30 에 토스증권 체결은 집계 없음 → 장중 누적(_rt)을 대신 쓴다 · 개인 순매수는 대체 없음
    c = FakeToss(investor=_investor(None, []), daily={})
    stats = await rs.collect_rank_daily(c, now=_DAY2)
    assert stats["kinds"]["toss_amount"]["state"] == "no_data"
    sigs = await _rank_signals_in_db()
    got = [s for s in sigs if s.source == "rank_toss_amount" and s.ticker == "222222"]
    assert len(got) == 1 and got[0].intensity == rs.rank_intensity(7, None)
    assert not [s for s in sigs if s.source == "rank_individual_netbuy"]


@pytest.mark.asyncio
async def test_realtime_skips_stale_ranked_at_on_holiday():
    stale = _ranking("2026-10-29T15:30:00+09:00", [("222222", 3, "0.01")])
    c = FakeToss(realtime={"TOSS_SECURITIES_TRADING_AMOUNT": stale})
    out = await rs.collect_rank_realtime(c, now=datetime(2026, 11, 2, 9, 5, tzinfo=_KST))
    assert out["changed"] == 0


@pytest.mark.asyncio
async def test_rank_signal_job_is_idempotent():
    await rs.collect_rank_daily(
        _day_client("2026-10-30", indiv=[("111111", 5)], toss_amt=[("111111", 5)]), now=_DAY1)
    c2 = _day_client("2026-11-02", indiv=[("222222", 2)], toss_amt=[("222222", 2)])
    await rs.collect_rank_daily(c2, now=_DAY2)
    await rs.collect_rank_daily(c2, now=_DAY2 + timedelta(minutes=10))
    sigs = [s for s in await _rank_signals_in_db() if s.source == "rank_toss_amount"]
    assert len(sigs) == 1


@pytest.mark.asyncio
async def test_chase_threshold_follows_params(monkeypatch):
    from backend.discovery.live_tape import params as params_mod

    p = SniperParams()
    p.watchlist_chase_max_change_pct = 1.0     # 1% 로 낮추면 2% 종목도 추격으로 제외
    monkeypatch.setattr(params_mod, "get_sniper_params", lambda: p)
    await rs.collect_rank_daily(
        _day_client("2026-10-30", indiv=[("111111", 5)], toss_amt=[("111111", 5)]), now=_DAY1)
    c2 = _day_client("2026-11-02", indiv=[("222222", 2)], toss_amt=[("222222", 2)])
    await rs.collect_rank_daily(c2, now=_DAY2)
    assert await _rank_signals_in_db() == []


# ═══════════════════════════════════════════════════════════════
# P4b · DART 공시
# ═══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("title,expected", [
    ("단일판매ㆍ공급계약체결", "dart_disclosure"),
    ("[기재정정]단일판매ㆍ공급계약체결", None),
    ("임상시험계획 승인", "dart_disclosure"),
    ("품목허가 신청", "dart_disclosure"),
    ("최대주주 변경을 수반하는 주식 양수도 계약", "dart_disclosure"),
    ("자기주식 취득 결정", "dart_disclosure"),
    ("무상증자 결정", "dart_disclosure"),
    ("유상증자 결정", "dart_caution"),
    ("전환사채권 발행결정", "dart_caution"),
    ("신주인수권부사채권 발행결정", "dart_caution"),
    ("감자 결정", "dart_caution"),
    ("횡령ㆍ배임 혐의 발생", "dart_caution"),
    ("감사의견 거절", "dart_caution"),
    ("[기재정정]유상증자 결정", "dart_caution"),       # 정정이어도 주의는 유지
    ("주주총회 소집 결의", None),
    ("무상증자 결정 및 유상증자 병행", "dart_caution"),  # 둘 다면 제외가 이긴다
])
def test_dart_classify(title, expected):
    assert dart_events.classify(title) == expected


@pytest.mark.asyncio
async def test_collect_dart_events_reads_stored_events_without_calling_dart():
    now = datetime(2026, 10, 30, 11, 20, tzinfo=timezone.utc)      # 20:20 KST → 곧 20:40 잡과 같은 날
    async with get_session() as session:
        for ticker, label, eid, days in [
            ("005930", "단일판매ㆍ공급계약체결", "20261030000001", 0),
            ("000660", "유상증자 결정", "20261030000002", 0),
            ("035420", "주주총회소집공고", "20261030000003", 0),
            ("068270", "임상시험계획 승인", "20261020000004", 10),    # 오래됨 → 읽지 않음
        ]:
            session.add(MemeCatalystEvent(
                ticker=ticker, source="dart", event_type="B", event_label=label,
                occurred_at=datetime(2026, 10, 30) - timedelta(days=days), event_id=eid, payload="{}"))
    stats = await dart_events.collect_dart_events(now=now)
    assert stats["disclosure"] == 1 and stats["caution"] == 1
    rows = await _rank_signals_in_db()
    by = {r.ticker: r for r in rows}
    assert by["005930"].source == "dart_disclosure" and by["005930"].intensity == 1.0
    assert by["000660"].source == "dart_caution" and by["000660"].intensity == 0.0
    assert "035420" not in by and "068270" not in by
    again = await dart_events.collect_dart_events(now=now + timedelta(minutes=20))
    assert again["disclosure"] == 0 and again["caution"] == 0       # 재실행해도 중복 없음


@pytest.mark.asyncio
async def test_two_disclosures_same_ticker_both_saved():
    now = datetime(2026, 10, 30, 11, 20, tzinfo=timezone.utc)
    async with get_session() as session:
        for eid, label in (("20261030000010", "단일판매ㆍ공급계약체결"), ("20261030000011", "자기주식 취득 결정")):
            session.add(MemeCatalystEvent(ticker="005930", source="dart", event_type="B", event_label=label,
                                          occurred_at=datetime(2026, 10, 30), event_id=eid, payload="{}"))
    stats = await dart_events.collect_dart_events(now=now)
    assert stats["disclosure"] == 2


# ═══════════════════════════════════════════════════════════════
# 화면용 근거 · finalize · /sources
# ═══════════════════════════════════════════════════════════════
def test_build_evidence_shape():
    sigs = [
        {"ticker": "A", "source": "news_mk", "intensity": 1.0, "detected_at": "2026-10-30T01:00:00",
         "payload": {"title": "기사1", "url": "u1", "published": "p"}},
        {"ticker": "A", "source": "news_yna_market", "intensity": 0.5, "detected_at": "2026-10-30T02:00:00",
         "payload": {"title": "기사2", "url": "u2"}},
        {"ticker": "A", "source": "news_mk", "intensity": 1.0, "detected_at": "2026-10-30T03:00:00",
         "payload": {"title": "기사3", "url": "u3"}},
        {"ticker": "A", "source": "news_mk", "intensity": 1.0, "detected_at": "2026-10-30T04:00:00",
         "payload": {"title": "기사4", "url": "u4"}},
        {"ticker": "A", "source": "rank_individual_netbuy", "intensity": 0.9, "detected_at": "x",
         "payload": {"rank": 3, "prev_rank": None, "is_new": True, "change_rate": 0.0123}},
        {"ticker": "A", "source": "dart_disclosure", "intensity": 1.0, "detected_at": "x",
         "payload": {"title": "단일판매ㆍ공급계약체결"}},
        {"ticker": "A", "source": "dart_caution", "intensity": 0.0, "detected_at": "x",
         "payload": {"title": "유상증자 결정"}},
    ]
    ev = build_evidence(sigs)
    assert ev["news"]["count"] == 4 and ev["news"]["publishers"] == 2
    assert len(ev["news"]["articles"]) == 3
    assert [a["title"] for a in ev["news"]["articles"]][0] == "기사4"       # 같은 가중이면 최근 먼저
    assert ev["interest"] == [{
        "source": "rank_individual_netbuy", "label": "개인 순매수", "rank": 3, "prev_rank": None,
        "is_new": True, "change_rate_pct": 1.23}]
    assert ev["event"] == [{"source": "dart_disclosure", "title": "단일판매ㆍ공급계약체결"}]
    assert ev["caution"] == [{"title": "유상증자 결정"}]
    assert ev["youtube"] == {"count": 0, "videos": []} and ev["prev_day"] == []


@pytest.mark.asyncio
async def test_finalize_writes_evidence_version_and_skips_zero_score(monkeypatch):
    from backend.discovery.watchlist import finalize as fin

    m = _matcher()
    m._loaded_at = datetime.now(tz=timezone.utc)
    monkeypatch.setattr(fin, "get_matcher", lambda: m)
    monkeypatch.setattr(fin, "dart_names", lambda: {})
    td = "2026-10-30"
    await upsert_signal(ticker="005930", source="news_mk", signal_type="headline", intensity=1.0,
                        trade_date=td, payload={"title": "삼성전자 호재", "url": "https://x/1"})
    await upsert_signal(ticker="005930", source="dart_caution", signal_type="disc_1", intensity=0.0,
                        trade_date=td, payload={"title": "유상증자 결정"})
    await upsert_signal(ticker="000660", source="dart_caution", signal_type="disc_2", intensity=0.0,
                        trade_date=td, payload={"title": "감자 결정"})        # 주의 공시만 → 목록에 안 오름
    stats = await finalize_watchlist(trade_date=td)
    assert stats["written"] == 1
    items = await list_watchlist(td)
    assert [i["ticker"] for i in items] == ["005930"]
    it = items[0]
    assert it["score_version"] == "watchlist-v2-2026-10-30"
    assert it["evidence"]["caution"] == [{"title": "유상증자 결정"}]
    assert it["evidence"]["news"]["articles"][0]["title"] == "삼성전자 호재"
    assert not any(k.startswith("_") for k in it["source_breakdown"])      # 옛 화면 호환
    assert 0.0 <= it["composite_score"] <= 1.0


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_sources_has_interest_and_prev_day_lines_and_rank_state(client, monkeypatch):
    monkeypatch.setenv("TOSS_CLIENT_ID", "dummy-id-not-real")
    monkeypatch.setenv("TOSS_CLIENT_SECRET", "dummy-secret-not-real")
    from backend.services import config as cfg
    monkeypatch.setattr(cfg, "get", lambda name, default=None: os.environ.get(name, default))

    body = (await client.get("/api/v1/watchlist/sources")).json()
    by = {s["key"]: s for s in body["sources"]}
    assert set(by) == {"news", "board", "youtube", "event", "prev_day"}
    assert by["board"]["label"] == "개인 관심" and by["prev_day"]["label"] == "전일"
    assert "아직 저장 전" in by["board"]["note"]
    assert body["score_version"] == "watchlist-v2-2026-10-30"

    # 20:30 집계 없음 상태가 화면에 말로 나온다
    c = FakeToss(investor=_investor(None, []), daily={})
    await rs.collect_rank_daily(c, now=_DAY1)
    body = (await client.get("/api/v1/watchlist/sources")).json()
    by = {s["key"]: s for s in body["sources"]}
    assert "집계 없음" in by["board"]["note"] and by["board"]["last_saved_at"]
    assert "dummy-" not in str(body)          # 키 값은 나가지 않는다


@pytest.mark.asyncio
async def test_sources_event_collecting_with_only_dart_key(client, monkeypatch):
    monkeypatch.delenv("ASSEMBLY_API_KEY", raising=False)
    monkeypatch.delenv("GOV_RSS_SOURCES", raising=False)
    monkeypatch.setenv("DART_API_KEY", "dummy-dart-not-real-123")
    body = (await client.get("/api/v1/watchlist/sources")).json()
    by = {s["key"]: s for s in body["sources"]}
    assert by["event"]["collecting"] is True
    assert "dummy-dart" not in str(body)


@pytest.mark.asyncio
async def test_watchlist_response_contains_evidence_keys(client, monkeypatch):
    from backend.discovery.watchlist import finalize as fin

    m = _matcher()
    m._loaded_at = datetime.now(tz=timezone.utc)
    monkeypatch.setattr(fin, "get_matcher", lambda: m)
    td = "2026-10-30"
    await upsert_signal(ticker="005930", source="news_mk", signal_type="headline", intensity=1.0,
                        trade_date=td, payload={"title": "기사", "url": "https://x/1"})
    await finalize_watchlist(trade_date=td)
    body = (await client.get("/api/v1/watchlist", params={"trade_date": td})).json()
    ev = body["items"][0]["evidence"]
    assert set(ev) == {"news", "interest", "youtube", "event", "caution", "prev_day"}
    assert body["items"][0]["score_version"] == "watchlist-v2-2026-10-30"
