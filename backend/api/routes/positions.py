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
                shares=p.shares,
                avg_cost=p.avg_cost,
                current_price=p.current_price,
                unrealized_pnl_pct=p.unrealized_pnl_pct,
                risk_level=p.risk_level or "MED",
            )
            for p in positions
        ]
