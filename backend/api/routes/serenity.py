"""Serenity Influencer 공개 read API · Phase L6~L7 · 2026-08-02.

read-only · 인증 없음 (관리자 편집 없음 · signals·scores 는 크론 자동 갱신).

엔드포인트:
    GET /api/v1/serenity/signals              — Signal Feed (최근 N일 · sentiment 필터)
    GET /api/v1/serenity/tickers              — Ticker Grid (financing_tier 분류)
    GET /api/v1/serenity/tickers/{t}          — 상세
    GET /api/v1/serenity/summary              — 대시보드 요약
    GET /api/v1/serenity/methodology          — 15원칙 원문 md (L7)
    GET /api/v1/serenity/backtest/summary     — 백테스트 통계 (L7)

참조: docs/plans/serenity-integration/01-ui-spec.md §5~8
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, func, select

from backend.discovery.serenity.aggregators import aggregate_signals
from backend.services.db import get_session
from backend.services.models import (
    DiscoverySerenityScore,
    SerenityBacktest,
    SerenitySignal,
    SerenityTweet,
)

router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────


class SignalFeedItem(BaseModel):
    """Signal Feed 항목 · 트윗 컨텍스트 병치."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    tweet_id: int
    ticker: str
    sentiment: str
    thesis_type: Optional[str]
    evidence_type: Optional[str]
    confidence: float
    extracted_reasoning: Optional[str]
    extracted_at: datetime
    tweet_text: Optional[str] = None
    tweet_url: Optional[str] = None
    tweet_posted_at: Optional[datetime] = None


class TickerCardItem(BaseModel):
    """Ticker Grid 항목 · score + aggregate 합쳐 카드용 요약."""

    ticker: str
    financing_tier: Optional[str]
    serenity_tier: Optional[str]
    total_score: int
    auto_avoid: bool
    domain_tags: list[str]
    anti_pattern_flags: list[str]
    mention_count_90d: int
    bullish_pct_90d: float
    last_signal_at: Optional[datetime]
    latest_reasoning: Optional[str] = None


class TickerDetailResponse(BaseModel):
    """L7 상세 페이지 seed · 최소 골격 (checklist 등은 L7 확장)."""

    ticker: str
    score: TickerCardItem
    recent_signals: list[SignalFeedItem]
    backtest_avg: dict[str, Optional[float]]  # return_5d/10d/30d/60d/180d 평균


class SerenitySummary(BaseModel):
    tweets: int
    signals: int
    tickers_scored: int
    tickers_auto_avoid: int
    last_signal_at: Optional[datetime]
    last_tweet_at: Optional[datetime]


# ─── helpers ──────────────────────────────────────────────────────


