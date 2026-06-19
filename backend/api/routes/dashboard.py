"""대시보드 요약 — Phase K (Toss API) 활성 후."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import desc, func, select

from backend.api.schemas import DashboardSummary
from backend.services.db import get_session
from backend.services.models import Account, AccountPosition, AuditTrade, EngineStatus

router = APIRouter()


@router.get("/", response_model=DashboardSummary)
async def get_summary():
    """자동매매 대시보드 요약."""
    async with get_session() as session:
        positions = (await session.execute(select(AccountPosition))).scalars().all()
        total_value = sum((p.current_price or p.avg_cost) * p.shares for p in positions)
        total_cost = sum(p.avg_cost * p.shares for p in positions)
        unrealized = total_value - total_cost

        # 실현 손익
        realized = (await session.execute(
            select(func.coalesce(func.sum(AuditTrade.realized_pnl_usd), 0))
        )).scalar() or 0.0

        # 마지막 거래
        last_trade = (await session.execute(
            select(AuditTrade).order_by(desc(AuditTrade.executed_at)).limit(1)
        )).scalar_one_or_none()

        # 엔진 상태
        engine = (await session.execute(
            select(EngineStatus).order_by(desc(EngineStatus.updated_at)).limit(1)
        )).scalar_one_or_none()

        return DashboardSummary(
            total_value_usd=total_value,
            total_cost_usd=total_cost,
            realized_pnl_usd=realized,
            unrealized_pnl_usd=unrealized,
            open_positions=len(positions),
            last_trade_at=last_trade.executed_at if last_trade else None,
            engine_status=engine.status if engine else "not_initialized",
        )
