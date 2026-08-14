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
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
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
    horizon_days: int = Field(default=7, ge=1, le=3650)  # 최대 10년 (장기 분할 계획 지원)
    mood: Literal["cool", "neutral", "revenge", "fomo"] = "neutral"
    market_regime: Optional[str] = None  # None 이면 자동 태깅
    entry_price: Optional[float] = Field(default=None, description="Rulebook R:R 계산용 (선택).")
    # 전술 격벽 (Fable 5 · 2026-08-14) · 생성 후 수정 불가 · supersede 만 가능
    strategy: Literal["core", "swing", "event"] = Field(
        ..., description="core (장기 · 최후 방어선) · swing (단기 · 타이트 손절) · event (사건 조건)"
    )
    qty: Optional[float] = Field(default=None, description="트랑셰 수량 (선택 · 소수점 지원).")


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
    entry_price: Optional[float] = None
    result_at_horizon: Optional[float]
    result_computed_at: Optional[datetime]
    invalidation_hit_ts: Optional[datetime] = None
    invalidation_hit_low: Optional[float] = None
    git_sha: Optional[str]
    # Supersede · 티커당 1건 원칙 (2026-08-14)
    superseded_by_id: Optional[int] = None
    superseded_at: Optional[datetime] = None
    supersede_reason: Optional[str] = None
    updated_history: Optional[str] = None
    # 전술 격벽 (2026-08-14) · 수정 불가 · supersede 만
    strategy: Optional[str] = None
    qty: Optional[float] = None

    # SQLite func.now() 저장 시 naive UTC 반환 → 명시 UTC 마킹 (Z suffix)
    # 브라우저 new Date() 가 로컬 (KST) 로 자동 변환 · 2026-08-14 KST 표기 사고 대응
    @field_validator("ts", "result_computed_at", "invalidation_hit_ts", "superseded_at", mode="before")
    @classmethod
    def _mark_utc(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

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
    # Rulebook 확장 (Phase E · 2026-08-02 · 존마 원칙 2·3)
    avg_rr_ratio: Optional[float] = None       # entry·target·invalidation 있는 판정만 · 평균 R:R
    rr_computable_count: int = 0               # R:R 계산 가능한 판정 수
    invalidation_hit_count: int = 0            # invalidation 이탈 감지 판정 수
    invalidation_hit_rate: Optional[float] = None  # 물타기율 = 이탈/전체 (전체 0 이면 None)


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
            entry_price=payload.entry_price,
            git_sha=git_sha[:40] if git_sha else None,
            strategy=payload.strategy,
            qty=payload.qty,
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
    active_only: bool = Query(False, description="True 시 superseded 판정 제외"),
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
        if active_only:
            stmt = stmt.where(UserJudgment.superseded_by_id.is_(None))
        stmt = stmt.order_by(desc(UserJudgment.ts)).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()


# ─── Supersede · 티커당 1건 원칙 (2026-08-14 · Fable 5) ───────────────


class SupersedeRequest(BaseModel):
    by_id: int = Field(..., description="이 판정을 대체하는 신규 판정 id")
    reason: str = Field(..., min_length=1, max_length=200)


@router.post("/{judgment_id}/supersede", response_model=JudgmentOut)
async def supersede_judgment(judgment_id: int, payload: SupersedeRequest):
    """판정 대체 마킹 · append-only · 삭제 금지.

    Fable 5 (2026-08-14): 티커당 판정 1건 원칙.
    positions 3건이 manual 3건으로 대체되는 케이스 등.
    """
    async with get_session() as session:
        row = (await session.execute(
            select(UserJudgment).where(UserJudgment.id == judgment_id)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"판정 id={judgment_id} 없음")
        if row.superseded_by_id is not None:
            raise HTTPException(
                status_code=409,
                detail=f"이미 supersede 됨 · by_id={row.superseded_by_id}",
            )
        # by_id 존재 확인
        new_row = (await session.execute(
            select(UserJudgment).where(UserJudgment.id == payload.by_id)
        )).scalar_one_or_none()
        if new_row is None:
            raise HTTPException(status_code=404, detail=f"by_id={payload.by_id} 판정 없음")
        if new_row.ticker != row.ticker:
            raise HTTPException(
                status_code=400,
                detail=f"티커 불일치 · {row.ticker} → {new_row.ticker} · supersede 는 동일 티커만",
            )

        row.superseded_by_id = payload.by_id
        row.superseded_at = datetime.utcnow()
        row.supersede_reason = payload.reason
        await session.commit()
        await session.refresh(row)
        return row


class JudgmentPatch(BaseModel):
    """판정 갱신 · 이력 append (updated_history) · strategy 는 수정 불가."""
    invalidation_price: Optional[float] = None
    target_price: Optional[float] = None
    thesis_md: Optional[str] = None
    horizon_days: Optional[int] = Field(default=None, ge=1, le=3650)
    mood: Optional[Literal["cool", "neutral", "revenge", "fomo"]] = None
    qty: Optional[float] = None
    change_note: str = Field(..., min_length=1, max_length=200, description="변경 사유")


@router.patch("/{judgment_id}", response_model=JudgmentOut)
async def patch_judgment(judgment_id: int, payload: JudgmentPatch):
    """판정 필드 갱신 · updated_history 에 이전 값·변경 사유 append.

    Fable 5: 첫 기록 오기 수정 허용 · 이력 남김 · 이후 하향 조정 금지 판정은 사용자 책임.
    """
    import json as _json

    async with get_session() as session:
        row = (await session.execute(
            select(UserJudgment).where(UserJudgment.id == judgment_id)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"판정 id={judgment_id} 없음")
        if row.superseded_by_id is not None:
            raise HTTPException(
                status_code=409,
                detail=f"superseded 판정은 갱신 불가 · by_id={row.superseded_by_id}",
            )

        history: list[dict] = []
        if row.updated_history:
            try:
                history = _json.loads(row.updated_history)
            except (ValueError, TypeError):
                history = []
        entry: dict = {
            "at": datetime.now(timezone.utc).isoformat(),
            "note": payload.change_note,
            "before": {},
            "after": {},
        }
        # exclude_unset · 명시 전송된 필드만 (null 포함 · 미전송 제외)
        # (2026-08-14 · target 비우기 사고 fix · Pydantic 부분 업데이트 "없음 vs 지움" 구분)
        patched = payload.model_dump(exclude_unset=True)
        for field in ("invalidation_price", "target_price", "thesis_md",
                      "horizon_days", "mood", "qty"):
            if field not in patched:
                continue  # 미전송 · 유지
            new_val = patched[field]
            old_val = getattr(row, field)
            if old_val != new_val:
                entry["before"][field] = old_val
                entry["after"][field] = new_val
                setattr(row, field, new_val)  # null 명시 시 실제 null 저장

        if not entry["after"]:
            raise HTTPException(status_code=400, detail="변경 사항 없음")

        history.append(entry)
        row.updated_history = _json.dumps(history, ensure_ascii=False)
        await session.commit()
        await session.refresh(row)
        return row


@router.get("/baseline", response_model=Baseline)
async def get_baseline(days: int = Query(90, ge=7, le=365)):
    """판정 정확도 baseline · Stage 2 진입 KPI 근거.

    3분류 (Fable 5 · 2026-08-14):
    - active (진행 중): superseded_by_id IS NULL AND result_at_horizon IS NULL
    - closed (청산 완료): result_at_horizon IS NOT NULL → 성적 집계 대상
    - superseded (정리): superseded_by_id IS NOT NULL → 모든 집계 제외

    superseded 는 정리 작업이지 판정이 아니므로 모든 KPI 에서 제외.
    supersede 생성 시 어떤 KPI 도 개선되지 않아야 함 (부풀림 방지).
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with get_session() as session:
        stmt = (
            select(UserJudgment)
            .where(UserJudgment.ts >= cutoff)
            .where(UserJudgment.superseded_by_id.is_(None))  # 모든 집계에서 superseded 제외
        )
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

    # Rulebook 확장 · R:R 평균 (entry·target·invalidation 모두 있는 판정)
    rr_values = [
        rr for r in rows
        if (rr := _compute_rr(r.entry_price, r.target_price, r.invalidation_price)) is not None
    ]
    rr_computable_count = len(rr_values)
    avg_rr_ratio = (sum(rr_values) / rr_computable_count) if rr_computable_count else None

    # Rulebook 확장 · 물타기율 (invalidation 이탈 감지 판정)
    invalidation_hit_count = sum(1 for r in rows if r.invalidation_hit_ts is not None)
    invalidation_hit_rate = (invalidation_hit_count / total) if total else None

    return Baseline(
        total_count=total,
        computed_count=computed_count,
        win_rate=win_rate,
        avg_return=avg_return,
        mood_distribution=mood_dist,
        page_source_distribution=page_dist,
        avg_rr_ratio=avg_rr_ratio,
        rr_computable_count=rr_computable_count,
        invalidation_hit_count=invalidation_hit_count,
        invalidation_hit_rate=invalidation_hit_rate,
    )


def _compute_rr(
    entry: Optional[float],
    target: Optional[float],
    invalidation: Optional[float],
) -> Optional[float]:
    """Long/Short 자동 판별 R:R 계산 · 세 값 모두 있고 유효할 때만.

    Long: target > entry > invalidation
        R:R = (target - entry) / (entry - invalidation)
    Short: target < entry < invalidation
        R:R = (entry - target) / (invalidation - entry)
    그 외: None (계산 불가 · Rulebook 재검토 대상)
    """
    if entry is None or target is None or invalidation is None:
        return None
    if target > entry > invalidation:
        risk = entry - invalidation
        return (target - entry) / risk if risk > 0 else None
    if target < entry < invalidation:
        risk = invalidation - entry
        return (entry - target) / risk if risk > 0 else None
    return None


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
