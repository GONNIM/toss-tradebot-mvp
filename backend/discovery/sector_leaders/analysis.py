"""Sector Leaders 분석 엔진 (B-2d).

품목 × 종목 페어별:
- Pearson r (24개월 수출 YoY vs 종목 월간 수익률)
- lead/lag -3~+3 매트릭스, best |r| 시점 기록
- 신뢰도 배지: strong (|r|≥0.7) / medium (0.4~0.7) / weak (<0.4)
- Sector Leader Score = log10(시총) × export_ratio_hint
- 품목별 score 기준 rank 1~N
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.data_sources.mapping import iter_all_tickers
from backend.services.models import (
    KrxDailyCandle,
    KrxStockMeta,
    MotirItemExport,
    SectorLeader,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# 통계 헬퍼
# ─────────────────────────────────────────────────────────────────


def _pearson(a: list[float], b: list[float]) -> float:
    if len(a) < 3 or len(a) != len(b):
        return float("nan")
    aa = np.array(a, dtype=float)
    bb = np.array(b, dtype=float)
    if aa.std() < 1e-9 or bb.std() < 1e-9:
        return float("nan")
    return float(np.corrcoef(aa, bb)[0, 1])


def _confidence_label(r: float) -> str:
    if math.isnan(r):
        return "weak"
    a = abs(r)
    if a >= 0.7:
        return "strong"
    if a >= 0.4:
        return "medium"
    return "weak"


def _best_lag(
    yoy: pd.Series,
    ret: pd.Series,
    lag_range: tuple[int, int] = (-3, 3),
) -> tuple[float, int]:
    """lead/lag -3~+3 매트릭스 → |r| 최대 시점.

    lag>0 = yoy 가 주가를 선행 (수출 → 주가).
    lag<0 = 주가가 수출을 선행 (시장 기대 반영).
    """
    best_r = 0.0
    best_lag = 0
    for k in range(lag_range[0], lag_range[1] + 1):
        if k == 0:
            a = yoy.tolist()
            b = ret.tolist()
        elif k > 0:
            a = yoy[:-k].tolist()
            b = ret[k:].tolist()
        else:
            a = yoy[-k:].tolist()
            b = ret[:k].tolist()
        r = _pearson(a, b)
        if not math.isnan(r) and abs(r) > abs(best_r):
            best_r = r
            best_lag = k
    return best_r, best_lag


def _score(market_cap_krw: Optional[float], export_ratio_hint: float) -> float:
    """Sector Leader Score = log10(시총) × export_ratio_hint."""
    if market_cap_krw is None or market_cap_krw <= 0:
        return 0.0
    return math.log10(market_cap_krw) * export_ratio_hint


# ─────────────────────────────────────────────────────────────────
# 분석 데이터 빌더
# ─────────────────────────────────────────────────────────────────


async def _load_item_yoy(session: AsyncSession) -> dict[str, dict[str, float]]:
    rows = (
        await session.execute(
            select(
                MotirItemExport.item,
                MotirItemExport.month,
                MotirItemExport.yoy_pct,
            )
            .where(MotirItemExport.yoy_pct.is_not(None))
            .order_by(MotirItemExport.month)
        )
    ).all()
    out: dict[str, dict[str, float]] = {}
    for it, m, y in rows:
        out.setdefault(it, {})[m] = float(y)
    return out


async def _load_ticker_monthly_return(
    session: AsyncSession,
) -> dict[str, dict[str, float]]:
    rows = (
        await session.execute(
            select(KrxDailyCandle.ticker, KrxDailyCandle.date, KrxDailyCandle.close)
            .order_by(KrxDailyCandle.ticker, KrxDailyCandle.date)
        )
    ).all()
    by_ticker: dict[str, list[tuple[str, float]]] = {}
    for t, d, c in rows:
        by_ticker.setdefault(t, []).append((d, c))

    out: dict[str, dict[str, float]] = {}
    for ticker, points in by_ticker.items():
        if not points:
            continue
        df = pd.DataFrame(points, columns=["date", "close"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").set_index("date")
        monthly_close = df["close"].resample("ME").last()
        monthly_ret = monthly_close.pct_change() * 100.0
        ret_dict = {
            idx.strftime("%Y-%m"): float(v)
            for idx, v in monthly_ret.items()
            if not pd.isna(v)
        }
        out[ticker] = ret_dict
    return out


async def _load_meta(session: AsyncSession) -> dict[str, KrxStockMeta]:
    rows = (await session.execute(select(KrxStockMeta))).scalars().all()
    return {m.ticker: m for m in rows}


# ─────────────────────────────────────────────────────────────────
# 메인 엔진
# ─────────────────────────────────────────────────────────────────


@dataclass
class PairResult:
    item: str
    ticker: str
    name: str
    score: float
    market_cap_krw: Optional[float]
    export_ratio_hint: float
    pearson_r0: float
    best_r: float
    best_lag: int
    sample_n: int
    confidence: str


async def compute_sector_leaders(
    session: AsyncSession,
) -> list[PairResult]:
    """전 매핑 종목 × 품목 → Sector Leaders 결과 리스트.

    DB 저장은 별도 호출 (persist_sector_leaders).
    """
    item_yoy = await _load_item_yoy(session)
    ticker_ret = await _load_ticker_monthly_return(session)
    meta_by_code = await _load_meta(session)

    results: list[PairResult] = []
    for mt in iter_all_tickers():
        yoy = item_yoy.get(mt.item, {})
        ret = ticker_ret.get(mt.code, {})
        common = sorted(set(yoy.keys()) & set(ret.keys()))
        if len(common) < 6:
            continue
        yoy_s = pd.Series({m: yoy[m] for m in common})
        ret_s = pd.Series({m: ret[m] for m in common})

        r0 = _pearson(yoy_s.tolist(), ret_s.tolist())
        best_r, best_lag = _best_lag(yoy_s, ret_s)

        meta = meta_by_code.get(mt.code)
        market_cap = meta.market_cap_krw if meta else None
        score = _score(market_cap, mt.export_ratio_hint)

        results.append(
            PairResult(
                item=mt.item,
                ticker=mt.code,
                name=mt.name,
                score=score,
                market_cap_krw=market_cap,
                export_ratio_hint=mt.export_ratio_hint,
                pearson_r0=r0 if not math.isnan(r0) else 0.0,
                best_r=best_r,
                best_lag=best_lag,
                sample_n=len(common),
                confidence=_confidence_label(best_r),
            )
        )
    return results


async def persist_sector_leaders(
    session: AsyncSession,
    results: list[PairResult],
) -> dict[str, int]:
    """결과 → SectorLeader 테이블 덮어쓰기.

    같은 (item, ticker) 키 UPSERT, 품목별 score 기준 rank 1~N.
    """
    # 품목별 rank 계산
    by_item: dict[str, list[PairResult]] = {}
    for r in results:
        by_item.setdefault(r.item, []).append(r)
    for item, lst in by_item.items():
        lst.sort(key=lambda r: r.score, reverse=True)
        for rank, r in enumerate(lst, start=1):
            existing = (
                await session.execute(
                    select(SectorLeader).where(
                        SectorLeader.item == r.item,
                        SectorLeader.ticker == r.ticker,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    SectorLeader(
                        item=r.item,
                        ticker=r.ticker,
                        name=r.name,
                        rank=rank,
                        score=r.score,
                        market_cap_krw=r.market_cap_krw,
                        export_ratio_hint=r.export_ratio_hint,
                        pearson_r0=r.pearson_r0,
                        best_r=r.best_r,
                        best_lag_months=r.best_lag,
                        sample_n=r.sample_n,
                        confidence=r.confidence,
                    )
                )
            else:
                existing.name = r.name
                existing.rank = rank
                existing.score = r.score
                existing.market_cap_krw = r.market_cap_krw
                existing.export_ratio_hint = r.export_ratio_hint
                existing.pearson_r0 = r.pearson_r0
                existing.best_r = r.best_r
                existing.best_lag_months = r.best_lag
                existing.sample_n = r.sample_n
                existing.confidence = r.confidence

    return {"items": len(by_item), "rows": len(results)}
