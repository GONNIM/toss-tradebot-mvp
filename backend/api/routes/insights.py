"""Insights API · Phase C 주 5-3 · 2026-07-30 · 자산화 공개 엔드포인트.

참조: docs/plans/toss-tradebot-tobe/stage2-architecture.md §4-6
      reviews/perspective-c-knowledge-assetization.md 권고 7

Stage 2 지식 자산화 원천 · Wiki sync 스크립트가 소비.
    /api/v1/insights/decision/{run_id}/{ticker} — 판정 근거 permalink (뉴스레터·리포트 인용)
    /api/v1/insights/tier-history/{ticker}     — 종목별 tier 이동 시계열
    /api/v1/insights/tier-history/recent       — 최근 tier 변경 (Weekly Report 소재)
    /api/v1/insights/reject-reasons/summary    — 월별 reject 카테고리 집계
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, func, select

from backend.services.db import get_session
from backend.services.models import PowderKegList, PowderKegTierHistory

router = APIRouter()


# ─── Schemas ─────────────────────────────────────────────────────


class DecisionSummary(BaseModel):
    """판정 근거 permalink 응답 · 뉴스레터·리포트 인용용."""

    model_config = ConfigDict(from_attributes=True)

    run_id: str
    ticker: str
    name: Optional[str]
    status: str
    net_cash_ratio: Optional[float]
    piotroski_f_score: Optional[int]
    owner_pct: Optional[float]
    pbr: Optional[float]
    conditions_json: Optional[str]
    reject_reasons: Optional[str]
    hypothesis_id: Optional[str]
    market_context: Optional[str]
    retrospect_url: Optional[str]
    conditions_margins_json: Optional[str]
    created_at: datetime


class TierHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    run_id: str
    prev_tier: Optional[str]
    curr_tier: str
    change_type: str  # promoted / demoted / stable_first / rejected
    note: Optional[str]
    hypothesis_id: Optional[str]
    changed_at: datetime


class RejectReasonBucket(BaseModel):
    """월별 reject 원인 카테고리 집계."""

    month: str            # YYYY-MM
    category: str         # parsing_error | threshold_miss | hypothesis_revision | other
    count: int


# ─── Categorization helper ───────────────────────────────────────


def _categorize_reject(reject_reasons: Optional[str]) -> str:
    """reject_reasons 문자열 → 카테고리 매핑.

    카테고리 (리뷰 C 권고 4):
        parsing_error       — 데이터 파싱 오류 (예: 서희건설 v1.0→v1.1 취소)
        threshold_miss      — 규모·수치 임계 미달
        hypothesis_revision — 가설 변경으로 강등
        other               — 기타
    """
    if not reject_reasons:
        return "other"
    s = reject_reasons.lower()
    if "parse" in s or "parsing" in s or "invalid" in s:
        return "parsing_error"
    if "hypothesis" in s or "v1." in s or "v2." in s:
        return "hypothesis_revision"
    if any(k in s for k in ("<", ">", "miss", "너무", "미달", "부족", "over", "under")):
        return "threshold_miss"
    return "other"


# ─── Endpoints ───────────────────────────────────────────────────


@router.get("/decision/{run_id}/{ticker}", response_model=DecisionSummary)
async def get_decision(run_id: str, ticker: str):
    """판정 근거 permalink · 특정 run·ticker 조합."""
    async with get_session() as session:
        stmt = (
            select(PowderKegList)
            .where(PowderKegList.run_id == run_id, PowderKegList.ticker == ticker)
            .limit(1)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="decision not found")
        return row


@router.get("/tier-history/recent", response_model=list[TierHistoryItem])
async def get_recent_tier_changes(
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(50, ge=1, le=500),
):
    """최근 tier 이동 이벤트 · Weekly Report 소재."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with get_session() as session:
        stmt = (
            select(PowderKegTierHistory)
            .where(PowderKegTierHistory.changed_at >= cutoff)
            .order_by(desc(PowderKegTierHistory.changed_at))
            .limit(limit)
        )
        return (await session.execute(stmt)).scalars().all()


@router.get("/tier-history/{ticker}", response_model=list[TierHistoryItem])
async def get_ticker_tier_history(ticker: str, limit: int = Query(50, ge=1, le=500)):
    """종목별 tier 이동 이력 · Tickers/{ticker}.md sync 소재."""
    async with get_session() as session:
        stmt = (
            select(PowderKegTierHistory)
            .where(PowderKegTierHistory.ticker == ticker)
            .order_by(desc(PowderKegTierHistory.changed_at))
            .limit(limit)
        )
        return (await session.execute(stmt)).scalars().all()


@router.get("/reject-reasons/summary", response_model=list[RejectReasonBucket])
async def get_reject_reasons_summary(months: int = Query(6, ge=1, le=36)):
    """월별 reject 카테고리 집계 · 리뷰 C 권고 4."""
    cutoff = datetime.utcnow() - timedelta(days=months * 31)
    async with get_session() as session:
        stmt = (
            select(PowderKegList.created_at, PowderKegList.reject_reasons)
            .where(PowderKegList.created_at >= cutoff)
            .where(PowderKegList.status == "rejected")
        )
        rows = (await session.execute(stmt)).all()

    buckets: dict[tuple[str, str], int] = {}
    for created_at, reject_reasons in rows:
        month = created_at.strftime("%Y-%m")
        cat = _categorize_reject(reject_reasons)
        buckets[(month, cat)] = buckets.get((month, cat), 0) + 1

    return [
        RejectReasonBucket(month=m, category=c, count=n)
        for (m, c), n in sorted(buckets.items())
    ]
