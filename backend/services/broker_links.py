"""토스증권 웹 주소 규칙 (1025-06 · docs/plans/site-roadmap/broker-link.md).

사이트는 주문을 넣지 않는다. 종목 → 토스증권 웹 주문 화면 주소만 만든다.
- 국내: https://www.tossinvest.com/stocks/A{코드}/order
- 미국: 사람이 확인한 (verified) 토스 코드만 주문 화면 · 그 밖에는 토스증권 첫 화면 (검색) 으로.
"""
from __future__ import annotations

import re
from typing import Optional

from backend.services.models import TossStockCode

TOSS_WEB = "https://www.tossinvest.com/"
_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")
_KR_RE = re.compile(r"^(?=.*\d)[0-9A-Z]{6}$")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def normalize_symbol(raw: str) -> str:
    sym = (raw or "").strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise ValueError(f"종목 기호 형식 오류: {raw!r}")
    return sym


def is_kr_code(sym: str) -> bool:
    return bool(_KR_RE.match(sym))


def toss_code_from_list_date(list_date: Optional[str]) -> Optional[str]:
    """상장일 `YYYY-MM-DD` → `US{YYYYMMDD}001` (추정 규칙 · 사용자 예 WEN = US19810527001)."""
    m = _DATE_RE.match(list_date or "")
    return f"US{m.group(1)}{m.group(2)}{m.group(3)}001" if m else None


def order_url(code: str) -> str:
    return f"{TOSS_WEB}stocks/{code}/order"


def broker_link(symbol: str, row: Optional[TossStockCode]) -> dict:
    if is_kr_code(symbol):
        return {"symbol": symbol, "kind": "order", "url": order_url(f"A{symbol}"), "verified": True}
    if row is not None and row.verified and row.toss_code:
        return {"symbol": symbol, "kind": "order", "url": order_url(row.toss_code), "verified": True}
    return {"symbol": symbol, "kind": "search", "url": TOSS_WEB, "verified": False}