def _parse_csv(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


async def _score_to_card(
    score: DiscoverySerenityScore,
    *,
    latest_reasoning: Optional[str] = None,
) -> TickerCardItem:
    agg = await aggregate_signals(score.ticker, days=90)
    return TickerCardItem(
        ticker=score.ticker,
        financing_tier=score.financing_tier,
        serenity_tier=score.serenity_tier,
        total_score=score.total_score,
        auto_avoid=score.auto_avoid,
        domain_tags=_parse_csv(score.domain_tags),
        anti_pattern_flags=_parse_csv(score.anti_pattern_flags),
        mention_count_90d=agg["mention_count"],
        bullish_pct_90d=agg["bullish_pct"],
        last_signal_at=agg["last_signal_at"],
        latest_reasoning=latest_reasoning,
    )


# ─── Endpoints ────────────────────────────────────────────────────


@router.get("/signals", response_model=list[SignalFeedItem])
async def list_signals(
    days: int = Query(14, ge=1, le=365),
    sentiment: Optional[str] = Query(None, description="bullish|bearish|neutral|calibration"),
    ticker: Optional[str] = Query(None, description="특정 티커만"),
    limit: int = Query(100, ge=1, le=500),
):
    """Signal Feed · 최근 N일 · sentiment/ticker 선택 필터."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with get_session() as session:
        stmt = (
            select(SerenitySignal, SerenityTweet)
            .join(SerenityTweet, SerenityTweet.tweet_id == SerenitySignal.tweet_id, isouter=True)
            .where(SerenitySignal.extracted_at >= cutoff)
        )
        if sentiment:
            stmt = stmt.where(SerenitySignal.sentiment == sentiment)
        if ticker:
            stmt = stmt.where(SerenitySignal.ticker == ticker.upper())
        stmt = stmt.order_by(desc(SerenitySignal.extracted_at)).limit(limit)
        rows = (await session.execute(stmt)).all()

    items: list[SignalFeedItem] = []
    for sig, tw in rows:
        items.append(SignalFeedItem(
            id=sig.id,
            tweet_id=sig.tweet_id,
            ticker=sig.ticker,
            sentiment=sig.sentiment,
            thesis_type=sig.thesis_type,
            evidence_type=sig.evidence_type,
            confidence=sig.confidence,
            extracted_reasoning=sig.extracted_reasoning,
            extracted_at=sig.extracted_at,
            tweet_text=tw.text if tw else None,
            tweet_url=tw.url if tw else None,
            tweet_posted_at=tw.posted_at if tw else None,
        ))
    return items


@router.get("/tickers", response_model=list[TickerCardItem])
async def list_tickers(
    min_score: Optional[int] = Query(None, description="최소 total_score"),
    include_avoid: bool = Query(True, description="auto_avoid 포함 여부"),
    limit: int = Query(200, ge=1, le=500),
):
    """Ticker Grid · discovery_serenity_scores 정렬 + 90일 aggregate 병합."""
    async with get_session() as session:
        stmt = select(DiscoverySerenityScore)
        if not include_avoid:
            stmt = stmt.where(DiscoverySerenityScore.auto_avoid.is_(False))
        if min_score is not None:
            stmt = stmt.where(DiscoverySerenityScore.total_score >= min_score)
        stmt = stmt.order_by(
            desc(DiscoverySerenityScore.total_score),
            DiscoverySerenityScore.ticker,
        ).limit(limit)
        scores = list((await session.execute(stmt)).scalars().all())

    items: list[TickerCardItem] = []
    for s in scores:
        items.append(await _score_to_card(s))
    return items


@router.get("/tickers/{ticker}", response_model=TickerDetailResponse)
async def get_ticker_detail(ticker: str, recent_limit: int = Query(10, ge=1, le=100)):
    """티커 상세 · L7 페이지 데이터 소스."""
    ticker = ticker.upper()
    async with get_session() as session:
        score = (await session.execute(
            select(DiscoverySerenityScore).where(DiscoverySerenityScore.ticker == ticker)
        )).scalar_one_or_none()
        if score is None:
            raise HTTPException(status_code=404, detail=f"ticker not found: {ticker}")

        # 최근 signals + 트윗 컨텍스트
        stmt = (
            select(SerenitySignal, SerenityTweet)
            .join(SerenityTweet, SerenityTweet.tweet_id == SerenitySignal.tweet_id, isouter=True)
            .where(SerenitySignal.ticker == ticker)
            .order_by(desc(SerenitySignal.extracted_at))
            .limit(recent_limit)
        )
        sig_rows = (await session.execute(stmt)).all()

        # backtest 평균 (최근 90일)
        cutoff = datetime.utcnow() - timedelta(days=90)
        avg_stmt = (
            select(
                func.avg(SerenityBacktest.return_5d),
                func.avg(SerenityBacktest.return_10d),
                func.avg(SerenityBacktest.return_30d),
                func.avg(SerenityBacktest.return_60d),
                func.avg(SerenityBacktest.return_180d),
            )
            .where(
                SerenityBacktest.ticker == ticker,
                SerenityBacktest.computed_at >= cutoff,
            )
        )
        avg_row = (await session.execute(avg_stmt)).one()

    recent_signals = [
        SignalFeedItem(
            id=sig.id, tweet_id=sig.tweet_id, ticker=sig.ticker,
            sentiment=sig.sentiment, thesis_type=sig.thesis_type,
            evidence_type=sig.evidence_type, confidence=sig.confidence,
            extracted_reasoning=sig.extracted_reasoning,
            extracted_at=sig.extracted_at,
            tweet_text=tw.text if tw else None,
            tweet_url=tw.url if tw else None,
            tweet_posted_at=tw.posted_at if tw else None,
        )
        for sig, tw in sig_rows
    ]
    latest_reasoning = recent_signals[0].extracted_reasoning if recent_signals else None
    card = await _score_to_card(score, latest_reasoning=latest_reasoning)

    return TickerDetailResponse(
        ticker=ticker,
        score=card,
        recent_signals=recent_signals,
        backtest_avg={
            "return_5d": float(avg_row[0]) if avg_row[0] is not None else None,
            "return_10d": float(avg_row[1]) if avg_row[1] is not None else None,
            "return_30d": float(avg_row[2]) if avg_row[2] is not None else None,
            "return_60d": float(avg_row[3]) if avg_row[3] is not None else None,
            "return_180d": float(avg_row[4]) if avg_row[4] is not None else None,
        },
    )


# ─── L7 · methodology 원문 ────────────────────────────────────────


class MethodologyResponse(BaseModel):
    source: str
    text: str
    bytes: int


def _resolve_methodology_path() -> Optional[Path]:
    """SERENITY_TRACKER_DIR 아래 references/methodology.md 경로 후보 탐색."""
    env_dir = os.environ.get("SERENITY_TRACKER_DIR")
    candidates: list[Path] = []
    if env_dir:
        candidates.append(Path(env_dir).expanduser() / "serenity-aleabitoreddit" / "references" / "methodology.md")
        candidates.append(Path(env_dir).expanduser() / "references" / "methodology.md")
    # 프로젝트 root vendor 경로 (submodule 기본)
    project_root = Path(__file__).resolve().parents[3]
    candidates.append(project_root / "vendor" / "serenity-tracker" / "serenity-aleabitoreddit" / "references" / "methodology.md")
    candidates.append(project_root / "vendor" / "serenity-tracker" / "references" / "methodology.md")
    for c in candidates:
        if c.exists():
            return c
    return None


@router.get("/methodology", response_model=MethodologyResponse)
async def get_methodology():
    """15원칙 프레임 원문 · vendor/serenity-tracker submodule 에서 read."""
    path = _resolve_methodology_path()
    if path is None:
        raise HTTPException(status_code=404, detail="methodology.md 파일 없음 · submodule 미초기화")
    text = path.read_text(encoding="utf-8")
    return MethodologyResponse(source=str(path), text=text, bytes=len(text.encode("utf-8")))


# ─── L7 · Backtest summary ────────────────────────────────────────


class BacktestBucket(BaseModel):
    key: str
    count: int
    avg_return_5d: Optional[float]
    avg_return_10d: Optional[float]
    avg_return_30d: Optional[float]
    avg_return_60d: Optional[float]
    avg_return_180d: Optional[float]


class BacktestSummary(BaseModel):
    total_backtests: int
    overall: BacktestBucket                  # 전체 평균
    by_sentiment: list[BacktestBucket]
    by_financing_tier: list[BacktestBucket]
    top_tickers_60d: list[BacktestBucket]    # 60일 평균 상위 10 티커


async def _bucket_stats(key: str, rows: list) -> BacktestBucket:
    """rows 는 [SerenityBacktest, ...] · 평균 return 필드 계산."""
    def _avg(field: str) -> Optional[float]:
        vals = [getattr(r, field) for r in rows if getattr(r, field) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    return BacktestBucket(
        key=key,
        count=len(rows),
        avg_return_5d=_avg("return_5d"),
        avg_return_10d=_avg("return_10d"),
        avg_return_30d=_avg("return_30d"),
        avg_return_60d=_avg("return_60d"),
        avg_return_180d=_avg("return_180d"),
    )


@router.get("/backtest/summary", response_model=BacktestSummary)
async def get_backtest_summary(days: int = Query(180, ge=7, le=365)):
    """백테스트 통계 · sentiment/financing tier/top-ticker 분류."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    async with get_session() as session:
        # backtest × signal(sentiment) × score(financing_tier) join
        stmt = (
            select(SerenityBacktest, SerenitySignal, DiscoverySerenityScore)
            .join(SerenitySignal, SerenitySignal.id == SerenityBacktest.signal_id, isouter=True)
            .join(
                DiscoverySerenityScore,
                DiscoverySerenityScore.ticker == SerenityBacktest.ticker,
                isouter=True,
            )
            .where(SerenityBacktest.computed_at >= cutoff)
        )
        joined = (await session.execute(stmt)).all()

    all_bt = [row[0] for row in joined]
    total = len(all_bt)
    overall = await _bucket_stats("overall", all_bt)

    # sentiment 별
    sentiment_map: dict[str, list] = {}
    for bt, sig, _score in joined:
        if sig is None:
            continue
        sentiment_map.setdefault(sig.sentiment, []).append(bt)
    by_sent = [await _bucket_stats(k, v) for k, v in sorted(sentiment_map.items())]

    # financing tier 별
    tier_map: dict[str, list] = {}
    for bt, _sig, score in joined:
        if score is None or score.financing_tier is None:
            continue
        tier_map.setdefault(score.financing_tier, []).append(bt)
    by_tier = [
        await _bucket_stats(k, v)
        for k, v in sorted(tier_map.items(), key=lambda x: "SABCDF".index(x[0]) if x[0] in "SABCDF" else 99)
    ]

    # ticker 별 60d 평균 상위 10
    ticker_map: dict[str, list] = {}
    for bt, _sig, _score in joined:
        ticker_map.setdefault(bt.ticker, []).append(bt)
    ticker_buckets: list[BacktestBucket] = []
    for tk, bts in ticker_map.items():
        ticker_buckets.append(await _bucket_stats(tk, bts))
    ticker_buckets.sort(
        key=lambda b: (b.avg_return_60d if b.avg_return_60d is not None else -1e9),
        reverse=True,
    )

    return BacktestSummary(
        total_backtests=total,
        overall=overall,
        by_sentiment=by_sent,
        by_financing_tier=by_tier,
        top_tickers_60d=ticker_buckets[:10],
    )


@router.get("/summary", response_model=SerenitySummary)
async def get_summary():
    """랜딩 상단 카운터·최근 갱신 시각."""
    async with get_session() as session:
        tweets = (await session.execute(select(func.count(SerenityTweet.id)))).scalar_one()
        signals = (await session.execute(select(func.count(SerenitySignal.id)))).scalar_one()
        tickers = (await session.execute(select(func.count(DiscoverySerenityScore.ticker)))).scalar_one()
        avoid = (await session.execute(
            select(func.count(DiscoverySerenityScore.ticker))
            .where(DiscoverySerenityScore.auto_avoid.is_(True))
        )).scalar_one()
        last_signal = (await session.execute(select(func.max(SerenitySignal.extracted_at)))).scalar_one_or_none()
        last_tweet = (await session.execute(select(func.max(SerenityTweet.posted_at)))).scalar_one_or_none()

    return SerenitySummary(
        tweets=tweets,
        signals=signals,
        tickers_scored=tickers,
        tickers_auto_avoid=avoid,
        last_signal_at=last_signal,
        last_tweet_at=last_tweet,
    )
