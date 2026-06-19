"""Moonshot Picks 라우트."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, select

from backend.api.schemas import MoonshotPickResponse
from backend.services.db import get_session
from backend.services.models import MoonshotPick

router = APIRouter()


@router.get("/", response_model=list[MoonshotPickResponse])
async def list_moonshot_picks(
    limit: int = Query(3, ge=1, le=20),
    risk_level: str | None = Query(None, regex="^(HIGH|MED|LOW)$"),
):
    """최근 Moonshot Picks Top N."""
    async with get_session() as session:
        stmt = select(MoonshotPick).order_by(desc(MoonshotPick.created_at))
        if risk_level:
            stmt = stmt.where(MoonshotPick.risk_level == risk_level)
        stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()


@router.get("/history", response_model=list[MoonshotPickResponse])
async def history(days: int = Query(7, ge=1, le=90)):
    """최근 N일 Moonshot 픽 히스토리."""
    cutoff = datetime.now() - timedelta(days=days)
    async with get_session() as session:
        stmt = (
            select(MoonshotPick)
            .where(MoonshotPick.created_at >= cutoff)
            .order_by(desc(MoonshotPick.created_at))
        )
        result = await session.execute(stmt)
        return result.scalars().all()


@router.get("/{ticker}", response_model=MoonshotPickResponse)
async def get_moonshot_pick(ticker: str):
    """단일 종목 최근 Moonshot Pick."""
    async with get_session() as session:
        stmt = (
            select(MoonshotPick)
            .where(MoonshotPick.ticker == ticker.upper())
            .order_by(desc(MoonshotPick.created_at))
            .limit(1)
        )
        result = await session.execute(stmt)
        pick = result.scalar_one_or_none()
        if not pick:
            raise HTTPException(404, f"{ticker} Moonshot Pick 없음")
        return pick
