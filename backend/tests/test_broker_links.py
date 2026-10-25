"""1025-06 · 토스증권 주소 규칙 (국내 A코드 · 미국은 확인된 코드만 주문 화면)."""
from __future__ import annotations

import pytest

from backend.services import broker_links as bl
from backend.services.models import TossStockCode


def test_code_from_list_date():
    assert bl.toss_code_from_list_date("1981-05-27") == "US19810527001"
    assert bl.toss_code_from_list_date(None) is None
    assert bl.toss_code_from_list_date("1981/05/27") is None
    assert bl.toss_code_from_list_date("") is None


def test_kr_link():
    assert bl.is_kr_code("005930") and bl.is_kr_code("0101N0")
    assert not bl.is_kr_code("AAPL") and not bl.is_kr_code("ABCDEF")
    link = bl.broker_link("005930", None)
    assert link == {"symbol": "005930", "kind": "order", "url": "https://www.tossinvest.com/stocks/A005930/order", "verified": True}
    assert bl.broker_link("0101N0", None)["url"] == "https://www.tossinvest.com/stocks/A0101N0/order"


def test_us_unverified_is_search():
    row = TossStockCode(symbol="WEN", toss_code="US19810527001", source="api", verified=False)
    link = bl.broker_link("WEN", row)
    assert link["kind"] == "search" and link["url"] == "https://www.tossinvest.com/" and link["verified"] is False
    assert bl.broker_link("MRNA", None)["kind"] == "search"


def test_us_verified_is_order():
    row = TossStockCode(symbol="WEN", toss_code="US19810527001", source="manual", verified=True)
    assert bl.broker_link("WEN", row) == {"symbol": "WEN", "kind": "order", "url": "https://www.tossinvest.com/stocks/US19810527001/order", "verified": True}
    no_code = TossStockCode(symbol="X", toss_code=None, source="api", verified=True)
    assert bl.broker_link("X", no_code)["kind"] == "search"


def test_lowercase_and_junk():
    assert bl.normalize_symbol(" aapl ") == "AAPL"
    assert bl.normalize_symbol("brk.b") == "BRK.B"
    for bad in ("A;B", "", "A" * 13, "가나"):
        with pytest.raises(ValueError):
            bl.normalize_symbol(bad)
