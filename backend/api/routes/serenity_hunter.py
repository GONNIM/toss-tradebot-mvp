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
    hunter_rows,
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


class HunterRow(BaseModel):
    ticker: str
    industry: Optional[str] = None
    sector: Optional[str] = None
    first_mention_at: Optional[str] = None
    latest_signal_at: Optional[str] = None
    mentions_today: int = 0
    mentions_7d: int = 0
    mentions_28d: int = 0
    mentions_90d: int = 0
    # avg_confidence_recent 삭제 (v6 L14+ · predictive_status=fail 확정)
    latest_thesis: Optional[str] = None
    bull_pct_90d: float = 0.0
    market_cap: Optional[float] = None
    market_cap_tier: str = "unknown"
    avg_dollar_volume_20d: Optional[float] = None
    order_pct_of_adv_1M: Optional[float] = None
    passes_liquidity: bool = False
    vs_prior_close_pct: Optional[float] = None
    gain_since_first_mention_pct: Optional[float] = None
    stance: str = "neutral"
    is_new: bool = False
    is_avoid_new: bool = False


class HunterResponse(BaseModel):
    gate_open: bool
    deprecation_triggered: bool
    mid_gate_warning: bool
    gate_close_reasons: list[str] = []
    deprecation_recommended: bool = False
    rows: list[HunterRow] = []


# ─── Action Cards (L14+ · 2026-08-05 · 사용자 지시서) ─────────────────

class ActionCard(BaseModel):
    ticker: str
    tier: Optional[str] = None
    tier_rank: int = 99
    financing_tier: Optional[str] = None
    bull_pct: float
    mentions_7d: int
    mentions_90d: int
    industry: Optional[str] = None
    sector: Optional[str] = None
    sector_overlap: bool = False
    last_close: float
    first_mention_at: Optional[str] = None
    entry_limit: float
    entry_krw: float
    qty: int
    sl_price: float
    sl_days: int
    tp_trigger_price: float
    trail_pct: float
    min_rr: float
    min_rr_warning: bool


class WatchOnlyItem(BaseModel):
    ticker: str
    industry: Optional[str] = None
    bull_pct: float
    mentions_7d: int
    mentions_90d: int
    reason: str


class ExcludedItem(BaseModel):
    ticker: str
    reason: str


class ActionCardFilters(BaseModel):
    bull_pct_min: float
    mentions_90d_min: int
    mentions_7d_min: int
    shell_industries: list[str]


class ActionRiskParams(BaseModel):
    slippage_limit_pct: float
    sl_pct: float
    sl_days: int
    tp_trigger_pct: float
    trail_pct: float
    position_krw: float
    min_rr_warning: float


class ActionCardsResponse(BaseModel):
    as_of: str
    fx_rate: float
    fx_source: str
    cards: list[ActionCard] = []
    cards_hidden: list[ActionCard] = []
    rest_count: int = 0
    watch_only: list[WatchOnlyItem] = []
    excluded: list[ExcludedItem] = []
    filters: ActionCardFilters
    risk: ActionRiskParams


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


# ─── Hunter (Step C) ────────────────────────────────────────────────────────

@router.get("/hunter", response_model=HunterResponse)
async def hunter() -> HunterResponse:
    """발굴 리스트 · 게이트+폐기 판정 반영 (v6 §2.6).

    Fable 5 3차 (2a): deprecation_triggered=true 시 자동 rows=[] (배너 아님).

    로컬 dev 편의: env `SERENITY_HUNTER_SKIP_HEALTH_GATE=true` 시 health warn 무시.
    로컬 크론 미실행이라 stale 판정 발동 · UI 검증 불가한 문제 해소.
    서버 default 미설정 · 자연 정상 작동.
    """
    import os
    skip_health = os.environ.get("SERENITY_HUNTER_SKIP_HEALTH_GATE", "").lower() in {"1", "true", "yes"}
    # health 상태 반영 (warn=true → 게이트 강제 close · v6 §2.7)
    reasons, _meta = await _health_reasons()
    health_warn = (len(reasons) > 0) and (not skip_health)

    # hunter_rows 내부 게이트 판정 · 여기 health_warn 은 별도 재판정 필요
    if health_warn:
        # 이 케이스도 gate close · rows=[]
        result = {
            "gate_open": False,
            "deprecation_triggered": False,
            "mid_gate_warning": False,
            "gate_close_reasons": ["health_warn"],
            "deprecation_recommended": False,
            "rows": [],
        }
    else:
        result = await hunter_rows()

    return HunterResponse(
        gate_open=result["gate_open"],
        deprecation_triggered=result["deprecation_triggered"],
        mid_gate_warning=result["mid_gate_warning"],
        gate_close_reasons=result.get("gate_close_reasons", []),
        deprecation_recommended=result.get("deprecation_recommended", False),
        rows=[HunterRow(**r) for r in result.get("rows", [])],
    )


# ─── Action Cards endpoint (L14+ · 2026-08-05) ───────────────────────

@router.get("/action-cards", response_model=ActionCardsResponse)
async def action_cards() -> ActionCardsResponse:
    """오늘의 실행 카드 · Serenity Hunter 페이지 최상단 (지시서 §1).

    필터: bull_pct≥70 · m90≥10 · m7≥2 · auto_avoid/anti_pattern 제외 ·
    industry != Shell Companies · 가격 존재 (없으면 watch_only 분리).
    계산: 매수 상한가·수량·손절·TP (constants.py 상수).
    """
    from backend.discovery.serenity.action_cards import build_action_cards
    data = await build_action_cards()
    return ActionCardsResponse(
        as_of=data["as_of"],
        fx_rate=data["fx_rate"],
        fx_source=data["fx_source"],
        cards=[ActionCard(**c) for c in data["cards"]],
        cards_hidden=[ActionCard(**c) for c in data.get("cards_hidden", [])],
        rest_count=data["rest_count"],
        watch_only=[WatchOnlyItem(**w) for w in data["watch_only"]],
        excluded=[ExcludedItem(**e) for e in data["excluded"]],
        filters=ActionCardFilters(**data["filters"]),
        risk=ActionRiskParams(**data["risk"]),
    )
