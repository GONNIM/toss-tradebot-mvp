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

from backend.discovery.serenity.aggregators import (
    active_tickers,
    aggregate_signals,
    aggregate_ticker_full,
)
from backend.services.db import get_session
from backend.services.models import (
    DiscoverySerenityScore,
    SerenityBacktest,
    SerenitySignal,
    SerenityTickerPrice,
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


class StanceBreakdown(BaseModel):
    bull: int = 0
    bear: int = 0
    neu: int = 0
    cal: int = 0


class TickerCardItem(BaseModel):
    """Ticker Grid 항목 · 이미지 UX 형식 (mentions rolling window + stance today).

    - seed 있으면 tier/score/anti_pattern/domain 필드 채움 · 없으면 None/[].
    - overall_stance: bullish | bearish | mixed | neutral (90일 다수결).
    - vs_prior_close: yfinance 배치 저장 컬럼 (Phase 2 · 현재는 None).
    """

    ticker: str
    financing_tier: Optional[str]
    serenity_tier: Optional[str]
    total_score: int
    auto_avoid: bool
    domain_tags: list[str]
    anti_pattern_flags: list[str]

    # Rolling window mentions (이미지 · today · 7d · 28d)
    mentions_today: int
    mentions_7d: int
    mentions_28d: int
    mention_count_90d: int
    bullish_pct_90d: float

    # Stance breakdown (오늘)
    stance_today: StanceBreakdown

    # Overall stance · UI 상단 배지 (▲/▼/• )
    overall_stance: str            # bullish | bearish | mixed | neutral
    thesis_types: list[str] = []   # 90일 관측된 thesis_type 집합

    # Meta
    first_mention_at: Optional[datetime]
    last_signal_at: Optional[datetime]
    latest_reasoning: Optional[str] = None

    # Phase 2 · vs prior close (yfinance 배치 · 아직 채워지지 않음)
    vs_prior_close_pct: Optional[float] = None


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


async def _load_price_map(tickers: list[str]) -> dict[str, float]:
    """티커 → vs_prior_close_pct 매핑 (SerenityTickerPrice 배치 결과)."""
    if not tickers:
        return {}
    async with get_session() as session:
        rows = (await session.execute(
            select(SerenityTickerPrice.ticker, SerenityTickerPrice.vs_prior_close_pct)
            .where(SerenityTickerPrice.ticker.in_(tickers))
        )).all()
    return {r[0]: r[1] for r in rows if r[1] is not None}


async def _score_to_card(
    score: DiscoverySerenityScore,
    *,
    latest_reasoning: Optional[str] = None,
    vs_prior_close_pct: Optional[float] = None,
) -> TickerCardItem:
    agg = await aggregate_ticker_full(score.ticker)
    return TickerCardItem(
        ticker=score.ticker,
        financing_tier=score.financing_tier,
        serenity_tier=score.serenity_tier,
        total_score=score.total_score,
        auto_avoid=score.auto_avoid,
        domain_tags=_parse_csv(score.domain_tags),
        anti_pattern_flags=_parse_csv(score.anti_pattern_flags),
        mentions_today=agg["mentions_today"],
        mentions_7d=agg["mentions_7d"],
        mentions_28d=agg["mentions_28d"],
        mention_count_90d=agg["mentions_90d"],
        bullish_pct_90d=agg["overall_bullish_pct"],
        stance_today=StanceBreakdown(**agg["stance_today"]),
        overall_stance=agg["overall_stance"],
        thesis_types=agg["thesis_types"],
        first_mention_at=agg["first_mention_at"],
        last_signal_at=agg["last_signal_at"],
        latest_reasoning=latest_reasoning,
        vs_prior_close_pct=vs_prior_close_pct,
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
    days: int = Query(90, ge=1, le=365, description="signal aggregate 윈도우"),
    min_score: Optional[int] = Query(None, description="최소 total_score (seed 있는 티커만 필터)"),
    include_avoid: bool = Query(True, description="auto_avoid 포함 여부"),
    include_unscored: bool = Query(True, description="seed 없는 언급 티커도 포함"),
    limit: int = Query(500, ge=1, le=2000),
):
    """Ticker Grid · seed 티커 + Serenity 가 언급한 모든 티커 union.

    정렬:
      1. seed 있고 total_score>0 → total_score desc
      2. seed 없는 언급 티커 → mention_count desc
      3. 이후 알파벳
    """
    # 1) seed 티커 로드
    async with get_session() as session:
        seed_stmt = select(DiscoverySerenityScore)
        if not include_avoid:
            seed_stmt = seed_stmt.where(DiscoverySerenityScore.auto_avoid.is_(False))
        if min_score is not None:
            seed_stmt = seed_stmt.where(DiscoverySerenityScore.total_score >= min_score)
        seed_scores = list((await session.execute(seed_stmt)).scalars().all())
    seed_by_ticker: dict[str, DiscoverySerenityScore] = {s.ticker: s for s in seed_scores}

    # 2) signals 에서 언급된 모든 티커 (최근 N일 · 확장 가능하도록 별도 인자)
    signal_tickers: set[str] = set()
    if include_unscored:
        signal_tickers = set(await active_tickers(days=days))

    # union · seed 있으면 seed 우선 카드 · 없으면 unscored 카드
    all_tickers = sorted(set(seed_by_ticker.keys()) | signal_tickers)

    # 가격 스냅샷 map (yfinance 배치 · 존재 티커만 값 있음)
    price_map = await _load_price_map(all_tickers)

    items: list[TickerCardItem] = []
    for tk in all_tickers:
        seed = seed_by_ticker.get(tk)
        vs_prior = price_map.get(tk)
        if seed is not None:
            card = await _score_to_card(seed, vs_prior_close_pct=vs_prior)
            # 90일 언급 없는 seed 티커 제외 (사용자 지시 · UI 노이즈)
            if card.mention_count_90d == 0:
                continue
            items.append(card)
        else:
            # unscored · seed 없이 aggregate_ticker_full 로 카드 구성 (동일 UX)
            agg = await aggregate_ticker_full(tk)
            items.append(TickerCardItem(
                ticker=tk,
                financing_tier=None,
                serenity_tier=None,
                total_score=0,
                auto_avoid=False,
                domain_tags=[],
                anti_pattern_flags=[],
                mentions_today=agg["mentions_today"],
                mentions_7d=agg["mentions_7d"],
                mentions_28d=agg["mentions_28d"],
                mention_count_90d=agg["mentions_90d"],
                bullish_pct_90d=agg["overall_bullish_pct"],
                stance_today=StanceBreakdown(**agg["stance_today"]),
                overall_stance=agg["overall_stance"],
                thesis_types=agg["thesis_types"],
                first_mention_at=agg["first_mention_at"],
                last_signal_at=agg["last_signal_at"],
                latest_reasoning=None,
                vs_prior_close_pct=vs_prior,
            ))

    # 3) 정렬 (이미지 UX · By Mentions Today · 그 다음 rolling window)
    #    seed 있고 total_score>0 은 여전히 상단 유지 · 그 안에서 mentions_today desc
    def _key(x: TickerCardItem) -> tuple[int, int, int, int, int, str]:
        seeded_high = 1 if (x.total_score > 0) else 0
        return (
            -seeded_high,
            -x.total_score,
            -x.mentions_today,
            -x.mentions_7d,
            -x.mention_count_90d,
            x.ticker,
        )

    items.sort(key=_key)
    return items[:limit]


@router.get("/tickers/{ticker}", response_model=TickerDetailResponse)
async def get_ticker_detail(ticker: str, recent_limit: int = Query(10, ge=1, le=100)):
    """티커 상세 · L7 페이지 데이터 소스.

    seed 있으면 score 카드 + 상세 · seed 없어도 signals 언급 있으면 unscored 카드로 표시.
    "최적 종목 찾기" UX · 신규 매핑 티커 접근 지원.
    """
    ticker = ticker.upper()
    async with get_session() as session:
        score = (await session.execute(
            select(DiscoverySerenityScore).where(DiscoverySerenityScore.ticker == ticker)
        )).scalar_one_or_none()

        # signal 존재 여부 (seed 없어도 언급만 있으면 표시)
        has_signal = (await session.execute(
            select(SerenitySignal.id).where(SerenitySignal.ticker == ticker).limit(1)
        )).scalar_one_or_none() is not None

        if score is None and not has_signal:
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

    # 가격 스냅샷 병합
    price_map = await _load_price_map([ticker])
    vs_prior = price_map.get(ticker)

    if score is not None:
        card = await _score_to_card(score, latest_reasoning=latest_reasoning, vs_prior_close_pct=vs_prior)
    else:
        # unscored · seed 없이 aggregate + price 만으로 카드 구성
        agg = await aggregate_ticker_full(ticker)
        card = TickerCardItem(
            ticker=ticker,
            financing_tier=None,
            serenity_tier=None,
            total_score=0,
            auto_avoid=False,
            domain_tags=[],
            anti_pattern_flags=[],
            mentions_today=agg["mentions_today"],
            mentions_7d=agg["mentions_7d"],
            mentions_28d=agg["mentions_28d"],
            mention_count_90d=agg["mentions_90d"],
            bullish_pct_90d=agg["overall_bullish_pct"],
            stance_today=StanceBreakdown(**agg["stance_today"]),
            overall_stance=agg["overall_stance"],
            thesis_types=agg["thesis_types"],
            first_mention_at=agg["first_mention_at"],
            last_signal_at=agg["last_signal_at"],
            latest_reasoning=latest_reasoning,
            vs_prior_close_pct=vs_prior,
        )

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
