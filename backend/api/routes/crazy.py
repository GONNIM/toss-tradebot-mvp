"""Crazy Picks 라우트."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select

from backend.api.auth import require_sniper_token
from backend.api.schemas import CrazyPickResponse
from backend.services.db import get_session
from backend.services.models import CrazyPick
from backend.services.outcomes import summarize

# 조회 전부 로그인 필수 (1025-03 ②)
router = APIRouter(dependencies=[Depends(require_sniper_token)])


@router.get("", response_model=list[CrazyPickResponse])
async def list_crazy_picks(limit: int = Query(10, ge=1, le=50)):
    """최근 Crazy Picks Top N (최신 pick_date 의 rank 순)."""
    async with get_session() as session:
        stmt = (
            select(CrazyPick)
            .order_by(desc(CrazyPick.pick_date), CrazyPick.rank)
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()


@router.get("/history", response_model=list[CrazyPickResponse])
async def history(days: int = Query(7, ge=1, le=90)):
    """최근 N일 Crazy 픽 히스토리 (pick_date desc, rank asc)."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    async with get_session() as session:
        stmt = (
            select(CrazyPick)
            .where(CrazyPick.pick_date >= cutoff)
            .order_by(desc(CrazyPick.pick_date), CrazyPick.rank)
        )
        result = await session.execute(stmt)
        return result.scalars().all()


@router.get("/summary")
async def summary():
    """과거 실현 결과 중앙값·건수 (outcomes 가 채운 값 · 미래 수익 보장 아님)."""
    async with get_session() as session:
        rows = (await session.execute(select(CrazyPick))).scalars().all()
    return summarize(rows, {"1w": "perf_1w", "1m": "perf_1m"})


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
