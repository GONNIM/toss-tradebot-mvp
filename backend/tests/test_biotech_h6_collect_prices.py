"""H6 가격 수집 · 429 즉시 중단 · 월 배분 · 키 헤더 전용 · 커버율."""
from __future__ import annotations

from datetime import date

from backend.scripts import biotech_h6_collect_prices as h6

KEY = "tk-test-" + "z" * 30


class _R:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


def _bars(n=5, drop=None):
    out = []
    for i in range(n):
        b = {f: 1 for f in h6.TIINGO_FIELDS}
        b["date"] = f"2026-09-{i + 21:02d}T00:00:00.000Z"
        if drop:
            b.pop(drop)
        out.append(b)
    return out


def test_stops_on_429_and_key_only_in_header(tmp_path, monkeypatch):
    monkeypatch.setattr(h6._P, "RUNTIME_DIR", tmp_path)
    seen = []

    def get(url, params=None, headers=None):
        seen.append((url, params, headers))
        return _R(429) if "BBB" in url else _R(200, _bars())

    res = h6.run(["AAA", "BBB", "CCC"], KEY, get, date(2026, 10, 1), sleep=lambda s: None)
    assert res["success"] == 1 and res["failed"] == {"BBB": "blocked"} and res["not_attempted"] == ["CCC"]
    assert all(KEY not in u and KEY not in str(p) for u, p, _ in seen)
    assert all(hdr["Authorization"] == f"Token {KEY}" for _, _, hdr in seen)


def test_monthly_allocation_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(h6._P, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(h6, "MONTHLY_ALLOCATION", 2)
    res = h6.run(["A", "B", "C"], KEY, lambda *a, **k: _R(200, _bars()), date(2026, 10, 1), sleep=lambda s: None)
    assert res["success"] == 2 and res["failed"] == {"C": "monthly_allocation_reached"} and res["monthly_remaining"] == 0


def test_coverage_denominator_is_union_of_dates():
    bars = {"A": [{"date": "2026-09-28"}, {"date": "2026-09-29"}], "B": [{"date": "2026-09-29"}, {"date": "2026-09-30"}], "C": []}
    cov = h6.coverage(bars, ["A", "B", "C"])
    assert cov["ticker_coverage"] == "2/3" and cov["distinct_trading_dates"] == 3
    assert cov["trading_day_coverage_by_ticker"]["A"] == round(2 / 3, 4)
    assert cov["trading_day_coverage_pct"] == round(4 / 9 * 100, 1)


def test_all_tiingo_fields_saved_and_missing_field_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(h6._P, "RUNTIME_DIR", tmp_path)
    ok = h6.run(["A"], KEY, lambda *a, **k: _R(200, _bars()), date(2026, 10, 1), sleep=lambda s: None)
    assert set(h6.TIINGO_FIELDS) <= set(ok["bars"]["A"][0]) and ok["bars"]["A"][0]["date"] == "2026-09-21"
    bad = h6.run(["B"], KEY, lambda *a, **k: _R(200, _bars(drop="adjVolume")), date(2026, 10, 1), sleep=lambda s: None)
    assert bad["success"] == 0 and bad["failed"] == {"B": "missing_fields:adjVolume"}


def test_targets_file_has_59():
    assert len(h6.load_targets()) == 59


def test_hourly_limit_50_stops_and_logs_next_time(tmp_path, monkeypatch, caplog):
    """2026-10-01 · 시간당 50회 · 장부에 요청 시각 기록 · 50회째 뒤 멈춤 · 다음 가능 시각 = 첫 요청 + 60분."""
    import logging
    from datetime import datetime, timedelta, timezone
    monkeypatch.setattr(h6._P, "RUNTIME_DIR", tmp_path)
    caplog.set_level(logging.WARNING)
    t0 = datetime(2026, 10, 1, 9, 51, tzinfo=timezone(timedelta(hours=9)))
    clock = {"n": 0}

    def now():
        clock["n"] += 1
        return t0 + timedelta(seconds=clock["n"])

    calls = []
    res = h6.run([f"T{i}" for i in range(55)], KEY, lambda *a, **k: calls.append(1) or _R(200, _bars()),
                 date(2026, 10, 1), sleep=lambda s: None, now=now)
    assert len(calls) == 50 and res["requests"] == 50 and res["blocked"].startswith("hourly_limit · next 2026-10-01 10:51")
    assert "시간당 한도 50회 · 다음 가능 시각 2026-10-01 10:51" in caplog.text
    usage = h6.load_usage("202610")
    assert usage["hourly"] == {"2026-10-01T09": {"H6": 50}} and len(usage["recent_requests"]) == 50
    # 한 시간 뒤에는 다시 가능
    later = h6.run(["T50"], KEY, lambda *a, **k: _R(200, _bars()), date(2026, 10, 1), sleep=lambda s: None,
                   now=lambda: t0 + timedelta(minutes=61))
    assert later["requests"] == 1 and later["blocked"] is None


def test_alias_glmd_to_eocn_and_first_bar_date():
    assert "EOCN" in h6.load_targets() and "GLMD" not in h6.load_targets()
    bars = {"A": [{"date": "2020-01-03"}, {"date": "2019-05-01"}]}
    assert h6.first_bar_dates(bars, ["A", "B"]) == {"A": "2019-05-01", "B": None}
