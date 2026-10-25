"""토스증권 이동 주소 API (1025-06 · docs/plans/site-roadmap/broker-link.md).

- GET  /api/v1/broker-links?symbols=…   공개 · 표만 읽음 (토스 API 호출 없음) · 최대 50
- GET  /api/v1/broker-links/codes        관리자 · 미국 코드 목록 (확인 전 먼저)
- PUT  /api/v1/broker-links/{symbol}     관리자 · 토스 주소를 붙여 고치거나 「확인함」 표시 (source=manual)
"""
from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from backend.api.auth import require_sniper_token
from backend.services import broker_links as bl
from backend.services.models import TossStockCode

router = APIRouter()

MAX_SYMBOLS = 50
_URL_RE = re.compile(r"^https://(www\.)?tossinvest\.com/stocks/(US\d{11})(/|/order)?(\?.*)?$")


def _parse_symbols(raw: str) -> list[str]:
    parts = [p for p in raw.split(",") if p.strip()]
    if not parts or len(parts) > MAX_SYMBOLS:
        raise HTTPException(status_code=422, detail=f"symbols 는 1~{MAX_SYMBOLS}개")
    out: list[str] = []
    for p in parts:
        try:
            s = bl.normalize_symbol(p)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        if s not in out:
            out.append(s)
    return out


@router.get("")
async def get_links(symbols: str = Query(..., max_length=700)) -> dict:
    from backend.services.db import get_session

    syms = _parse_symbols(symbols)
    async with get_session() as session:
        rows = {r.symbol: r for r in (await session.execute(select(TossStockCode).where(TossStockCode.symbol.in_(syms)))).scalars().all()}
    return {"links": [bl.broker_link(s, rows.get(s)) for s in syms]}


def _row_view(r: TossStockCode) -> dict:
    return {"symbol": r.symbol, "toss_code": r.toss_code, "list_date": r.list_date, "source": r.source,
            "verified": r.verified, "updated_at": r.updated_at.isoformat() if r.updated_at else None}


@router.get("/codes", dependencies=[Depends(require_sniper_token)])
async def list_codes() -> dict:
    from backend.services.db import get_session

    async with get_session() as session:
        rows = (await session.execute(select(TossStockCode).order_by(TossStockCode.verified, TossStockCode.symbol))).scalars().all()
    return {"codes": [_row_view(r) for r in rows if not bl.is_kr_code(r.symbol)]}


class CodeUpdate(BaseModel):
    toss_url: Optional[str] = None
    verified: bool = True


@router.put("/{symbol}", dependencies=[Depends(require_sniper_token)])
async def update_code(symbol: str, body: CodeUpdate) -> dict:
    from backend.services.db import get_session

    try:
        sym = bl.normalize_symbol(symbol)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if bl.is_kr_code(sym):
        raise HTTPException(status_code=422, detail="국내 종목은 코드로 바로 연결되므로 고칠 것이 없습니다")
    code: Optional[str] = None
    if body.toss_url:
        m = _URL_RE.match(body.toss_url.strip())
        if not m:
            raise HTTPException(status_code=422, detail="토스증권 종목 주소가 아닙니다 (예: https://www.tossinvest.com/stocks/US19810527001/order)")
        code = m.group(2)
    async with get_session() as session:
        row = await session.get(TossStockCode, sym)
        if row is None:
            if code is None:
                raise HTTPException(status_code=422, detail="코드가 없는 종목은 주소를 함께 넣어 주십시오")
            row = TossStockCode(symbol=sym, toss_code=code, source="manual", verified=body.verified)
            session.add(row)
        else:
            if code is not None:
                row.toss_code = code
            if not row.toss_code:
                raise HTTPException(status_code=422, detail="코드가 없는 종목은 주소를 함께 넣어 주십시오")
            row.source, row.verified = "manual", body.verified
        await session.flush()
        await session.refresh(row)  # onupdate 로 만료된 updated_at 을 다시 읽음
        return _row_view(row)
