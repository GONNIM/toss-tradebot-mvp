"""P3a-3 (PRD v0.7 13절) · ① 5B 초과 제외 격일 복귀 방지 · ② 15개월 창 · ③ 차입금 0 → 미확인 · ④ 합계 항목 범위 표시.

수치는 P2 에서 받은 companyfacts 원본 (CIK0001785530 HOWL · CIK0001680581 FULC · CIK0001650664 EDIT · CIK0001703057 ABCL)
의 값을 인용했다 (새 SEC 요청 0).
"""
from __future__ import annotations

import csv
import json
from datetime import date

from backend.scripts import biotech_filings as bf
from backend.scripts import biotech_h48v3_candidates as hc
from backend.scripts import biotech_mcap_daily as mc

QE = "2026-06-30"
C = bf.CASH_TAG


def _i(val, end=QE, form="10-Q", filed="2026-08-05") -> dict:
    return {"end": end, "val": val, "form": form, "filed": filed, "accn": "x"}


def _facts(tags: dict) -> dict:
    return {"facts": {"us-gaap": {k: {"units": {"USD": v}} for k, v in tags.items()}, "dei": {}}}


# ── ② 15개월 창 ──────────────────────────────────────────────────────


def test_window_lo_is_15_months_before_quarter_end():
    assert bf._window_lo("2026-06-30") == date(2025, 3, 30)
    assert bf._in_window("2025-03-31", QE) and not bf._in_window("2025-03-29", QE)


def test_investment_old_values_only_is_none():
    """KOD 유형 · 투자자산 태그가 2019~2023 에만 있음 → "투자자산 항목 없음 · 현금만"."""
    f = _facts({C: [_i(125903000)], "MarketableSecuritiesCurrent": [_i(0, end="2023-12-31", form="10-K")],
                "AvailableForSaleSecuritiesDebtSecuritiesCurrent": [_i(104576000, end="2023-03-31")],
                "AvailableForSaleSecuritiesDebtSecurities": [_i(23571000, end="2019-09-30")]})
    ci = bf.extract_finance(f)["cash_inv"]
    assert ci["val"] == 125903000 and ci["note"] == bf.INV_NONE and len(ci["dropped"]) == 3


def test_kod_zero_only_in_window_is_none():
    """P3a-3 ⑦ · KOD · 창 안 값이 MarketableSecurities 2025-12-31 = 0 뿐 → "투자자산 항목 없음 · 현금만"."""
    f = _facts({C: [_i(125903000)], "MarketableSecuritiesCurrent": [_i(0, end="2023-12-31", form="10-K")],
                "AvailableForSaleSecuritiesDebtSecuritiesCurrent": [_i(104576000, end="2023-03-31")],
                "MarketableSecurities": [_i(0, end="2024-12-31", form="10-K"), _i(0, end="2025-12-31", form="10-K")]})
    ci = bf.extract_finance(f)["cash_inv"]
    assert ci["val"] == 125903000 and ci["note"] == "투자자산 항목 없음 · 현금만"


def test_debt_zero_only_in_window_is_ladder_none():
    f = _facts({C: [_i(1)], "LongTermDebtNoncurrent": [_i(0, end="2025-12-31", form="10-K")]})
    assert bf.extract_finance(f)["debt"]["reason"] == "사다리 항목 없음"


def test_investment_recent_dropped_keeps_mismatch():
    f = _facts({C: [_i(18738000)], bf.INV_SHORT_SUM: [_i(3500000, end="2025-09-30")]})      # AGEN 유형
    assert bf.extract_finance(f)["cash_inv"]["note"] == bf.INV_MISMATCH


def test_debt_abcl_2020_only_is_ladder_none():
    f = _facts({C: [_i(120065000)], "LongTermDebtCurrent": [_i(1, end="2020-12-31", form="10-K")]})
    d = bf.extract_finance(f)["debt"]
    assert d["val"] is None and d["label"] == "차입금 미확인" and d["reason"] == "사다리 항목 없음"


def test_debt_recent_dropped_keeps_mismatch():
    f = _facts({C: [_i(1)], "LongTermDebtNoncurrent": [_i(5, end="2025-12-31", form="10-K")]})
    assert bf.extract_finance(f)["debt"]["reason"] == "차입금 기준일 불일치"


# ── ③ 차입금 0 → 미확인 ──────────────────────────────────────────────


