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


# ─── 하루 1회 배치 (서버 cron 만 · 로컬에서 토스 API 를 부르면 서버 토큰이 끊긴다) ───
import asyncio  # noqa: E402
import csv  # noqa: E402
import logging  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

logger = logging.getLogger(__name__)

BATCH = 200
REASK_DAYS = 7


def radar_symbols() -> list[str]:
    """최신 바이오 레이더 CSV 의 미국 티커 (순서 유지 · 중복·국내·빈칸 제외)."""
    from backend.api.routes.biotech import _latest_radar_csv  # 파일 찾기 규칙은 바이오 화면과 같게 (옮기지 않음)

    path = _latest_radar_csv()
    if not path or not path.exists():
        return []
    out: list[str] = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                sym = normalize_symbol(row.get("ticker") or "")
            except ValueError:
                continue
            if not is_kr_code(sym) and sym not in out:
                out.append(sym)
    return out


async def refresh_toss_stock_codes(client=None, symbols: Optional[list[str]] = None) -> dict:
    """미국 종목의 토스 코드 후보를 공식 Open API 상장일로 만든다 · source=manual 은 건드리지 않는다."""
    from sqlalchemy import select

    from backend.services.db import get_session

    if symbols is None:
        symbols = radar_symbols()
    syms: list[str] = []
    for raw in symbols:
        try:
            s = normalize_symbol(raw)
        except ValueError:
            continue
        if not is_kr_code(s) and s not in syms:
            syms.append(s)

    async with get_session() as session:
        rows = {r.symbol: r for r in (await session.execute(select(TossStockCode).where(TossStockCode.symbol.in_(syms)))).scalars().all()} if syms else {}
    now = datetime.utcnow()
    manual = [s for s in syms if s in rows and rows[s].source == "manual"]
    ask = [s for s in syms if s not in manual and (s not in rows or rows[s].updated_at < now - timedelta(days=REASK_DAYS))]

    if ask and client is None:
        from backend.execution.brokers.toss_client import get_toss_client

        client = get_toss_client()
    dates: dict[str, Optional[str]] = {}
    for i in range(0, len(ask), BATCH):
        chunk = ask[i:i + BATCH]
        for item in await asyncio.to_thread(client.stocks, chunk) or []:
            sym = str(item.get("symbol") or "").upper()
            if sym:
                dates[sym] = item.get("listDate")

    found = 0
    async with get_session() as session:
        for s in ask:
            ld = dates.get(s)
            code = toss_code_from_list_date(ld)
            found += code is not None
            row = await session.get(TossStockCode, s)
            if row is None:
                session.add(TossStockCode(symbol=s, toss_code=code, list_date=ld, source="api", verified=False, updated_at=now))
            else:
                row.toss_code, row.list_date, row.verified, row.updated_at = code, ld, False, now
    out = {"asked": len(ask), "found": found, "missing": len(ask) - found, "skipped_manual": len(manual)}
    wen = f" · WEN list_date={dates['WEN']}" if "WEN" in dates else ""
    logger.info(f"[broker-links] asked={out['asked']} found={found} missing={out['missing']} manual={len(manual)}{wen}")
    return out
