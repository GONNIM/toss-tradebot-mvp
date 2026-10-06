"""P4-0 (PRD 20절 · FR-6c 봉인 설계 5절 87~92행) · 주간 주식수 단계가 dei 주식수 전체 이력을 저장 (요청 0).

5절 89행의 두 처리를 이력 저장 단계에서 확인한다: 같은 end · 같은 공시 (accn) 안의 값은 합산 · 같은 end 를 여러 공시가
보고하면 가장 최근 제출 (filed) 공시 하나만.
"""
from __future__ import annotations

import json
from datetime import date

from backend.scripts import biotech_mcap_daily as mc

TODAY = date(2026, 10, 12)


def _facts(items):
    return {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": items}}}}}


def _i(end, val, accn, filed):
    return {"end": end, "val": val, "accn": accn, "filed": filed, "form": "10-Q"}


ITEMS = [
    _i("2025-11-05", 100, "A1", "2025-11-07"),
    _i("2026-02-20", 70, "B1", "2026-03-01"), _i("2026-02-20", 30, "B1", "2026-03-01"),   # 같은 공시 · 주식 종류 둘 → 합산 100
    _i("2026-05-04", 120, "C1", "2026-05-06"), _i("2026-05-04", 125, "C2", "2026-06-10"), # 같은 end · 정정 공시 → 최근 제출 C2
]


def test_history_same_accn_summed():
    h = {p["end"]: p for p in mc.dei_shares_history(_facts(ITEMS))}
    assert h["2026-02-20"]["shares"] == 100 and h["2026-02-20"]["n_values"] == 2 and h["2026-02-20"]["accn"] == "B1"


def test_history_latest_filed_accn_only():
    h = {p["end"]: p for p in mc.dei_shares_history(_facts(ITEMS))}
    assert h["2026-05-04"]["shares"] == 125 and h["2026-05-04"]["accn"] == "C2" and h["2026-05-04"]["filed"] == "2026-06-10"


def test_history_sorted_and_same_rule_as_dei_shares():
    hist = mc.dei_shares_history(_facts(ITEMS))
    assert [p["end"] for p in hist] == ["2025-11-05", "2026-02-20", "2026-05-04"]
    for p in hist:                                        # 이력의 각 end 값 = 그 날짜 기준 dei_shares() 값 (같은 함수)
        d = mc.dei_shares(_facts(ITEMS), p["end"])
        assert (d["asof"], d["shares"], d["accn"], d["n_values"]) == (p["end"], p["shares"], p["accn"], p["n_values"])


def test_history_empty_without_dei():
    assert mc.dei_shares_history({"facts": {"us-gaap": {}}}) == []


def test_weekly_saves_history_without_extra_requests_and_keeps_old(tmp_path, monkeypatch):
    monkeypatch.setattr(mc._P, "RUNTIME_DIR", tmp_path)
    monkeypatch.setenv(mc.FLAG, "1")
    (tmp_path / "candidates").mkdir()
    (tmp_path / "candidates" / "biotech_candidates_20261012.csv").write_text("ticker,cik\nAAA,1\nBBB,2\n")
    (tmp_path / "mcap").mkdir(exist_ok=True)
    mc.shares_history_path().write_text(json.dumps({"rows": {"OLD": {"cik": "9", "points": [], "fetched": "2026-10-05"}}}))
    fin = tmp_path / "f.json"

    def fake_save_finance(rows, today):
        fin.write_text(json.dumps({"rows": rows}))
        return fin

    monkeypatch.setattr(mc, "save_finance", fake_save_finance)
    calls = []

    def get(url):
        calls.append(url)
        return {"status": 200, "json": _facts(ITEMS)}

    res = mc.run("weekly", get_sec=get, today=TODAY, ledger=mc.SecDailyLedger.load("20261012", base=tmp_path))
    assert res["requests"] == 2 == len(calls)                                 # 종목당 1건 그대로 (이력 저장으로 늘지 않음)
    rows = json.loads(mc.shares_history_path().read_text())["rows"]
    assert set(rows) == {"AAA", "BBB", "OLD"} and rows["OLD"]["fetched"] == "2026-10-05"
    assert rows["AAA"]["fetched"] == "2026-10-12" and [p["end"] for p in rows["AAA"]["points"]] == ["2025-11-05", "2026-02-20", "2026-05-04"]
    assert rows["AAA"]["points"][2]["shares"] == 125
