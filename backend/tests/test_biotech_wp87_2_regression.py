"""WP87-2 · parse_form4 회귀 (가격 열만 추가) · 하루 SEC 요청 공용 장부."""
from __future__ import annotations

from pathlib import Path

from backend.scripts import biotech_h77_alert_brief as br
from backend.scripts.biotech_h28v2_form4_channel import parse_form4
from backend.scripts.biotech_sec_common import SecDailyLedger

FIXTURE = Path(__file__).parent / "fixtures" / "biotech_form4_sample.xml"

# WP87 이전 parse_form4 (커밋 7bcf0c9) 가 같은 표본에서 낸 결과 · 매수 (P · A) 2건만 · 매도 (S · D) 제외
BEFORE_WP87 = [
    {"issuer_cik": "0002088082", "issuer_name": "Electra Therapeutics, Inc.", "tx_date": "2026-09-21", "shares": 333333.0},
    {"issuer_cik": "0002088082", "issuer_name": "Electra Therapeutics, Inc.", "tx_date": "2026-09-22", "shares": 1000000.0},
]


def test_parse_form4_same_as_before_except_price():
    rows = parse_form4(FIXTURE.read_text())
    assert [{k: v for k, v in r.items() if k != "price"} for r in rows] == BEFORE_WP87
    assert [r["price"] for r in rows] == [3.0, None]          # 새 열 · 각주만 있으면 None


def test_ledger_sums_across_steps(tmp_path):
    led = SecDailyLedger.load("20261001", base=tmp_path)
    led.add("form4", 55)
    led.add("price_backfill", 3)
    led.save()
    led2 = SecDailyLedger.load("20261001", base=tmp_path)    # 다음 단계 (브리핑) 가 이어서 더함
    led2.add("brief")
    assert led2.total() == 59 and led2.counts == {"form4": 55, "price_backfill": 3, "brief": 1}
    assert SecDailyLedger.load("20261002", base=tmp_path).total() == 0   # 날짜가 바뀌면 새 장부


def test_brief_requests_go_to_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(br.time, "sleep", lambda s: None)

    class Resp:
        status_code, text = 200, "x"

    class Client:
        def get(self, url, timeout=None):
            return Resp()

    led = SecDailyLedger.load("20261001", base=tmp_path)
    counter = {"sec_requests": 0, "zai_calls": 0, "ledger": led}
    br._sec_text(Client(), "u1", counter)
    br._sec_text(Client(), "u2", counter, "exhibit")
    assert counter["sec_requests"] == 2 and led.counts == {"brief": 1, "exhibit": 1}


# WP92 · 실제 신고서 원문 (서버 form4_xml 보관분 · 신고자 이름·서명자 → "REPORTING PERSON" · 주소·신고자 CIK·각주 본문 제거)
REAL = Path(__file__).parent / "fixtures" / "biotech_form4_real_0000947871-26-000880.xml"


def test_parse_form4_real_filing():
    rows = parse_form4(REAL.read_text())
    assert [{k: v for k, v in r.items() if k != "price"} for r in rows] == [
        {"issuer_cik": "0002088082", "issuer_name": "Electra Therapeutics, Inc.", "tx_date": "2026-09-21", "shares": 333333.0},
        {"issuer_cik": "0002088082", "issuer_name": "Electra Therapeutics, Inc.", "tx_date": "2026-09-21", "shares": 1000000.0},
    ]
    assert [r["price"] for r in rows] == [15.0, 15.0]
    text = REAL.read_text()
    assert "REPORTING PERSON" in text and "<rptOwnerCik>0000000000</rptOwnerCik>" in text
