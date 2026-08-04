"""Serenity Hunter · 게이트 + 폐기 + 중간경고 판정 · Phase L14 v6 (2026-08-04).

Step A: is_gate_open()/is_deprecation_triggered()/mid_gate_excess_warning() 뼈대.
        (실제 hunter_rows() 는 Step C 에서 구현 · Fable 5 3차 순서 강제)

Fable 5 3차 (1) 반영 (v6 §2.7):
    is_gate_open() = 5조건 AND
      1. valid_backtest_events >= 50 (v6 §2.7 상폐 포함)
      2. IWM benchmark row >= 50 영업일 (Fable 5 6차 · 개수 · 수익률 아님)
      3. MAX(computed_at) >= now - 48h
      4. health.warn == false (stale 방어)
      5. is_deprecation_triggered() == false (폐기 강제 close)

Fable 5 3차 (2) 반영 (v6 §2.8):
    is_deprecation_triggered() =
      · valid >= 150
      · AND avg(raw_return_3d - benchmark_iwm_return_3d) - SLIPPAGE - COST <= 0
        (v6 D1: raw · 판정 계층에서 1회 차감)
      · AND DEPRECATION_OVERRIDE_TICKET is None

Fable 5 3차 (2d) 반영 (v6 §2.9):
    mid_gate_excess_warning() =
      · 50 <= valid < 150 AND avg(raw - bench_iwm) - SLIPPAGE - COST <= 0
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select

from backend.discovery.serenity.constants import (
    COST_ROUND_TRIP_PCT,
    DEPRECATION_EVENTS_MIN,
    DEPRECATION_OVERRIDE_TICKET,
    GATE_EVENTS_MIN,
    SLIPPAGE_PCT,
)
from backend.services.db import get_session
from backend.services.models import SerenityBacktest, SerenityBenchmarkPrice

logger = logging.getLogger(__name__)


async def _count_valid_backtests() -> int:
    """v6 §2.7 valid = price_at_signal not null AND (return_3d not null OR delisting_flag=true)."""
    async with get_session() as session:
        return int((await session.execute(
            select(func.count()).select_from(SerenityBacktest).where(
                SerenityBacktest.price_at_signal.is_not(None),
                (SerenityBacktest.return_3d.is_not(None)) | (SerenityBacktest.delisting_flag.is_(True)),
            )
        )).scalar_one())


async def _count_benchmark_rows(symbol: str) -> int:
    async with get_session() as session:
        return int((await session.execute(
            select(func.count()).select_from(SerenityBenchmarkPrice).where(
                SerenityBenchmarkPrice.symbol == symbol
            )
        )).scalar_one())


async def _last_backtest_freshness() -> Optional[datetime]:
    async with get_session() as session:
        return (await session.execute(
            select(func.max(SerenityBacktest.computed_at))
        )).scalar_one_or_none()


async def _avg_excess_iwm_3d_adjusted() -> Optional[float]:
    """v6 D1: raw excess (bench 차감) - SLIPPAGE - COST · 판정 계층 1회 차감.

    valid 이벤트만 대상 (상폐 포함 · return_3d 이 있어야 계산 가능).
    """
    async with get_session() as session:
        rows = list((await session.execute(
            select(SerenityBacktest.return_3d, SerenityBacktest.benchmark_iwm_return_3d)
            .where(SerenityBacktest.price_at_signal.is_not(None))
            .where(SerenityBacktest.return_3d.is_not(None))
            .where(SerenityBacktest.benchmark_iwm_return_3d.is_not(None))
        )).all())
    if not rows:
        return None
    diffs = [r[0] - r[1] for r in rows]
    raw_excess = sum(diffs) / len(diffs)
    # 판정 계층 1회 차감 (Fable 5 4차 D1 · v6 §2.8)
    return round(raw_excess - SLIPPAGE_PCT - COST_ROUND_TRIP_PCT, 2)


async def is_deprecation_triggered() -> bool:
    """폐기 조건 판정 (v6 §2.8 · Fable 5 3차 (2) · IWM 단독).

    True → hunter_rows() 자동 빈 배열 · 리스트 사라짐 (배너 아님).
    재개: RISK-PRINCIPLES §11 이력 + constants.DEPRECATION_OVERRIDE_TICKET 변경.
    """
    if DEPRECATION_OVERRIDE_TICKET is not None:
        # 재개 트리거 · 폐기 무효화
        return False
    valid = await _count_valid_backtests()
    if valid < DEPRECATION_EVENTS_MIN:
        return False
    adjusted = await _avg_excess_iwm_3d_adjusted()
    if adjusted is None:
        return False
    return adjusted <= 0


async def is_gate_open(health_warn: bool = False) -> tuple[bool, list[str]]:
    """v6 §2.7 하드 게이트 5조건 AND.

    반환: (open: bool, close_reasons: list[str])
    Step B UI 는 open=false 시 HunterEmptyGate 렌더.
    """
    reasons: list[str] = []

    valid = await _count_valid_backtests()
    if valid < GATE_EVENTS_MIN:
        reasons.append(f"insufficient_valid_events ({valid}/{GATE_EVENTS_MIN})")

    iwm_rows = await _count_benchmark_rows("IWM")
    if iwm_rows < GATE_EVENTS_MIN:
        reasons.append(f"insufficient_benchmark_rows_iwm ({iwm_rows}/{GATE_EVENTS_MIN})")

    last_computed = await _last_backtest_freshness()
    if last_computed is None or last_computed < datetime.utcnow() - timedelta(hours=48):
        reasons.append("stale_backtest (computed_at > 48h)")

    if health_warn:
        reasons.append("health_warn")

    if await is_deprecation_triggered():
        reasons.append("deprecation_triggered")

    return (len(reasons) == 0, reasons)


async def mid_gate_excess_warning() -> bool:
    """v6 §2.9 · 50 <= valid < 150 AND avg(raw - bench_iwm) - SLIPPAGE - COST <= 0.

    True → UI 리스트 상단 적색 배너 상시.
    """
    valid = await _count_valid_backtests()
    if valid < GATE_EVENTS_MIN or valid >= DEPRECATION_EVENTS_MIN:
        return False
    adjusted = await _avg_excess_iwm_3d_adjusted()
    if adjusted is None:
        return False
    return adjusted <= 0


async def hunter_rows() -> dict:
    """발굴 리스트 · 게이트+폐기 판정 반영 · v6 §2.6.

    반환:
      {gate_open, deprecation_triggered, mid_gate_warning, rows: [...],
       deprecation_recommended, gate_close_reasons}

    gate_open=False OR deprecation_triggered=True → rows=[] (배너 아닌 소멸 · Fable 5 3차 (2a))
    """
    from datetime import timedelta
    from collections import defaultdict
    from sqlalchemy import desc
    from backend.discovery.serenity.aggregators import (
        active_tickers,
        aggregate_ticker_full,
        first_mention_map,
    )
    from backend.services.models import (
        DiscoverySerenityScore,
        SerenitySignal,
        SerenityTickerPrice,
    )

    # 게이트 판정 (health.warn 은 API 레이어에서 이미 반영 · 여기선 데이터/deprecation만)
    gate_open, gate_reasons = await is_gate_open(health_warn=False)
    deprecation = await is_deprecation_triggered()
    mid_warn = await mid_gate_excess_warning()

    if not gate_open or deprecation:
        return {
            "gate_open": gate_open and not deprecation,
            "deprecation_triggered": deprecation,
            "mid_gate_warning": mid_warn,
            "gate_close_reasons": gate_reasons,
            "deprecation_recommended": deprecation,
            "rows": [],
        }

    # 게이트 오픈 · 실 hunter rows 조립 (Serenity Stock Tracker /tickers 와 유사한 소스 · 컬럼 확장)
    seed_tickers: dict[str, DiscoverySerenityScore] = {}
    signal_ticker_set: set[str] = set()
    price_map: dict[str, dict] = {}
    fm_map = {}
    async with get_session() as session:
        # seed 티커
        seed_rows = list((await session.execute(select(DiscoverySerenityScore))).scalars().all())
        seed_tickers = {s.ticker: s for s in seed_rows}
        # signals 언급 티커 (최근 90일 · aggregators.active_tickers 재사용)

    signal_ticker_set = set(await active_tickers(days=90))
    all_tickers = sorted(set(seed_tickers.keys()) | signal_ticker_set)
    if not all_tickers:
        return {
            "gate_open": True,
            "deprecation_triggered": False,
            "mid_gate_warning": mid_warn,
            "gate_close_reasons": [],
            "deprecation_recommended": False,
            "rows": [],
        }

    # 가격/유동성/시총
    async with get_session() as session:
        pr_rows = list((await session.execute(
            select(
                SerenityTickerPrice.ticker,
                SerenityTickerPrice.vs_prior_close_pct,
                SerenityTickerPrice.gain_since_first_mention_pct,
                SerenityTickerPrice.sector,
                SerenityTickerPrice.industry,
                SerenityTickerPrice.market_cap,
                SerenityTickerPrice.avg_dollar_volume_20d,
            )
            .where(SerenityTickerPrice.ticker.in_(all_tickers))
        )).all())
    for row in pr_rows:
        price_map[row[0]] = {
            "vs_prior_close_pct": row[1],
            "gain_since_first_mention_pct": row[2],
            "sector": row[3],
            "industry": row[4],
            "market_cap": row[5],
            "avg_dollar_volume_20d": row[6],
        }

    fm_map = await first_mention_map(all_tickers)

    # 최근 signal 배치 · signal 별 avg_confidence · latest_thesis 계산
    async with get_session() as session:
        sig_rows = list((await session.execute(
            select(SerenitySignal.ticker, SerenitySignal.confidence, SerenitySignal.thesis_type, SerenitySignal.extracted_at)
            .where(SerenitySignal.ticker.in_(all_tickers))
            .order_by(desc(SerenitySignal.extracted_at))
        )).all())

    # 티커별 최근 signals · confidence 평균 (최근 5개) · latest thesis (최상단)
    by_ticker: dict[str, list] = defaultdict(list)
    for tk, conf, thesis, at in sig_rows:
        by_ticker[tk].append((conf, thesis, at))

    now = datetime.utcnow()
    d7 = now - timedelta(days=7)

    # RISK-PRINCIPLES §1 종목당 20% · 시드 100만원 = 20만원 ≈ USD 150 (환율 1330 근사 · 최대 매수)
    ORDER_KRW = 200_000.0
    ORDER_USD = ORDER_KRW / 1330.0

    rows_out = []
    for tk in all_tickers:
        seed = seed_tickers.get(tk)
        agg = await aggregate_ticker_full(tk)
        # 90일 언급 없음 제외
        if agg["mentions_90d"] == 0:
            continue

        price = price_map.get(tk) or {}
        recent = by_ticker.get(tk, [])[:5]
        avg_conf = None
        latest_thesis = None
        if recent:
            confs = [r[0] for r in recent if r[0] is not None]
            if confs:
                avg_conf = round(sum(confs) / len(confs), 2)
            latest_thesis = recent[0][1]

        first_at = fm_map.get(tk)
        is_new = first_at is not None and first_at >= d7
        is_avoid_new = bool(seed and seed.auto_avoid and is_new)

        adv = price.get("avg_dollar_volume_20d")
        order_pct_of_adv = None
        if adv and adv > 0:
            order_pct_of_adv = round(ORDER_USD / adv * 100, 4)
        passes_liquidity = bool(
            adv is not None and adv >= 2_000_000
            and order_pct_of_adv is not None and order_pct_of_adv <= 0.5
        )

        mc = price.get("market_cap")
        if mc is None:
            mc_tier = "unknown"
        elif mc < 1e9:
            mc_tier = "micro (<1B)"
        elif mc < 1e10:
            mc_tier = "small (1-10B)"
        else:
            mc_tier = "mid+"

        rows_out.append({
            "ticker": tk,
            "industry": price.get("industry"),
            "sector": price.get("sector"),
            "first_mention_at": first_at.isoformat() if first_at else None,
            "latest_signal_at": agg["last_signal_at"].isoformat() if agg.get("last_signal_at") else None,
            "mentions_today": agg["mentions_today"],
            "mentions_7d": agg["mentions_7d"],
            "mentions_28d": agg["mentions_28d"],
            "mentions_90d": agg["mentions_90d"],
            "avg_confidence_recent": avg_conf,
            "latest_thesis": latest_thesis,
            "bull_pct_90d": agg["overall_bullish_pct"],
            "market_cap": mc,
            "market_cap_tier": mc_tier,
            "avg_dollar_volume_20d": adv,
            "order_pct_of_adv_1M": order_pct_of_adv,
            "passes_liquidity": passes_liquidity,
            "vs_prior_close_pct": price.get("vs_prior_close_pct"),
            "gain_since_first_mention_pct": price.get("gain_since_first_mention_pct"),
            "stance": agg["overall_stance"],
            "is_new": is_new,
            "is_avoid_new": is_avoid_new,
        })

    # default sort · first_mention_at desc (v6 · Fable 5 지시)
    rows_out.sort(
        key=lambda r: r["first_mention_at"] or "",
        reverse=True,
    )

    return {
        "gate_open": True,
        "deprecation_triggered": False,
        "mid_gate_warning": mid_warn,
        "gate_close_reasons": [],
        "deprecation_recommended": False,
        "rows": rows_out,
    }
