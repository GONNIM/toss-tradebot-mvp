"""Serenity Influencer 공개 read API · Phase L6 · 2026-08-02.

read-only · 인증 없음 (관리자 편집 없음 · signals·scores 는 크론 자동 갱신).

엔드포인트:
    GET /api/v1/serenity/signals      — Signal Feed (최근 N일 · sentiment 필터)
    GET /api/v1/serenity/tickers      — Ticker Grid (financing_tier 분류)
    GET /api/v1/serenity/tickers/{t}  — 상세 (L7 예정 · 최소 skeleton 포함)
    GET /api/v1/serenity/summary      — 대시보드 요약 (tweets/signals/tickers count)

참조: docs/plans/serenity-integration/01-ui-spec.md §5
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
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
