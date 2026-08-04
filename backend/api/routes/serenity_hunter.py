"""Serenity Hunter API 라우터 · Phase L14 v6 (2026-08-04).

Step A 산출물: /verification · /health  (Fable 5 6차 D3 순서 이관)
Step C 산출물: /hunter                    (하드 게이트 · 폐기 · 중간경고 반영)

Fable 5 3차 (2) 이후: /hunter 는 is_deprecation_triggered() true → 자동 rows=[] · 배너 아님.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from backend.discovery.serenity.hunter import (
    is_deprecation_triggered,
    is_gate_open,
    mid_gate_excess_warning,
)
from backend.discovery.serenity.verification import (
    build_buckets,
    build_hero,
    first_mention_events,
)
from backend.services.db import get_session
from backend.services.models import (
    SerenityBenchmarkPrice,
    SerenitySignal,
    SerenityTickerPrice,
    SerenityTweet,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Schemas ────────────────────────────────────────────────────────────────

class HealthReason(BaseModel):
    code: str
    message: str
    since: Optional[datetime] = None


class HealthResponse(BaseModel):
    warn: bool
    reasons: list[HealthReason]
    last_crawl_at: Optional[datetime]
    last_signal_at: Optional[datetime]
    last_backtest_at: Optional[datetime]
    last_price_snapshot_at: Optional[datetime]
    benchmark_fresh: bool


class BucketRow(BaseModel):
    key: str
    n: int
    hit_rate_10pct_3d: Optional[float] = None
    avg_return_3d: Optional[float] = None
    excess_iwm_3d: Optional[float] = None
    is_masked: bool = False


class BucketGroup(BaseModel):
    name: str
    rows: list[BucketRow]


class ConfidencePredictiveCheck(BaseModel):
    top_hit_rate: Optional[float]
    bottom_hit_rate: Optional[float]
    diff_pp: Optional[float]
    top_n: int
    bottom_n: int
    min_n_ok: bool
    predictive_status: str  # "insufficient_n" | "fail" | "pass"


class VerificationHero(BaseModel):
    total_events: int
    valid_events: int
    benchmark_rows_iwm: int
    benchmark_rows_spy: int
    hit_rate_10pct_1d: Optional[float]
    hit_rate_10pct_3d: Optional[float]
    hit_rate_10pct_1d_delisting_as_minus100: Optional[float]
    hit_rate_10pct_3d_delisting_as_minus100: Optional[float]
    avg_raw_return_1d: Optional[float]
    avg_raw_return_3d: Optional[float]
    avg_return_by_window: dict[int, Optional[float]]
    avg_gap_next_open_pct: Optional[float]
    avg_slippage_adjusted_return_1d: Optional[float]
    avg_slippage_adjusted_return_3d: Optional[float]
    avg_cost_adjusted_return_1d: Optional[float]
    avg_cost_adjusted_return_3d: Optional[float]
    benchmark_iwm_avg: dict[int, Optional[float]]
    benchmark_spy_avg: dict[int, Optional[float]]
    excess_return_primary_raw: dict[int, Optional[float]]
    excess_return_primary_adjusted: dict[int, Optional[float]]
    excess_return_reference_raw: dict[int, Optional[float]]
    excess_return_reference_adjusted: dict[int, Optional[float]]
    gate_open: bool
    gate_events_needed: int
    gate_events_have: int
    gate_close_reasons: list[str]
    deprecation_triggered: bool
    mid_gate_excess_warning: bool
    warning_text: Optional[str]


class VerificationResponse(BaseModel):
    hero: VerificationHero
    buckets: list[BucketGroup]
    confidence_predictive_check: ConfidencePredictiveCheck


# ─── Health ─────────────────────────────────────────────────────────────────

async def _health_reasons() -> tuple[list[HealthReason], dict]:
    """건강성 판정 · 24h 이내 신선도 기준."""
    now = datetime.utcnow()
    threshold = now - timedelta(hours=24)
    reasons: list[HealthReason] = []
    meta: dict = {
        "last_crawl_at": None,
        "last_signal_at": None,
        "last_backtest_at": None,
        "last_price_snapshot_at": None,
        "benchmark_fresh": False,
    }

    async with get_session() as session:
        # 마지막 tweet posted_at
        last_tweet = (await session.execute(
            select(func.max(SerenityTweet.posted_at))
        )).scalar_one_or_none()
        meta["last_crawl_at"] = last_tweet
        if last_tweet is None or last_tweet < threshold:
            reasons.append(HealthReason(
                code="stale_crawler", message="트윗 24h 이상 신규 없음", since=last_tweet,
            ))

        # 마지막 signal extracted_at
        last_signal = (await session.execute(
            select(func.max(SerenitySignal.extracted_at))
        )).scalar_one_or_none()
        meta["last_signal_at"] = last_signal
        if last_signal is None or last_signal < threshold:
            reasons.append(HealthReason(
                code="stale_signals", message="signal 24h 이상 신규 없음", since=last_signal,
            ))

        # 마지막 price snapshot fetched_at
        last_price = (await session.execute(
            select(func.max(SerenityTickerPrice.fetched_at))
        )).scalar_one_or_none()
        meta["last_price_snapshot_at"] = last_price
        if last_price is None or last_price < threshold:
            reasons.append(HealthReason(
                code="stale_prices", message="price snapshot 24h 이상 미갱신", since=last_price,
            ))

        # 마지막 backtest computed_at (Step A 이후 매일)
        from backend.services.models import SerenityBacktest
        last_bt = (await session.execute(
            select(func.max(SerenityBacktest.computed_at))
        )).scalar_one_or_none()
        meta["last_backtest_at"] = last_bt

        # benchmark 신선도 (오늘 or 어제 snapshot_date 존재)
        recent_iso = (now - timedelta(days=2)).date().isoformat()
        bench_recent = (await session.execute(
            select(func.count()).select_from(SerenityBenchmarkPrice)
            .where(SerenityBenchmarkPrice.symbol == "IWM")
            .where(SerenityBenchmarkPrice.snapshot_date >= recent_iso)
        )).scalar_one()
        meta["benchmark_fresh"] = int(bench_recent) > 0
        if not meta["benchmark_fresh"]:
            reasons.append(HealthReason(
                code="stale_benchmark", message="IWM benchmark 최근 2일 미갱신",
            ))

    return reasons, meta


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Serenity Hunter 시스템 헬스 · 크론 신선도 · 벤치마크 · 배너 조건 노출."""
    reasons, meta = await _health_reasons()
    return HealthResponse(
        warn=len(reasons) > 0,
        reasons=reasons,
        last_crawl_at=meta["last_crawl_at"],
        last_signal_at=meta["last_signal_at"],
        last_backtest_at=meta["last_backtest_at"],
        last_price_snapshot_at=meta["last_price_snapshot_at"],
        benchmark_fresh=meta["benchmark_fresh"],
    )


# ─── Verification ───────────────────────────────────────────────────────────

@router.get("/verification", response_model=VerificationResponse)
async def verification() -> VerificationResponse:
    """알파 검증 · first_mention 이벤트 전수 사후 성과 (v6 §2.6)."""
    events = await first_mention_events()

    hero_data = await build_hero(events)
    # deprecation / mid_gate 상태는 hero 에 병합 (Fable 5 3차 (2))
    hero_data["deprecation_triggered"] = await is_deprecation_triggered()
    hero_data["mid_gate_excess_warning"] = await mid_gate_excess_warning()
    hero = VerificationHero(**hero_data)

    buckets_raw = await build_buckets(events)
    buckets = [
        BucketGroup(
            name=b["name"],
            rows=[BucketRow(**r) for r in b["rows"]],
        )
        for b in buckets_raw
    ]

    from backend.discovery.serenity.verification import _confidence_tertile
    check = ConfidencePredictiveCheck(**_confidence_tertile(events))

    return VerificationResponse(
        hero=hero,
        buckets=buckets,
        confidence_predictive_check=check,
    )
