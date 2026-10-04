"""P3a ① · 가격 기록 보관 400일 · 백필 380일 · 12개월 기록 대상 규칙 · 하루 50 상한 · XBI 포함 · 멈춘 종목 제외 유지."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from backend.scripts import _biotech_paths as _P
from backend.scripts import biotech_mcap_daily as mc

KST = timezone(timedelta(hours=9))
KEY = "tk-test-" + "z" * 30
TODAY = date(2026, 10, 5)


class _R:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


def _rt(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)


def _bars(first_days_ago: int, last_days_ago: int = 0):
    fields = mc.fetch_one.__globals__["TIINGO_FIELDS"]
    return [{**{f: 1 for f in fields}, "date": (TODAY - timedelta(days=i)).isoformat(), "close": 10.0}
            for i in range(last_days_ago, first_days_ago + 1)]


def _hist(tk: str, first_days_ago: int) -> dict:
    return {(tk, (TODAY - timedelta(days=i)).isoformat()): 1.0 for i in range(0, first_days_ago + 1)}


def _clock(hour: int = 7):
    t0 = datetime(2026, 10, 5, hour, 0, tzinfo=KST)
    tick = {"n": 0}

    def now():
        tick["n"] += 1
        return t0 + timedelta(seconds=tick["n"])
    return now


def test_constants():
    assert mc.HISTORY_KEEP_DAYS >= 400 and mc.BACKFILL_DAYS == 380 and mc.BACKFILL_MAX == 50 and mc.YEAR_DAYS == 365


def test_history_keeps_400_days(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    keep = (TODAY - timedelta(days=mc.HISTORY_KEEP_DAYS)).isoformat()
    drop = (TODAY - timedelta(days=mc.HISTORY_KEEP_DAYS + 1)).isoformat()
    year = (TODAY - timedelta(days=370)).isoformat()
    n = mc.save_history({("AAA", keep): 1.0, ("AAA", drop): 2.0, ("AAA", year): 3.0}, TODAY)
    assert n == 1 and set(mc.load_history()) == {("AAA", keep), ("AAA", year)}


def test_target_rule_365_days():
    # 90일 창은 덮지만 기록 시작이 오늘−100일 → 12개월 규칙으로 대상 (P2 · 서버 기록이 2026-06-26 부터인 상태)
    h = {**_hist("SHORT", 100), **_hist("FULL", 370), **_hist("EDGE", 365)}
    assert mc.needs_backfill(h, ["SHORT", "FULL", "EDGE", "NONE"], TODAY) == ["SHORT", "NONE"]


def test_target_rule_short_listing_not_repeated():
    # Tiingo 첫 거래일까지 이미 받은 종목 (상장 1년 미만) 은 다시 대상이 되지 않음
    h = _hist("IPO", 200)
    first = (TODAY - timedelta(days=200)).isoformat()
    assert mc.needs_backfill(h, ["IPO"], TODAY) == ["IPO"]
    assert mc.needs_backfill(h, ["IPO"], TODAY, short={"IPO": first}) == []


def test_backfill_380_days_and_cap_50(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    starts = []

    def get(url, params=None, headers=None):
        starts.append((params or {}).get("startDate"))
        return _R(200, _bars(375))

    tickers = [f"T{i:02d}" for i in range(79)] + [mc.BENCH]
    res = mc.backfill_prices(tickers, KEY, get, TODAY, now=_clock())
    assert res["requests"] == 50 and res["remaining"] == 30                       # 하루 50 상한 · 남은 30 은 다음 날
    assert set(starts) == {(TODAY - timedelta(days=380)).isoformat()}             # 380일 기간 요청
    res2 = mc.backfill_prices(tickers, KEY, get, TODAY, now=_clock(hour=9))      # 시간당 50 장부 · 다른 시간
    assert res2["requests"] == 30 and res2["remaining"] == 0                      # 이틀째 완료 (XBI 포함)
    assert any(k[0] == mc.BENCH for k in mc.load_history())


def test_backfill_short_listing_requested_once(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    calls = []
    get = lambda *a, **k: calls.append(1) or _R(200, _bars(150))                  # noqa: E731 · 첫 거래일 150일 전
    mc.backfill_prices(["IPO"], KEY, get, TODAY, now=_clock())
    res2 = mc.backfill_prices(["IPO"], KEY, get, TODAY, now=_clock())
    assert len(calls) == 1 and res2["requests"] == 0 and res2["remaining"] == 0


def test_stale_ticker_still_skipped(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    calls = []
    get = lambda *a, **k: calls.append(1) or _R(200, _bars(375, last_days_ago=30))   # noqa: E731 · 30일 전 멈춤 (APGE · FBRX 유형)
    mc.backfill_prices(["APGE"], KEY, get, TODAY, now=_clock())
    res2 = mc.backfill_prices(["APGE"], KEY, get, TODAY, now=_clock())
    assert len(calls) == 1 and res2["requests"] == 0


def test_run_includes_xbi_in_backfill(tmp_path, monkeypatch):
    _rt(tmp_path, monkeypatch)
    monkeypatch.setenv(mc.FLAG, "1")
    monkeypatch.setenv("TIINGO_API_KEY", KEY)
    monkeypatch.setattr(mc, "load_candidates", lambda: {"AAA": "1"})
    monkeypatch.setattr(mc, "_latest_json", lambda prefix: {"shares": {}})
    monkeypatch.setattr(mc, "daily_prices", lambda *a, **k: {"requests": 1, "blocked": None, "failed": {}, "prices": {},
                                                             "hidden": {}, "last_us_trading_day": None,
                                                             "monthly_unique_used": 0, "new_symbols": 0})
    seen = {}
    monkeypatch.setattr(mc, "backfill_prices", lambda tickers, *a, **k: seen.setdefault("t", tickers) and {"requests": 0})
    mc.run("daily", get_tiingo=lambda *a, **k: None, today=TODAY)
    assert seen["t"] == ["AAA", "XBI"]