HOWL = _facts({C: [_i(21987000, filed="2026-07-31")],
               "LongTermDebt": [_i(32085000, end="2026-03-31", filed="2026-05-07")],
               "NotesPayableCurrent": [_i(0, filed="2026-07-31")]})


def test_debt_howl_zero_with_recent_nonzero_is_unconfirmed():
    d = bf.extract_finance(HOWL)["debt"]
    assert d["val"] is None and d["reason"] == "최근 분기 태그 불일치"
    assert d["label"] == "차입금 미확인 · 최근 분기 태그 불일치(직전 값 32,085,000 · 2026-03-31)"
    assert d["prior"]["tag"] == "LongTermDebt" and [x["tag"] for x in d["zero_items"]] == ["NotesPayableCurrent"]


def test_debt_zero_without_recent_nonzero_stays_zero():
    f = _facts({C: [_i(1)], "LongTermDebt": [_i(32085000, end="2024-12-31", form="10-K")],
                "NotesPayableCurrent": [_i(0)]})
    d = bf.extract_finance(f)["debt"]
    assert d["val"] == 0 and d["step"] == 2


# ── ④ 합계 항목 범위 ─────────────────────────────────────────────────


def test_fulc_total_item_range_low_used_for_runway():
    f = _facts({C: [_i(48466000)], "AvailableForSaleSecuritiesDebtSecurities": [_i(270374000)]})
    ci = bf.extract_finance(f)["cash_inv"]
    assert ci["range"] == {"low": 270374000, "high": 318840000} and ci["val"] == 270374000
    assert ci["note"] == "합계 항목 · 현금성 증권 포함 여부 미확인 · 범위 표시"
    f["facts"]["us-gaap"][bf.OCF_TAG] = {"units": {"USD": [
        {"start": "2025-07-01", "end": QE, "val": -120000000, "form": "10-Q", "filed": "2026-08-05", "accn": "x"}]}}
    r = bf.runway(bf.extract_finance(f), None, date(2026, 10, 5))
    assert r["cash_inv"] == 270374000 and r["cash_inv_detail"]["range"]["high"] == 318840000


def test_total_item_range_low_is_cash_when_cash_larger():
    ci = bf.extract_finance(_facts({C: [_i(100)], "MarketableSecurities": [_i(40)]}))["cash_inv"]
    assert ci["range"] == {"low": 100, "high": 140} and ci["val"] == 100


def test_edit_short_path_has_no_range():
    f = _facts({C: [_i(181815000)], "MarketableSecuritiesCurrent": [_i(29830000)],
                "AvailableForSaleSecuritiesDebtSecurities": [_i(211645000)]})
    ci = bf.extract_finance(f)["cash_inv"]
    assert "range" not in ci and ci["val"] == 211645000 and ci["total_item"] is None and ci["note"] is None


# ── ① 격일 복귀 방지 ─────────────────────────────────────────────────


def _c(tk, bucket, mcap=0):
    return {"ticker": tk, "cik": "", "mcap_usd": mcap, "mcap_bucket": bucket}


def test_over5b_recorded_then_kept_while_unknown():
    d1 = date(2026, 10, 5)
    rows = [_c("KYMR", "over_5B_excluded", 8929587866), _c("ABCL", "1B-5B", 4212843542)]
    memo, kept, _ = hc.keep_over5b(rows, {}, d1)
    assert memo == {"KYMR": {"ticker": "KYMR", "cik": "", "mcap_usd": 8929587866, "date": "2026-10-05"}} and kept == []
    rows2 = [_c("KYMR", "unknown")]
    memo2, kept2, exp2 = hc.keep_over5b(rows2, memo, date(2026, 11, 4))          # 30일째 · 유지
    assert rows2[0]["mcap_bucket"] == "over_5B_excluded" and rows2[0]["mcap_usd"] == 8929587866
    assert kept2 == ["KYMR"] and exp2 == [] and memo2["KYMR"]["date"] == "2026-10-05"   # 확인 날짜는 바꾸지 않음


def test_over5b_expires_after_30_days_then_rejudged():
    memo = {"KYMR": {"ticker": "KYMR", "cik": "", "mcap_usd": 8929587866, "date": "2026-10-05"}}
    rows = [_c("KYMR", "unknown")]
    memo2, kept, exp = hc.keep_over5b(rows, memo, date(2026, 11, 5))             # 31일째
    assert rows[0]["mcap_bucket"] == "unknown" and kept == [] and exp == ["KYMR"] and memo2 == {}


