"""WP90-2 · 시점별 주식수 (제출일 ≤ 리밸런싱일 · 가장 최근 제출 공시 · 같은 공시 안 합산) · 미래 공시 사용 금지."""
from __future__ import annotations

from backend.scripts.biotech_h6_obesity_mcap import shares_pit


def _facts(items):
    return {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": items}}}}}


def test_point_in_time_latest_filing_summed_no_future():
    f = _facts([
        {"val": 100, "end": "2020-01-31", "filed": "2020-02-10", "accn": "A1"},
        {"val": 70, "end": "2020-04-30", "filed": "2020-05-08", "accn": "A2"},     # 종류 1
        {"val": 30, "end": "2020-04-30", "filed": "2020-05-08", "accn": "A2"},     # 종류 2 → 합산
        {"val": 999, "end": "2020-07-31", "filed": "2020-08-07", "accn": "A3"},    # 리밸런싱일 이후 제출 → 쓰면 안 됨
    ])
    got = shares_pit(f, "2020-07-01")
    assert got["shares"] == 100 and got["accn"] == "A2" and got["n_values"] == 2
    assert shares_pit(f, "2020-01-01") is None                                    # 그 전 공시 없음 = unknown
    assert shares_pit({"facts": {}}, "2020-07-01") is None                        # dei 없음 = unknown
