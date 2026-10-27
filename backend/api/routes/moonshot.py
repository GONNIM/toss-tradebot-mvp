"""Moonshot Picks 라우트."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select

from backend.api.auth import require_sniper_token
from backend.api.schemas import MoonshotPickResponse
from backend.services.db import get_session
from backend.services.models import MoonshotPick
from backend.services.outcomes import summarize

# 조회 전부 로그인 필수 (1025-03 ②)
router = APIRouter(dependencies=[Depends(require_sniper_token)])


@router.get("", response_model=list[MoonshotPickResponse])
async def list_moonshot_picks(
    limit: int = Query(3, ge=1, le=20),
    risk_level: str | None = Query(None, pattern="^(HIGH|MED|LOW)$"),
):
    """최근 Moonshot Picks Top N (최신 pick_date 의 rank 순)."""
    async with get_session() as session:
        # 최신 pick_date 부터 rank 오름차순
        stmt = (
            select(MoonshotPick)
            .order_by(desc(MoonshotPick.pick_date), MoonshotPick.rank)
        )
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


@router.get("/summary")
async def summary():
    """과거 실현 결과 중앙값·건수 (outcomes 가 채운 값 · 미래 수익 보장 아님)."""
    async with get_session() as session:
        rows = (await session.execute(select(MoonshotPick))).scalars().all()
    return summarize(rows, {"1d": "perf_1d", "3d": "perf_3d", "5d": "perf_5d"})


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
