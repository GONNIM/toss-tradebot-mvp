"""Rulebook API · Phase E 확장 · 2026-08-02.

존마 강의 3원칙 (docs/operations/principles/johnma-8-fundamentals.md) 을
Toss Tradebot 판정 데이터에 이식한 뷰용 엔드포인트.

엔드포인트:
    GET /api/v1/rulebook/rr-stats              — R:R 분포·평균·목표(≥2) 달성률
    GET /api/v1/rulebook/invalidation-hits     — 물타기 감지 판정 목록
    GET /api/v1/rulebook/rr-calc               — Stateless R:R 계산기 (query param)
    GET /api/v1/rulebook/blue-chip/list        — 5단계 필터 통과 종목 (최신 run)
    GET /api/v1/rulebook/blue-chip/detail/{ticker} — 종목별 5단계 근거 (최신 run)
    POST /api/v1/rulebook/blue-chip/run        — 스크리너 수동 재실행 (관리자)

참조: docs/plans/toss-tradebot-tobe/rulebook-integration.md
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, func, select

from backend.api.auth import require_sniper_token
from backend.api.routes.judgments import _compute_rr
from backend.rulebook.screener import run_blue_chip_screener
from backend.services.db import get_session
from backend.services.models import BlueChipCandidate, BlueChipRun, UserJudgment

router = APIRouter()


class RRBucket(BaseModel):
    """R:R 구간별 카운트."""

    label: str  # "R:R < 1" | "1 ≤ R:R < 2" | "R:R ≥ 2"
    count: int


class RRStats(BaseModel):
    """R:R 분포·평균·강의 권장 (≥2) 달성률."""

    computable_count: int
    avg_rr_ratio: Optional[float]
    median_rr_ratio: Optional[float]
    target_rr_min: float  # 존마 강의 권장 · 2.0
    target_hit_count: int  # R:R ≥ 2.0 판정 수
    target_hit_rate: Optional[float]  # target_hit / computable
    buckets: list[RRBucket]


class InvalidationHitItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    ticker: str
    page_source: str
    hypothesis_id: str
    invalidation_price: Optional[float]
    invalidation_hit_ts: Optional[datetime]
    invalidation_hit_low: Optional[float]
    result_at_horizon: Optional[float]
    horizon_days: int


class RRCalcResult(BaseModel):
    """Stateless R:R 계산기 응답 · UI 실시간 사용."""

    entry: float
    invalidation: float
    target: float
    direction: str  # "long" | "short" | "invalid"
    rr_ratio: Optional[float]
    risk_pct: Optional[float]         # entry 대비 손실 리스크 %
    reward_pct: Optional[float]       # entry 대비 목표 수익 %
    verdict: str                      # "권장 (R:R ≥ 2)" | "재검토 (1~2)" | "위험 (< 1)" | "invalid"


# ─── Endpoints ───────────────────────────────────────────────────


@router.get("/rr-stats", response_model=RRStats)
async def get_rr_stats(days: int = Query(90, ge=7, le=365)):
    """R:R 분포 · 강의 권장 (≥2) 달성률."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with get_session() as session:
        stmt = select(UserJudgment).where(UserJudgment.ts >= cutoff)
        rows = (await session.execute(stmt)).scalars().all()

    rr_values = [
        rr for r in rows
        if (rr := _compute_rr(r.entry_price, r.target_price, r.invalidation_price)) is not None
    ]
    n = len(rr_values)
    avg = sum(rr_values) / n if n else None
    median = sorted(rr_values)[n // 2] if n else None

    target_min = 2.0
    target_hits = sum(1 for x in rr_values if x >= target_min)
    target_rate = (target_hits / n) if n else None

    buckets = [
        RRBucket(label="R:R < 1", count=sum(1 for x in rr_values if x < 1)),
        RRBucket(label="1 ≤ R:R < 2", count=sum(1 for x in rr_values if 1 <= x < 2)),
        RRBucket(label="R:R ≥ 2", count=target_hits),
    ]

    return RRStats(
        computable_count=n,
        avg_rr_ratio=avg,
        median_rr_ratio=median,
        target_rr_min=target_min,
        target_hit_count=target_hits,
        target_hit_rate=target_rate,
        buckets=buckets,
    )


@router.get("/invalidation-hits", response_model=list[InvalidationHitItem])
async def get_invalidation_hits(
    days: int = Query(90, ge=7, le=365),
    limit: int = Query(100, ge=1, le=500),
):
    """물타기 감지 판정 목록 · invalidation 이탈 후에도 보유된 판정."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with get_session() as session:
        stmt = (
            select(UserJudgment)
            .where(
                UserJudgment.ts >= cutoff,
                UserJudgment.invalidation_hit_ts.is_not(None),
            )
            .order_by(desc(UserJudgment.invalidation_hit_ts))
            .limit(limit)
        )
        return (await session.execute(stmt)).scalars().all()


@router.get("/rr-calc", response_model=RRCalcResult)
async def rr_calc(
    entry: float = Query(..., description="진입가"),
    invalidation: float = Query(..., description="반증 가격 (손절 라인)"),
    target: float = Query(..., description="목표가"),
):
    """Stateless R:R 계산기 · UI 실시간 (DB 저장 없음)."""
    if entry <= 0 or invalidation <= 0 or target <= 0:
        raise HTTPException(status_code=400, detail="가격은 양수여야 합니다.")

    rr = _compute_rr(entry, target, invalidation)
    if rr is None:
        return RRCalcResult(
            entry=entry, invalidation=invalidation, target=target,
            direction="invalid", rr_ratio=None,
            risk_pct=None, reward_pct=None,
            verdict="invalid (entry·invalidation·target 관계가 Long/Short 어느 쪽도 아님)",
        )

    if target > entry > invalidation:
        direction = "long"
        risk_pct = (entry - invalidation) / entry
        reward_pct = (target - entry) / entry
    else:
        direction = "short"
        risk_pct = (invalidation - entry) / entry
        reward_pct = (entry - target) / entry

    if rr >= 2.0:
        verdict = f"권장 (R:R {rr:.2f} ≥ 2)"
    elif rr >= 1.0:
        verdict = f"재검토 (R:R {rr:.2f} · 강의 권장 2 미달)"
    else:
        verdict = f"위험 (R:R {rr:.2f} · 손절 > 목표)"

    return RRCalcResult(
        entry=entry, invalidation=invalidation, target=target,
        direction=direction, rr_ratio=rr,
        risk_pct=risk_pct, reward_pct=reward_pct,
        verdict=verdict,
    )


# ─── Blue-Chip 5단계 필터 (Phase E+ · 2026-08-02) ───────────────


class BlueChipItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    name: Optional[str]
    market: Optional[str]
    sector: Optional[str]
    market_cap_krw: Optional[float]
    tier: str  # premium (10조+) | entry (5조+) | none
    close_price: Optional[float]
    revenue_3y_growing: bool
    net_income_3y_growing: bool
    annual_turnaround: bool
    monthly_ma5_above: bool
    monthly_ma5_months_above: int
    pass_count: int
    overall_pass: bool
    reject_reasons: Optional[str]


class BlueChipListResponse(BaseModel):
    run_id: Optional[str]
    run_started_at: Optional[datetime]
    universe_size: int
    passed_count: int
    partial_count: int
    items: list[BlueChipItem]


class BlueChipDetailResponse(BaseModel):
    ticker: str
    latest_snapshots: list[BlueChipItem]   # 최근 N run · 시계열
    conditions_json: Optional[dict]        # 최신 run 상세 pass/fail
    financial_years: Optional[list[str]]
    annual_yoy_pcts: Optional[list[float]]


class BlueChipRunResponse(BaseModel):
    run_id: str
    universe_size: int
    passed: int
    partial: int
    elapsed_sec: float


@router.get("/blue-chip/list", response_model=BlueChipListResponse)
async def get_blue_chip_list(
    min_pass: int = Query(3, ge=1, le=5, description="최소 통과 단계 수 (기본 3+)"),
    only_overall_pass: bool = Query(False, description="5단계 모두 통과만"),
    limit: int = Query(200, ge=1, le=1000),
):
    """5단계 필터 통과 종목 · 최신 run 기준."""
    async with get_session() as session:
        latest_run: Optional[BlueChipRun] = (
            await session.execute(
                select(BlueChipRun).order_by(desc(BlueChipRun.started_at)).limit(1)
            )
        ).scalar_one_or_none()
        if latest_run is None:
            return BlueChipListResponse(
                run_id=None, run_started_at=None,
                universe_size=0, passed_count=0, partial_count=0, items=[],
            )
        stmt = (
            select(BlueChipCandidate)
            .where(BlueChipCandidate.run_id == latest_run.run_id)
            .where(BlueChipCandidate.pass_count >= min_pass)
        )
        if only_overall_pass:
            stmt = stmt.where(BlueChipCandidate.overall_pass.is_(True))
        stmt = stmt.order_by(
            desc(BlueChipCandidate.overall_pass),
            desc(BlueChipCandidate.pass_count),
            desc(BlueChipCandidate.market_cap_krw),
        ).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

    return BlueChipListResponse(
        run_id=latest_run.run_id,
        run_started_at=latest_run.started_at,
        universe_size=latest_run.universe_size,
        passed_count=latest_run.passed_count,
        partial_count=latest_run.partial_count,
        items=[BlueChipItem.model_validate(r) for r in rows],
    )


@router.get("/blue-chip/detail/{ticker}", response_model=BlueChipDetailResponse)
async def get_blue_chip_detail(ticker: str, limit: int = Query(10, ge=1, le=100)):
    """특정 종목의 최근 N run 5단계 근거 시계열."""
    async with get_session() as session:
        rows = (
            await session.execute(
                select(BlueChipCandidate)
                .where(BlueChipCandidate.ticker == ticker)
                .order_by(desc(BlueChipCandidate.created_at))
                .limit(limit)
            )
        ).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"blue-chip snapshot not found for {ticker}")

    latest = rows[0]
    try:
        conds = json.loads(latest.conditions_json) if latest.conditions_json else None
    except json.JSONDecodeError:
        conds = None
    years = latest.financial_years.split(",") if latest.financial_years else None
    yoy = (
        [float(x) for x in latest.annual_yoy_pcts.split(",")]
        if latest.annual_yoy_pcts else None
    )

    return BlueChipDetailResponse(
        ticker=ticker,
        latest_snapshots=[BlueChipItem.model_validate(r) for r in rows],
        conditions_json=conds,
        financial_years=years,
        annual_yoy_pcts=yoy,
    )


@router.post(
    "/blue-chip/run",
    response_model=BlueChipRunResponse,
    dependencies=[Depends(require_sniper_token)],
)
async def trigger_blue_chip_run(limit: Optional[int] = Query(None, ge=1, le=1000)):
    """스크리너 수동 재실행 (관리자) · limit 은 유니버스 상위 N개."""
    result = await run_blue_chip_screener(trigger="manual", limit=limit)
    return BlueChipRunResponse(**result)
