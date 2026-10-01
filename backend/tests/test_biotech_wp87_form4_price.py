"""WP87 · Form 4 주당 가격 파싱 · 예전 캐시 가격 보충 (신고서 1회 · 상한)."""
from __future__ import annotations

from backend.scripts import biotech_h65_form4_daily as h65
from backend.scripts.biotech_h28v2_form4_channel import parse_form4

XML = """<ownershipDocument><issuer><issuerCik>0002088082</issuerCik><issuerName>Electra Therapeutics, Inc.</issuerName></issuer>
<nonDerivativeTable>
<nonDerivativeTransaction><transactionDate><value>2026-09-21</value></transactionDate>
<transactionCoding><transactionCode>P</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>333333</value></transactionShares><transactionPricePerShare><value>3.00</value></transactionPricePerShare>
<transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts></nonDerivativeTransaction>
<nonDerivativeTransaction><transactionDate><value>2026-09-21</value></transactionDate>
<transactionCoding><transactionCode>P</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>1000000</value></transactionShares><transactionPricePerShare><footnoteId id="F1"/></transactionPricePerShare>
<transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts></nonDerivativeTransaction>
</nonDerivativeTable></ownershipDocument>"""


def test_parse_price_and_footnote_only():
    rows = parse_form4(XML)
    assert [(r["shares"], r["price"]) for r in rows] == [(333333.0, 3.0), (1000000.0, None)]


def test_backfill_once_per_filing_and_marks_missing():
    cache = {"F1": {"buys": [
        {"tx_date": "2026-09-21", "shares": 333333.0, "accession": "A1"},
        {"tx_date": "2026-09-21", "shares": 1000000.0, "accession": "A1"},
        {"tx_date": "2026-08-01", "shares": 5.0, "accession": "OLD"},          # 30일 밖 · 보충 안 함
    ]}}
    calls = []

    def fetch(filer, acc):
        calls.append(acc)
        return XML

    assert h65.backfill_prices(cache, "2026-09-01", fetch) == 1 and calls == ["A1"]
    buys = cache["F1"]["buys"]
    assert buys[0]["price"] == 3.0 and buys[1]["price"] is None and "price" not in buys[2]
    assert h65.backfill_prices(cache, "2026-09-01", fetch) == 0            # 가격 키가 생겨 재요청 없음
