"""포지션 라우트 — Phase K (Toss API) 활성 후 작동."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from backend.api.schemas import PositionResponse
from backend.services.db import get_session
from backend.services.models import AccountPosition

router = APIRouter()


@router.get("/", response_model=list[PositionResponse])
async def list_positions():
    """현재 보유 종목 (Phase K 활성 후 데이터 채워짐)."""
    async with get_session() as session:
        stmt = select(AccountPosition)
        result = await session.execute(stmt)
        positions = result.scalars().all()
        return [
            PositionResponse(
                ticker=p.ticker,
                shares=p.qty or 0,
                avg_cost=p.avg_price or 0,
                current_price=None,    # Phase K — 실시간 시세 후 채움
                unrealized_pnl_pct=None,
                risk_level="MED",      # Phase K — TickerUniverse JOIN 후 채움
            )
            for p in positions
        ]
