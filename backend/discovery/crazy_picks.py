"""Crazy Picks 모듈 — 시총 ≥ $1B 안전 universe.

스케줄: 매일 06:30 KST (한국 시간) ← 미국 장 마감 직후
출력: Top 10 후보 → DB `crazy_picks` 테이블
운영: 정보 전용 (자동 매매 X), Telegram 알림

데이터 흐름:
  1. universe 로드 (`ticker_universe` 테이블 → is_crazy=True)
  2. 각 ticker → 인자 입력 수집 (Stooq + Finnhub + SEC + Reddit + RSS + FINRA)
  3. scoring → FactorScores
  4. Top 10 선정
  5. 각 Top 10 → LLM thesis 생성
  6. DB 저장 + Telegram 알림
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

from backend.discovery.scoring import FactorScores, compute_factor_scores

logger = logging.getLogger(__name__)


@dataclass
class CrazyPickResult:
    """Crazy Picks 최종 결과."""

    ticker: str
    rank: int
    company_name: str
    sector: str
    current_price: float
    market_cap_usd: float
    total_score: float
    factor_scores: FactorScores
    thesis: str
    catalysts: list
    risks: list
    news_summary: str
    manipulation_risk: int


async def collect_factor_inputs(
    ticker: str,
    clients: dict,
    skip_slow: bool = False,
) -> dict:
    """단일 ticker → 9 인자 입력 dict 수집.

    Args:
        clients: {"stooq": StooqClient, "finnhub": ..., "sec": ..., ...}
        skip_slow: True 시 Reddit/SEC 등 느린 소스 skip (백테스트)

    Returns:
        scoring.compute_factor_scores() 의 inputs dict.
    """
    inputs: dict = {}

    # 각 외부 호출 개별 timeout — 한 소스 stuck 시 전체 hang 방지
    PER_STEP_TIMEOUT = 20.0  # 초

    # 1. Stooq (실제 Yahoo) — 52w, gap, volume
    try:
        stooq = clients["stooq"]
        stats = await asyncio.wait_for(stooq.get_52w_stats(ticker), timeout=PER_STEP_TIMEOUT)
        candles = await asyncio.wait_for(stooq.get_daily_candles(ticker, count=25), timeout=PER_STEP_TIMEOUT)
        if candles and stats:
            latest = candles[-1]
            prev = candles[-2] if len(candles) >= 2 else latest
            gap_pct = ((latest.open - prev.close) / prev.close) * 100 if prev.close else 0.0
            avg_vol_20 = sum(c.volume for c in candles[-20:]) / min(20, len(candles))
            volume_ratio = latest.volume / avg_vol_20 if avg_vol_20 > 0 else 1.0
            intraday_range_pct = ((latest.high - latest.low) / latest.low) * 100 if latest.low else 0
            inputs["gap_pct"] = gap_pct
            inputs["volume_ratio"] = volume_ratio
            inputs["intraday_range_pct"] = intraday_range_pct
            inputs["distance_from_52w_low_pct"] = (
                ((latest.close - stats.low_52w) / stats.low_52w) * 100 if stats.low_52w else 100
            )
            # ATR 근사 (5일 high-low 평균)
            recent_5 = candles[-5:]
            atr_pct_calc = (
                sum((c.high - c.low) / c.close for c in recent_5 if c.close) / len(recent_5) * 100
            )
            inputs["atr_pct"] = atr_pct_calc
    except Exception as e:
        logger.debug(f"[CrazyInputs] {ticker} Stooq fail: {e}")

    # 2. Finnhub — 어닝 캘린더
    try:
        finnhub = clients["finnhub"]
        earnings = await asyncio.wait_for(
            finnhub.get_earnings_calendar(ticker, days_ahead=14),
            timeout=PER_STEP_TIMEOUT,
        )
        if earnings:
            from datetime import datetime as dt
            today = dt.now().date()
            ev_date = dt.strptime(earnings[0].date, "%Y-%m-%d").date()
            days_to = (ev_date - today).days
            inputs["earnings_days"] = days_to
    except Exception as e:
        logger.debug(f"[CrazyInputs] {ticker} Finnhub fail: {e}")

    # 3. SEC EDGAR — 인사이더 cluster (가장 무거움 — timeout 30s)
    if not skip_slow:
        try:
            sec = clients["sec"]
            cluster = await asyncio.wait_for(
                sec.get_cluster_stats(ticker, window_days=15),
                timeout=30.0,
            )
            inputs["distinct_insider_buyers"] = cluster.distinct_buyers
            inputs["insider_cluster"] = cluster.cluster_detected
        except Exception as e:
            logger.debug(f"[CrazyInputs] {ticker} SEC fail: {e}")

    # 4. ApeWisdom — WSB 멘션 (Reddit 대체, 결정 2026-06-19)
    #    Reddit 정책 변경 (2025-11-11 사전 승인 필수) → 무인증 ApeWisdom 사용
    if not skip_slow:
        try:
            ape = clients["apewisdom"]
            stats = await asyncio.wait_for(ape.get_mention_stats(ticker), timeout=PER_STEP_TIMEOUT)
            inputs["wsb_mention_count"] = stats.mention_count
            # ApeWisdom 은 distinct_authors 미제공 — upvotes 를 근사 활동 지표로 사용
            inputs["wsb_distinct_authors"] = min(stats.upvotes // 10, stats.mention_count)
        except Exception as e:
            logger.debug(f"[CrazyInputs] {ticker} ApeWisdom fail: {e}")

    # 5. FINRA — 단기매도 (5일 윈도우 직렬 호출 → timeout 30s)
    if not skip_slow:
        try:
            finra = clients["finra"]
            summary = await asyncio.wait_for(
                finra.get_short_summary(ticker, window_days=5),
                timeout=30.0,
            )
            inputs["short_ratio"] = summary.latest_short_ratio
            inputs["short_trend_up"] = summary.trend_up
        except Exception as e:
            logger.debug(f"[CrazyInputs] {ticker} FINRA fail: {e}")

    # 6. RSS — 24h 뉴스 건수
    try:
        rss = clients["rss"]
        news = await asyncio.wait_for(
            asyncio.to_thread(rss.fetch_for_ticker, ticker, 24),
            timeout=PER_STEP_TIMEOUT,
        )
        inputs["news_count_24h"] = len(news)
    except Exception as e:
        logger.debug(f"[CrazyInputs] {ticker} RSS fail: {e}")

    return inputs


async def run_crazy_picks(
    universe_tickers: list,  # list[TickerInfo]
    clients: dict,
    top_n: int = 10,
    generate_thesis: bool = True,
    skip_slow: bool = False,
) -> list[CrazyPickResult]:
    """Crazy Picks 메인 실행.

    1. universe 전체 인자 수집 (병렬)
    2. 스코어링
    3. Top N 선정
    4. LLM thesis 생성 (Top N 만)

    Args:
        skip_slow: True 시 SEC EDGAR / FINRA / ApeWisdom 등 느린 소스 skip
                   (수동 dry-run·디버그 용 — Yahoo + Finnhub + RSS 만 사용)
    """
    logger.info(f"[Crazy] start — universe size: {len(universe_tickers)} skip_slow={skip_slow}")

    # 1. 인자 수집 (병렬 max 10 동시)
    sem = asyncio.Semaphore(10)

    async def collect_one(info):
        async with sem:
            inputs = await collect_factor_inputs(info.ticker, clients, skip_slow=skip_slow)
            return info, inputs

    results = await asyncio.gather(
        *(collect_one(info) for info in universe_tickers if info.is_crazy),
        return_exceptions=True,
    )

    # 2. 스코어링
    scored: list[tuple] = []  # (info, FactorScores)
    for r in results:
        if isinstance(r, Exception):
            continue
        info, inputs = r
        inputs["has_thesis"] = False  # thesis 는 Top N 만
        inputs["llm_manipulation_risk"] = 3  # 기본값
        scores = compute_factor_scores(info.ticker, inputs)
        scored.append((info, scores))

    # 3. Top N 정렬
    scored.sort(key=lambda x: x[1].total(), reverse=True)
    top = scored[:top_n]
    logger.info(f"[Crazy] {len(scored)} scored → Top {len(top)}")

    # 4. LLM thesis
    final: list[CrazyPickResult] = []
    if generate_thesis and "llm" in clients:
        llm = clients["llm"]
        async with llm:
            for rank, (info, scores) in enumerate(top, start=1):
                # thesis 후 재스코어
                scores_dict = {
                    "catalyst": scores.catalyst,
                    "gap_volume": scores.gap_volume,
                    "volatility": scores.volatility,
                    "insider": scores.insider,
                    "social": scores.social,
                    "technical": scores.technical,
                    "squeeze": scores.squeeze,
                    "low_52w": scores.low_52w,
                }
                try:
                    thesis = await llm.generate_pick_thesis(
                        ticker=info.ticker,
                        company_name=info.name,
                        sector=info.sector or "Unknown",
                        current_price=info.current_price or 0,
                        market_cap=(info.market_cap_usd / 1_000_000) if info.market_cap_usd else None,
                        scores=scores_dict,
                        catalysts_hint=[],
                        news_headlines=[],
                        risk_level="LOW",  # Crazy 는 시총 $1B+
                    )
                except Exception as e:
                    logger.warning(f"[Crazy] {info.ticker} LLM fail: {e}")
                    from backend.services.llm import PickThesis
                    thesis = PickThesis("", [], ["LLM 호출 실패"], "", 3)

                # 뉴스 점수 업데이트 (LLM 분석 후)
                from backend.discovery.scoring import score_news_llm
                scores.news_llm = score_news_llm(thesis.manipulation_risk, has_thesis=True)

                final.append(CrazyPickResult(
                    ticker=info.ticker,
                    rank=rank,
                    company_name=info.name,
                    sector=info.sector or "",
                    current_price=info.current_price or 0,
                    market_cap_usd=info.market_cap_usd or 0,
                    total_score=scores.total(),
                    factor_scores=scores,
                    thesis=thesis.thesis,
                    catalysts=thesis.catalysts,
                    risks=thesis.risks,
                    news_summary=thesis.news_summary,
                    manipulation_risk=thesis.manipulation_risk,
                ))
    else:
        # thesis 생략 모드 (백테스트)
        for rank, (info, scores) in enumerate(top, start=1):
            final.append(CrazyPickResult(
                ticker=info.ticker,
                rank=rank,
                company_name=info.name,
                sector=info.sector or "",
                current_price=info.current_price or 0,
                market_cap_usd=info.market_cap_usd or 0,
                total_score=scores.total(),
                factor_scores=scores,
                thesis="",
                catalysts=[],
                risks=[],
                news_summary="",
                manipulation_risk=3,
            ))

    logger.info(f"[Crazy] complete — Top {len(final)} picks")
    return final
