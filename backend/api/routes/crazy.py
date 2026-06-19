"""Crazy Picks 라우트."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, select

from backend.api.schemas import CrazyPickResponse
from backend.services.db import get_session
from backend.services.models import CrazyPick

router = APIRouter()


@router.get("/", response_model=list[CrazyPickResponse])
async def list_crazy_picks(limit: int = Query(10, ge=1, le=50)):
    """최근 Crazy Picks Top N."""
    async with get_session() as session:
        stmt = select(CrazyPick).order_by(desc(CrazyPick.created_at)).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()


@router.get("/{ticker}", response_model=CrazyPickResponse)
async def get_crazy_pick(ticker: str):
    """단일 종목 최근 Crazy Pick."""
    async with get_session() as session:
        stmt = (
            select(CrazyPick)
            .where(CrazyPick.ticker == ticker.upper())
            .order_by(desc(CrazyPick.created_at))
            .limit(1)
        )
        result = await session.execute(stmt)
        pick = result.scalar_one_or_none()
        if not pick:
            raise HTTPException(404, f"{ticker} Crazy Pick 없음")
        return pick
