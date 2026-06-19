"""Backtest 도구 — 과거 데이터로 스코어링 검증.

목적:
  - 과거 N일치 데이터로 Top N 픽이 실제 어떻게 움직였는지 검증
  - 가중치 튜닝의 객관적 근거
  - EHGO / AZTR 시점에 시스템이 픽 했을지 확인 (역사적 검증)

사용:
    results = await run_backtest(
        target_date="2026-06-12",   # EHGO +321% 일
        candidates=["EHGO", "AZTR", "...100 종목"],
        clients={...},
    )
    print(f"EHGO 점수: {results['EHGO'].total():.1f}, 순위: {results['EHGO'].rank}")
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from backend.discovery.crazy_picks import collect_factor_inputs
from backend.discovery.scoring import FactorScores, compute_factor_scores

logger = logging.getLogger(__name__)


@dataclass
class BacktestEntry:
    """단일 종목 백테스트 결과."""

    ticker: str
    rank: int                # 후보 풀 내 순위
    total_score: float
    factor_scores: FactorScores

    # 실제 결과 (target_date 기준)
    return_1d: Optional[float]   # 다음 거래일 수익률
    return_5d: Optional[float]   # 5거래일 수익률
    return_20d: Optional[float]  # 20거래일 수익률
    max_return_within_5d: Optional[float]  # 5일 내 고점 수익률


async def fetch_actual_returns(
    ticker: str,
    target_date: str,
    stooq_client,
) -> dict[str, Optional[float]]:
    """target_date 이후 실제 수익률 측정.

    Returns:
        {"return_1d": float, "return_5d": float, "return_20d": float, "max_return_within_5d": float}
    """
    try:
        candles = await stooq_client.get_daily_candles(ticker, count=40)
    except Exception as e:
        logger.debug(f"[Backtest] {ticker} candles fail: {e}")
        return {"return_1d": None, "return_5d": None, "return_20d": None, "max_return_within_5d": None}

    target_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
    # 시간 정렬 (오래된 → 최신)
    candles_sorted = sorted(candles, key=lambda c: c.date)
    # target_date 이상 처음 인덱스
    base_idx = None
    for i, c in enumerate(candles_sorted):
        c_date = datetime.strptime(c.date, "%Y-%m-%d").date() if isinstance(c.date, str) else c.date
        if c_date >= target_dt:
            base_idx = i
            break

    if base_idx is None or base_idx + 1 >= len(candles_sorted):
        return {"return_1d": None, "return_5d": None, "return_20d": None, "max_return_within_5d": None}

    base_price = candles_sorted[base_idx].close

    def _ret(offset: int) -> Optional[float]:
        idx = base_idx + offset
        if idx >= len(candles_sorted):
            return None
        return (candles_sorted[idx].close - base_price) / base_price * 100

    # 5일 내 최고가
    max_within_5 = None
    end = min(base_idx + 6, len(candles_sorted))
    if end > base_idx + 1:
        highs = [c.high for c in candles_sorted[base_idx + 1: end]]
        if highs:
            max_within_5 = (max(highs) - base_price) / base_price * 100

    return {
        "return_1d":    _ret(1),
        "return_5d":    _ret(5),
        "return_20d":   _ret(20),
        "max_return_within_5d": max_within_5,
    }


async def run_backtest(
    candidates: list[str],
    clients: dict,
    target_date: Optional[str] = None,
) -> list[BacktestEntry]:
    """후보 ticker 리스트 → 점수 + 실제 수익률."""
    sem = asyncio.Semaphore(10)

    async def score_one(ticker: str) -> Optional[tuple]:
        async with sem:
            try:
                inputs = await collect_factor_inputs(ticker, clients, skip_slow=True)
                inputs["has_thesis"] = False
                inputs["llm_manipulation_risk"] = 3
                scores = compute_factor_scores(ticker, inputs)
                # 실제 수익률
                returns = {}
                if target_date and "stooq" in clients:
                    returns = await fetch_actual_returns(ticker, target_date, clients["stooq"])
                return ticker, scores, returns
            except Exception as e:
                logger.debug(f"[Backtest] {ticker} fail: {e}")
                return None

    results = await asyncio.gather(*(score_one(t) for t in candidates))
    valid = [r for r in results if r is not None]

    # 점수 기준 정렬
    valid.sort(key=lambda x: x[1].total(), reverse=True)

    entries: list[BacktestEntry] = []
    for rank, (ticker, scores, returns) in enumerate(valid, start=1):
        entries.append(BacktestEntry(
            ticker=ticker,
            rank=rank,
            total_score=scores.total(),
            factor_scores=scores,
            return_1d=returns.get("return_1d"),
            return_5d=returns.get("return_5d"),
            return_20d=returns.get("return_20d"),
            max_return_within_5d=returns.get("max_return_within_5d"),
        ))

    return entries


def summarize_backtest(entries: list[BacktestEntry], top_k: int = 10) -> dict:
    """Top K vs Bottom K 평균 수익률 비교."""
    if len(entries) < 2 * top_k:
        top_k = len(entries) // 2

    top = entries[:top_k]
    bottom = entries[-top_k:]

    def _avg(xs, attr):
        vals = [getattr(e, attr) for e in xs if getattr(e, attr) is not None]
        return sum(vals) / len(vals) if vals else None

    return {
        "top_k": top_k,
        "total_candidates": len(entries),
        "top_avg_1d":  _avg(top, "return_1d"),
        "top_avg_5d":  _avg(top, "return_5d"),
        "top_avg_20d": _avg(top, "return_20d"),
        "top_avg_max_5d": _avg(top, "max_return_within_5d"),
        "bottom_avg_1d":  _avg(bottom, "return_1d"),
        "bottom_avg_5d":  _avg(bottom, "return_5d"),
        "bottom_avg_20d": _avg(bottom, "return_20d"),
    }
