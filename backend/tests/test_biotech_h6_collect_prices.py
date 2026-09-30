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


def _bars(n=5):
    return [{"date": f"2026-09-{i + 21:02d}T00:00:00.000Z", "open": 1, "high": 1, "low": 1, "close": 1, "adjClose": 1, "volume": 1}
            for i in range(n)]


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


def test_not_found_and_coverage():
    bars = {"A": [{"date": "2026-09-28"}, {"date": "2026-09-29"}], "B": []}
    cov = h6.coverage(bars, ["A", "B"])
    assert cov["ticker_coverage"] == "1/2" and cov["trading_day_coverage_by_ticker"]["A"] == 1.0


def test_targets_file_has_59():
    assert len(h6.load_targets()) == 59
