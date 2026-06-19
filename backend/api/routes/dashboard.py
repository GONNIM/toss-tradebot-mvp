"""대시보드 요약 — Phase K (Toss API) 활성 후."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import desc, select

from backend.api.schemas import DashboardSummary
from backend.services.db import get_session
from backend.services.models import AccountPosition, AuditTrade, EngineStatus

router = APIRouter()


@router.get("/", response_model=DashboardSummary)
async def get_summary():
    """자동매매 대시보드 요약."""
    async with get_session() as session:
        positions = (await session.execute(select(AccountPosition))).scalars().all()

        total_value = 0.0
        total_cost = 0.0
        for p in positions:
            qty = p.qty or 0
            avg_price = p.avg_price or 0
            total_cost += qty * avg_price
            total_value += qty * avg_price  # 실 평가가는 Phase K (Toss API) 후

        unrealized = total_value - total_cost
        realized = 0.0  # Phase K — AuditTrade 기반 계산은 SELL/BUY 매칭 후

        # 마지막 거래
        last_trade = (await session.execute(
            select(AuditTrade).order_by(desc(AuditTrade.timestamp)).limit(1)
        )).scalar_one_or_none()

        # 엔진 상태 (Phase K)
        engine = (await session.execute(
            select(EngineStatus).order_by(desc(EngineStatus.updated_at)).limit(1)
        )).scalar_one_or_none()

        engine_status = "not_initialized"
        if engine:
            engine_status = "running" if engine.is_running else "stopped"

        return DashboardSummary(
            total_value_usd=total_value,
            total_cost_usd=total_cost,
            realized_pnl_usd=realized,
            unrealized_pnl_usd=unrealized,
            open_positions=len(positions),
            last_trade_at=last_trade.timestamp if last_trade else None,
            engine_status=engine_status,
        )
