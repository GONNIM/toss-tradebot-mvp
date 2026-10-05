"""P3a-2 ① 현금 및 투자자산 사다리 (PRD v0.6 FR-5) · ② 오늘 기준 0개월 이하 표시 · ④ 차입금 사다리 (FR-6a).

수치는 P2 에서 받은 companyfacts 원본 (CIK0001815442 KYMR · CIK0001650664 EDIT · CIK0001703057 ABCL
· CIK0000882796 BCRX · CIK0001619856 CRBU · CIK0001098972 AGEN) 의 2026-06-30 값을 인용했다 (새 SEC 요청 0).
"""
from __future__ import annotations

from datetime import date

from backend.scripts import biotech_filings as bf

TODAY = date(2026, 10, 5)
QE = "2026-06-30"


def _i(val, form="10-Q", filed="2026-08-05", accn="x", end=QE) -> dict:
    return {"end": end, "val": val, "form": form, "filed": filed, "accn": accn}


def _d(start, end, val, form, filed) -> dict:
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed, "accn": "x"}


def _facts(tags: dict, ocf: tuple | None = None) -> dict:
    ug = {k: {"units": {"USD": v}} for k, v in tags.items()}
    if ocf:   # (연간 2025 · 올해 1~6월 · 전년 1~6월)
        ug[bf.OCF_TAG] = {"units": {"USD": [_d("2025-01-01", "2025-12-31", ocf[0], "10-K", "2026-03-01"),
                                            _d("2026-01-01", QE, ocf[1], "10-Q", "2026-08-05"),
                                            _d("2025-01-01", "2025-06-30", ocf[2], "10-Q", "2026-08-05")]}}
    return {"facts": {"us-gaap": ug, "dei": {}}}


C = bf.CASH_TAG
KYMR = _facts({C: [_i(124477000, accn="0001193125-26-333849")],
               "AvailableForSaleSecuritiesDebtSecuritiesCurrent": [_i(566508000)],
               "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent": [_i(813901000)],
               "AvailableForSaleSecuritiesDebtSecurities": [_i(1380409000)]},          # 합계 항목 · 단기 · 장기가 있으므로 안 씀
              ocf=(-232891000, -142905000, -139034000))
EDIT = _facts({C: [_i(181815000)], "MarketableSecuritiesCurrent": [_i(29830000)],
               "MarketableSecuritiesNoncurrent": [_i(0, form="10-K", end="2024-12-31")],
               "AvailableForSaleSecuritiesDebtSecurities": [_i(211645000)],
               "LongTermDebtNoncurrent": [_i(48238000)], "LongTermDebtCurrent": [_i(7500000)]})
ABCL = _facts({C: [_i(120065000)], "CashCashEquivalentsAndShortTermInvestments": [_i(540104000)],
               "AvailableForSaleSecuritiesDebtSecurities": [_i(420039000)],
               "LongTermDebtCurrent": [_i(1, form="10-K", end="2020-12-31")]})
BCRX = _facts({C: [_i(154972000)], "ShortTermInvestments": [_i(197601000)], "LongTermInvestments": [_i(0)],
               "AvailableForSaleSecuritiesDebtSecuritiesCurrent": [_i(216137000, form="10-K", end="2024-12-31")],
               "LongTermDebtNoncurrent": [_i(395400000)]})
CRBU = _facts({C: [_i(26194000)], "CashCashEquivalentsAndShortTermInvestments": [_i(113800000)],
               "AvailableForSaleSecuritiesDebtSecuritiesCurrent": [_i(86120000)],
               "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent": [_i(1504000)]})
AGEN = _facts({C: [_i(18738000, filed="2026-08-07")],
               "CashCashEquivalentsAndShortTermInvestments": [_i(3500000, end="2025-09-30")],
               "LongTermDebt": [_i(30068000)], "LongTermDebtCurrent": [_i(30068000)]},
              ocf=(-77195000, -67149000, -45840000))


# ── ① 현금 및 투자자산 ────────────────────────────────────────────────


def test_kymr_cash_plus_short_and_long():
    ci = bf.extract_finance(KYMR)["cash_inv"]
    assert ci["val"] == 124477000 + 566508000 + 813901000 == 1504886000                  # PRD 12절 "약 1,505M"
    assert ci["short"]["tag"] == "AvailableForSaleSecuritiesDebtSecuritiesCurrent"
    assert ci["long"]["tag"] == "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent"
    assert ci["total_item"] is None and ci["note"] is None
    assert ci["short"]["val"] + ci["long"]["val"] == 1380409000                          # 합계 항목과 같음 (이중 계산 없음)


def test_edit_short_only_and_old_long_dropped():
    ci = bf.extract_finance(EDIT)["cash_inv"]
    assert ci["val"] == 181815000 + 29830000 == 211645000 and ci["long"] is None
    assert {"tag": "MarketableSecuritiesNoncurrent", "end": "2024-12-31"} in ci["dropped"]


def test_abcl_short_from_cash_and_short_sum():
    ci = bf.extract_finance(ABCL)["cash_inv"]
    assert ci["short"] == {"tag": bf.INV_SHORT_SUM, "end": QE, "val": 540104000 - 120065000, "form": "10-Q",
                           "filed": "2026-08-05", "accn": "x"}
    assert ci["val"] == 540104000 and ci["short"]["val"] == 420039000                    # AFS 합계 항목과 같음


def test_bcrx_short_and_zero_long():
    ci = bf.extract_finance(BCRX)["cash_inv"]
    assert ci["short"]["tag"] == "ShortTermInvestments" and ci["long"]["val"] == 0
    assert ci["val"] == 154972000 + 197601000 == 352573000


def test_crbu_short_sum_then_long_noncurrent():
    ci = bf.extract_finance(CRBU)["cash_inv"]
    assert ci["short"]["val"] == 113800000 - 26194000 and ci["long"]["val"] == 1504000
    assert ci["val"] == 115304000


def test_total_item_only_when_no_short_and_long():
    f = _facts({C: [_i(48466000)], "AvailableForSaleSecuritiesDebtSecurities": [_i(270374000)]})   # FULC
    ci = bf.extract_finance(f)["cash_inv"]
    assert ci["total_item"]["tag"] == "AvailableForSaleSecuritiesDebtSecurities" and ci["val"] == 318840000


def test_negative_short_sum_skipped():
    f = _facts({C: [_i(100)], bf.INV_SHORT_SUM: [_i(90)], "ShortTermInvestments": [_i(5)]})
    assert bf.extract_finance(f)["cash_inv"]["short"]["tag"] == "ShortTermInvestments"


def test_no_investment_items_cash_only():
    ci = bf.extract_finance(_facts({C: [_i(7624000)]}))["cash_inv"]                  # CYPH
    assert ci["val"] == 7624000 and ci["note"] == bf.INV_NONE == "투자자산 항목 없음 · 현금만"


def test_investment_end_mismatch_cash_only():
    ci = bf.extract_finance(AGEN)["cash_inv"]
    assert ci["val"] == 18738000 and ci["note"] == bf.INV_MISMATCH
    assert ci["dropped"] == [{"tag": bf.INV_SHORT_SUM, "end": "2025-09-30"}]


def test_runway_uses_cash_and_investments():
    r = bf.runway(bf.extract_finance(KYMR), None, TODAY)
    ttm = -232891000 + -142905000 - -139034000
    assert r["ocf_ttm"] == ttm == -236762000
    assert r["cash"] == 124477000 and r["cash_inv"] == 1504886000
    assert r["months_qe"] == round(1504886000 / (236762000 / 12), 2) == 76.27        # P3a 현금만 = 6.31