def test_over5b_new_value_below_5b_clears_record():
    memo = {"KYMR": {"ticker": "KYMR", "cik": "", "mcap_usd": 8929587866, "date": "2026-10-05"}}
    rows = [_c("KYMR", "1B-5B", 4900000000)]
    memo2, kept, _ = hc.keep_over5b(rows, memo, date(2026, 10, 6))
    assert rows[0]["mcap_bucket"] == "1B-5B" and memo2 == {} and kept == []


def test_recent_candidates_union_30_days(tmp_path, monkeypatch):
    cdir = tmp_path / "candidates"
    cdir.mkdir()
    for d, tks in (("20260904", ["OLD"]), ("20260905", ["EDGE"]), ("20261004", ["KYMR", "ABCL"]),
                   ("20261005", ["ABCL", "MBX"])):
        with (cdir / f"biotech_candidates_{d}.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ticker", "cik"])
            for t in tks:
                w.writerow([t, "1"])
    (cdir / "biotech_candidates_v3_20261005.csv").write_text("ticker,cik\nV3ONLY,1\n")
    monkeypatch.setattr(mc._P, "RUNTIME_DIR", tmp_path)
    assert mc.recent_candidates(date(2026, 10, 5)) == ["ABCL", "EDGE", "KYMR", "MBX"]


def test_price_tickers_only_adds_symbols_already_in_month_ledger():
    tickers, extra = mc.price_tickers({"ABCL": "1", "MBX": "2"}, ["ABCL", "KYMR", "NEWX"], {"KYMR": {}, "ABCL": {}})
    assert tickers == ["ABCL", "MBX", "KYMR"] and extra == ["KYMR"]                      # NEWX 는 장부에 없어 넣지 않음


def test_daily_run_sends_one_iex_request_with_recent(tmp_path, monkeypatch):
    """오늘 후보 ∪ 최근 후보 (장부에 있는 종목) 를 IEX 일괄 1건으로 · 월 고유 변동 없음."""
    monkeypatch.setattr(mc._P, "RUNTIME_DIR", tmp_path)
    monkeypatch.setenv(mc.FLAG, "1")
    monkeypatch.setenv("TIINGO_API_KEY", "k" * 20)
    cdir = tmp_path / "candidates"
    cdir.mkdir()
    (cdir / "biotech_candidates_20261004.csv").write_text("ticker,cik\nKYMR,1\nABCL,2\n")
    (cdir / "biotech_candidates_20261005.csv").write_text("ticker,cik\nABCL,2\n")
    (tmp_path / "mcap").mkdir(exist_ok=True)
    (tmp_path / "mcap" / "shares_20261005.json").write_text(json.dumps({"shares": {
        "KYMR": {"shares": 83150618, "shares_asof": "2026-07-31"}, "ABCL": {"shares": 306611466, "shares_asof": "2026-08-03"}}}))
    usage = {"month": "202610", "symbols": {"KYMR": {}, "ABCL": {}, "XBI": {}}, "requests": []}
    monkeypatch.setattr(mc, "load_usage", lambda m: json.loads(json.dumps(usage)))
    saved = {}
    monkeypatch.setattr(mc, "save_usage", lambda u: saved.update(u))
    monkeypatch.setattr(mc, "hourly_check", lambda u, n: (True, None))
    monkeypatch.setattr(mc, "record_request", lambda u, n, by: None)
    monkeypatch.setattr(mc, "backfill_prices", lambda *a, **k: {"requests": 0})
    sent = []

    def fake_iex(get, tickers, key):
        sent.append(list(tickers))
        return [{"ticker": t, "tngoLast": 10.0, "timestamp": "2026-10-02T20:00:00+00:00"} for t in tickers]

    monkeypatch.setattr(mc, "fetch_iex", fake_iex)
    res = mc.run("daily", get_tiingo=lambda *a, **k: None, today=date(2026, 10, 5))
    assert len(sent) == 1 and sorted(sent[0]) == ["ABCL", "KYMR", "XBI"]
    assert res["monthly_unique_used"] == 3
    disp = json.loads((tmp_path / "mcap_display.json").read_text())["rows"]
    assert sorted(disp) == ["ABCL", "KYMR"]                                             # 후보에서 빠진 KYMR 도 시총 값 유지
