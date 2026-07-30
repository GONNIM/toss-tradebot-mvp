"""Judgment Journal API · Phase B 주 3-2 · 2026-07-30.

참조: docs/plans/toss-tradebot-tobe/stage1-optimization.md §1-2
      docs/plans/toss-tradebot-tobe/reviews/perspective-a-quant-psychology.md 권고 1

엔드포인트:
    POST   /api/v1/judgments             — 판정 생성 (rejection criteria 필수)
    GET    /api/v1/judgments             — 조회 (필터: ticker · page_source · mood · horizon)
    GET    /api/v1/judgments/baseline    — 승률·평균 수익률·mood 분포 (Stage 2 진입 KPI 근거)
    PATCH  /api/v1/judgments/{id}/outcome — outcome 갱신 (cron 자동 · 수동 오버라이드)
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from backend.services.db import get_session
from backend.services.market_regime import infer_market_regime
from backend.services.models import UserJudgment

router = APIRouter()


# ─── Schemas ─────────────────────────────────────────────────────


class JudgmentCreate(BaseModel):
    """판정 생성 페이로드 · rejection criteria (invalidation_price) 필수."""

    ticker: str = Field(..., min_length=1, max_length=20)
    page_source: str = Field(..., min_length=1, max_length=30)
    hypothesis_id: str = Field(..., min_length=1, max_length=50)
    thesis_md: str = Field(..., min_length=1)
    invalidation_price: float = Field(..., description="필수 · 반증 기준. 없으면 판정 아님.")
    target_price: Optional[float] = None
    horizon_days: int = Field(default=7, ge=1, le=365)
    mood: Literal["cool", "neutral", "revenge", "fomo"] = "neutral"
    market_regime: Optional[str] = None  # None 이면 자동 태깅


class JudgmentOut(BaseModel):
    id: int
    ts: datetime
    user_id: str
    ticker: str
    page_source: str
    hypothesis_id: str
    thesis_md: str
    invalidation_price: Optional[float]
    target_price: Optional[float]
    horizon_days: int
    mood: str
    market_regime: str
    result_at_horizon: Optional[float]
    result_computed_at: Optional[datetime]
    git_sha: Optional[str]

    class Config:
        from_attributes = True


class OutcomeUpdate(BaseModel):
    result_at_horizon: float


class Baseline(BaseModel):
    """Stage 2 진입 KPI 근거 · 판정 정확도 baseline (T+N horizon 만 집계)."""

    total_count: int
    computed_count: int  # outcome 계산 완료 건
    win_rate: Optional[float]  # 양수 outcome 비율
    avg_return: Optional[float]  # 평균 수익률
    mood_distribution: dict[str, int]  # mood 별 판정 건수
    page_source_distribution: dict[str, int]


# ─── Endpoints ───────────────────────────────────────────────────


@router.post("", response_model=JudgmentOut, status_code=201)
async def create_judgment(payload: JudgmentCreate):
    """판정 생성 · invalidation_price 필수 · git_sha·market_regime 자동."""
    regime = payload.market_regime or await infer_market_regime()
    git_sha = os.getenv("GIT_SHA") or os.getenv("VERCEL_GIT_COMMIT_SHA")

    async with get_session() as session:
        row = UserJudgment(
            ticker=payload.ticker,
            page_source=payload.page_source,
            hypothesis_id=payload.hypothesis_id,
            thesis_md=payload.thesis_md,
            invalidation_price=payload.invalidation_price,
            target_price=payload.target_price,
            horizon_days=payload.horizon_days,
            mood=payload.mood,
            market_regime=regime,
            git_sha=git_sha[:40] if git_sha else None,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


@router.get("", response_model=list[JudgmentOut])
async def list_judgments(
    ticker: Optional[str] = None,
    page_source: Optional[str] = None,
    mood: Optional[str] = None,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
):
    """조회 · 기본 최근 30일 · self-page 편애 방지 위해 모든 page_source 병치."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with get_session() as session:
        stmt = select(UserJudgment).where(UserJudgment.ts >= cutoff)
        if ticker:
            stmt = stmt.where(UserJudgment.ticker == ticker)
        if page_source:
            stmt = stmt.where(UserJudgment.page_source == page_source)
        if mood:
            stmt = stmt.where(UserJudgment.mood == mood)
        stmt = stmt.order_by(desc(UserJudgment.ts)).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()


@router.get("/baseline", response_model=Baseline)
async def get_baseline(days: int = Query(90, ge=7, le=365)):
    """판정 정확도 baseline · Stage 2 진입 KPI 근거."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with get_session() as session:
        stmt = select(UserJudgment).where(UserJudgment.ts >= cutoff)
        rows = (await session.execute(stmt)).scalars().all()

    total = len(rows)
    computed_rows = [r for r in rows if r.result_at_horizon is not None]
    computed_count = len(computed_rows)

    win_rate = None
    avg_return = None
    if computed_count > 0:
        wins = sum(1 for r in computed_rows if r.result_at_horizon > 0)
        win_rate = wins / computed_count
        avg_return = sum(r.result_at_horizon for r in computed_rows) / computed_count

    mood_dist: dict[str, int] = {}
    page_dist: dict[str, int] = {}
    for r in rows:
        mood_dist[r.mood] = mood_dist.get(r.mood, 0) + 1
        page_dist[r.page_source] = page_dist.get(r.page_source, 0) + 1

    return Baseline(
        total_count=total,
        computed_count=computed_count,
        win_rate=win_rate,
        avg_return=avg_return,
        mood_distribution=mood_dist,
        page_source_distribution=page_dist,
    )


@router.patch("/{judgment_id}/outcome", response_model=JudgmentOut)
async def update_outcome(judgment_id: int, payload: OutcomeUpdate):
    """outcome 수동 갱신 · 크론 자동 계산 실패 시 대체 경로."""
    async with get_session() as session:
        row = await session.get(UserJudgment, judgment_id)
        if not row:
            raise HTTPException(status_code=404, detail="judgment not found")
        row.result_at_horizon = payload.result_at_horizon
        row.result_computed_at = datetime.utcnow()
        await session.commit()
        await session.refresh(row)
        return row
