"""Insights API · Phase C 주 5-3 · 2026-07-30 · 자산화 공개 엔드포인트.

참조: docs/plans/toss-tradebot-tobe/stage2-architecture.md §4-6
      reviews/perspective-c-knowledge-assetization.md 권고 7

Stage 2 지식 자산화 원천 · Wiki sync 스크립트가 소비.
    /api/v1/insights/decision/{run_id}/{ticker} — 판정 근거 permalink (뉴스레터·리포트 인용)
    /api/v1/insights/tier-history/{ticker}     — 종목별 tier 이동 시계열
    /api/v1/insights/tier-history/recent       — 최근 tier 변경 (Weekly Report 소재)
    /api/v1/insights/reject-reasons/summary    — 월별 reject 카테고리 집계
    /api/v1/insights/weekly                    — Weekly Insights 초안 (Phase E · 2026-07-31)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, func, select

from backend.services.db import get_session
from backend.services.models import PowderKegList, PowderKegTierHistory, UserJudgment

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


# ─── Weekly Insights (Phase E · 2026-07-31) ─────────────────────
# 로드맵 주 12 에 예정된 Weekly 자동 초안의 데이터 조합 스켈레톤.
# Phase E 에서는 draft 만 반환 · 실 스케줄 발송(sunday 08:00)은 Phase F 에서 크론.
# 소비자: Wiki sync 스크립트가 Weekly/{YYYY-Www}.md 로 렌더.


class WeeklyJudgmentStat(BaseModel):
    total: int
    computed: int
    win_rate: Optional[float]
    avg_return: Optional[float]
    mood_distribution: dict[str, int]
    page_source_distribution: dict[str, int]


class WeeklyInsightsDraft(BaseModel):
    period_start: datetime
    period_end: datetime
    week_label: str  # 2026-W31
    tier_events: list[TierHistoryItem]
    judgment_stats: WeeklyJudgmentStat
    summary_bullets: list[str]


def _iso_week_label(dt: datetime) -> str:
    """ISO week 라벨 · 2026-W31 형식."""
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


@router.get("/weekly", response_model=WeeklyInsightsDraft)
async def get_weekly_insights(days: int = Query(7, ge=1, le=31)):
    """Weekly Insights 자동 초안 · tier 이동 + 판정 통계 조합.

    Phase E · 스켈레톤. summary_bullets 는 규칙 기반 (LLM 초안은 Phase F).
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(days=days)

    async with get_session() as session:
        # 1) 최근 tier 이동
        tier_stmt = (
            select(PowderKegTierHistory)
            .where(PowderKegTierHistory.changed_at >= cutoff)
            .order_by(desc(PowderKegTierHistory.changed_at))
            .limit(50)
        )
        tier_events = (await session.execute(tier_stmt)).scalars().all()

        # 2) 판정 통계
        j_stmt = select(UserJudgment).where(UserJudgment.ts >= cutoff)
        judgments = (await session.execute(j_stmt)).scalars().all()

    total = len(judgments)
    computed_list = [j for j in judgments if j.result_at_horizon is not None]
    computed = len(computed_list)
    wins = sum(1 for j in computed_list if (j.result_at_horizon or 0) > 0)
    win_rate = (wins / computed) if computed else None
    avg_return = (
        sum(j.result_at_horizon or 0.0 for j in computed_list) / computed
        if computed else None
    )
    mood_dist: dict[str, int] = {}
    src_dist: dict[str, int] = {}
    for j in judgments:
        mood_dist[j.mood] = mood_dist.get(j.mood, 0) + 1
        src_dist[j.page_source] = src_dist.get(j.page_source, 0) + 1

    # 3) 규칙 기반 요약 bullet (LLM 없이 · Phase F 에서 anthropic 호출로 승격 예정)
    bullets: list[str] = []
    if total == 0:
        bullets.append(f"이번 주({days}일) 판정 없음 · 사용 정착 필요")
    else:
        bullets.append(f"판정 {total}건 · outcome 계산 {computed}건")
        if win_rate is not None:
            bullets.append(f"승률 {win_rate * 100:.1f}% · 평균 수익률 {(avg_return or 0) * 100:.2f}%")
        # 편중 감지
        if src_dist:
            top_src = max(src_dist.items(), key=lambda x: x[1])
            share = top_src[1] / total
            if share > 0.6:
                bullets.append(f"⚠️ page_source 편중 · {top_src[0]} {share * 100:.0f}%")
        # revenge/fomo mood 경고
        rev = mood_dist.get("revenge", 0) + mood_dist.get("fomo", 0)
        if rev > 0:
            bullets.append(f"⚠️ hot state 판정 {rev}건 (revenge/fomo)")
    promoted = sum(1 for t in tier_events if t.change_type == "promoted")
    demoted = sum(1 for t in tier_events if t.change_type == "demoted")
    if promoted or demoted:
        bullets.append(f"화약고 tier 이동 · 승격 {promoted} / 강등 {demoted}")

    return WeeklyInsightsDraft(
        period_start=cutoff,
        period_end=now,
        week_label=_iso_week_label(now),
        tier_events=[TierHistoryItem.model_validate(t) for t in tier_events],
        judgment_stats=WeeklyJudgmentStat(
            total=total,
            computed=computed,
            win_rate=win_rate,
            avg_return=avg_return,
            mood_distribution=mood_dist,
            page_source_distribution=src_dist,
        ),
        summary_bullets=bullets,
    )
