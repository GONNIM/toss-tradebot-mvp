"""오늘의 실행 카드 · Phase L14+ · 2026-08-05.

사용자 지시서 · Serenity Hunter 페이지 최상단 섹션.
필터 통과 종목만 골라 매수가·손절가·TP 자동 계산 → 카드 발급.

원칙 (스코프 밖 금지):
    - 필터·계산 규칙은 constants.py 상수만 사용
    - 신규 데이터 소스 금지 (환율 = 하드코딩 constants.USDKRW_RATE)
    - 자동 주문·알림 금지

필터 (AND):
    - bull_pct_90d >= BULL_PCT_MIN (70)
    - mentions_90d >= MENTIONS_90D_MIN (10)
    - mentions_7d >= MENTIONS_7D_MIN (2)
    - auto_avoid=false AND anti_pattern_flags 비어있음
    - SerenityTickerPrice.close 존재 (가격 없는 티커는 watch_only 로 분리)
    - industry NOT IN SHELL_INDUSTRIES

정렬: seed tier (S→A→B) 우선 · mentions_7d desc · bull_pct desc.
최대 5카드 표시 (그 이상은 rest_count).
"""
from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from backend.discovery.serenity.aggregators import (
    active_tickers,
    aggregate_ticker_full,
    first_mention_map,
)
from backend.discovery.serenity.constants import (
    BULL_PCT_MIN,
    MENTIONS_7D_MIN,
    MENTIONS_90D_MIN,
    MIN_RR_WARNING,
    POSITION_KRW,
    SHELL_INDUSTRIES,
    SLIPPAGE_LIMIT_PCT,
    SL_DAYS,
    SL_PCT,
    TP_TRIGGER_PCT,
    TRAIL_PCT,
    USDKRW_RATE,
)
from backend.services.db import get_session
from backend.services.models import (
    DiscoverySerenityScore,
    SerenityTickerPrice,
)

logger = logging.getLogger(__name__)

MAX_VISIBLE_CARDS = 5

# ─── 가격 검증 게이트 (2026-08-13 MU 사고 대응) ───────────────────
# Fable 5 리뷰: 절대 범위 하드코딩 X · 내부 일관성 불변식 사용
PRICE_ABNORMAL_MOVE_THRESHOLD_PCT = 30.0
"""prior close 대비 |vs_prior_pct| > 30% → 카드에 "가격 검증 실패" 배지 (배제 X)."""

MARKET_CAP_SANITY_TOLERANCE = 0.10
"""|marketCap − shares × close| / marketCap > 10% → sanity warning."""


def _tier_rank(tier: Optional[str]) -> int:
    """S=0 · A=1 · B=2 · C=3 · D=4 · F=5 · None=99. 낮을수록 상위."""
    order = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4, "F": 5}
    return order.get(tier or "", 99)


def _compute_execution_plan(last_close: float) -> dict:
    """가격 → 매수·수량·손절·TP 자동 계산 (constants.py 상수 사용)."""
    entry_limit = round(last_close * (1 + SLIPPAGE_LIMIT_PCT / 100), 4)
    # qty (원화 예산 ÷ 원화 환산 매수 상한가 · floor)
    entry_krw = entry_limit * USDKRW_RATE
    qty = int(math.floor(POSITION_KRW / entry_krw)) if entry_krw > 0 else 0
    sl_price = round(entry_limit * (1 - SL_PCT / 100), 4)
    tp_trigger_price = round(entry_limit * (1 + TP_TRIGGER_PCT / 100), 4)
    # 최소 R:R = (TP − entry) / (entry − SL) = TP_TRIGGER_PCT / SL_PCT
    min_rr = round(TP_TRIGGER_PCT / SL_PCT, 2) if SL_PCT > 0 else 0.0
    return {
        "entry_limit": entry_limit,
        "entry_krw": round(entry_krw, 0),
        "qty": qty,
        "sl_price": sl_price,
        "sl_days": SL_DAYS,
        "tp_trigger_price": tp_trigger_price,
        "trail_pct": TRAIL_PCT,
        "min_rr": min_rr,
        "min_rr_warning": min_rr < MIN_RR_WARNING,
    }


async def build_action_cards() -> dict:
    """오늘의 실행 카드 조립 · 지시서 §1.

    반환:
      {as_of, fx_rate, cards: [...], watch_only: [...], excluded: [...], rest_count}
    """
    now = datetime.utcnow()

    # 후보 티커 (seed + 최근 90일 언급 union)
    async with get_session() as session:
        seed_rows = list((await session.execute(select(DiscoverySerenityScore))).scalars().all())
    seed_map: dict[str, DiscoverySerenityScore] = {s.ticker: s for s in seed_rows}
    signal_ticker_set = set(await active_tickers(days=90))
    all_tickers = sorted(set(seed_map.keys()) | signal_ticker_set)
    if not all_tickers:
        return {
            "as_of": now.isoformat(),
            "fx_rate": USDKRW_RATE,
            "fx_source": "hardcoded",
            "cards": [],
            "cards_hidden": [],
            "watch_only": [],
            "excluded": [],
            "rest_count": 0,
            "filters": {
                "bull_pct_min": BULL_PCT_MIN,
                "mentions_90d_min": MENTIONS_90D_MIN,
                "mentions_7d_min": MENTIONS_7D_MIN,
                "shell_industries": list(SHELL_INDUSTRIES),
            },
            "risk": {
                "slippage_limit_pct": SLIPPAGE_LIMIT_PCT,
                "sl_pct": SL_PCT,
                "sl_days": SL_DAYS,
                "tp_trigger_pct": TP_TRIGGER_PCT,
                "trail_pct": TRAIL_PCT,
                "position_krw": POSITION_KRW,
                "min_rr_warning": MIN_RR_WARNING,
            },
        }

    async with get_session() as session:
        price_rows = list((await session.execute(
            select(
                SerenityTickerPrice.ticker,
                SerenityTickerPrice.close,
                SerenityTickerPrice.industry,
                SerenityTickerPrice.sector,
                SerenityTickerPrice.prior_close,
                SerenityTickerPrice.vs_prior_close_pct,
                SerenityTickerPrice.market_cap,
                SerenityTickerPrice.shares_outstanding,
            )
            .where(SerenityTickerPrice.ticker.in_(all_tickers))
        )).all())
    price_map: dict[str, dict] = {
        r[0]: {
            "close": r[1], "industry": r[2], "sector": r[3],
            "prior_close": r[4], "vs_prior_pct": r[5],
            "market_cap": r[6], "shares": r[7],
        }
        for r in price_rows
    }
    fm_map = await first_mention_map(all_tickers)

    def _parse_flags(csv: Optional[str]) -> list[str]:
        if not csv:
            return []
        return [x.strip() for x in csv.split(",") if x.strip()]

    passed: list[dict] = []
    watch_only: list[dict] = []
    excluded: list[dict] = []

    for tk in all_tickers:
        seed = seed_map.get(tk)
        agg = await aggregate_ticker_full(tk)
        bull_pct = agg["overall_bullish_pct"]
        m90 = agg["mentions_90d"]
        m7 = agg["mentions_7d"]
        price = price_map.get(tk) or {}
        industry = price.get("industry")
        last_close = price.get("close")

        # Anti-filter
        if seed and seed.auto_avoid:
            excluded.append({"ticker": tk, "reason": "auto_avoid=true"})
            continue
        anti_flags = _parse_flags(seed.anti_pattern_flags) if seed else []
        if anti_flags:
            excluded.append({"ticker": tk, "reason": f"anti_pattern={','.join(anti_flags)}"})
            continue
        if industry in SHELL_INDUSTRIES:
            excluded.append({"ticker": tk, "reason": f"industry={industry}"})
            continue

        # 표본 필터
        if m90 < MENTIONS_90D_MIN:
            excluded.append({"ticker": tk, "reason": f"m90 {m90} < {MENTIONS_90D_MIN}"})
            continue
        if m7 < MENTIONS_7D_MIN:
            excluded.append({"ticker": tk, "reason": f"m7 {m7} < {MENTIONS_7D_MIN}"})
            continue
        if bull_pct < BULL_PCT_MIN:
            excluded.append({"ticker": tk, "reason": f"bull_pct {bull_pct:.0f} < {BULL_PCT_MIN:.0f}"})
            continue

        # 가격 유무 → watch_only 분리
        if last_close is None or last_close <= 0:
            watch_only.append({
                "ticker": tk,
                "industry": industry,
                "bull_pct": bull_pct,
                "mentions_7d": m7,
                "mentions_90d": m90,
                "reason": "no_price_feed",
            })
            continue

        # 카드 발급 대상 · 실행 계획 계산
        plan = _compute_execution_plan(last_close)

        # qty=0 판정 · 예산 대비 매수 불가 (2026-08-13 MU 사고 · A안 · Fable 5 리뷰)
        if plan["qty"] < 1:
            entry_usd = plan["entry_limit"]
            excluded.append({
                "ticker": tk,
                "reason": (
                    f"예산 미달 (1주 ${entry_usd:.2f} × FX {int(USDKRW_RATE)} = "
                    f"₩{int(entry_usd * USDKRW_RATE):,} > 예산 ₩{int(POSITION_KRW):,})"
                ),
            })
            continue

        # 가격 검증 게이트 (Fable 5 리뷰 · 배제 X · 배지만)
        vs_prior_pct = price.get("vs_prior_pct")
        price_verification_failed = (
            vs_prior_pct is not None
            and abs(vs_prior_pct) > PRICE_ABNORMAL_MOVE_THRESHOLD_PCT
        )

        # Market cap 검산 (내부 일관성 불변식)
        market_cap = price.get("market_cap")
        shares = price.get("shares")
        market_cap_sanity_warning = False
        if market_cap and shares and last_close and market_cap > 0:
            computed = shares * last_close
            deviation = abs(market_cap - computed) / market_cap
            if deviation > MARKET_CAP_SANITY_TOLERANCE:
                market_cap_sanity_warning = True
                logger.warning(
                    "[action_cards] market_cap sanity 실패 · %s · yf=%.0f computed=%.0f deviation=%.1f%%",
                    tk, market_cap, computed, deviation * 100,
                )

        first_at = fm_map.get(tk)
        passed.append({
            "ticker": tk,
            "tier": seed.serenity_tier if seed else None,
            "tier_rank": _tier_rank(seed.serenity_tier if seed else None),
            "financing_tier": seed.financing_tier if seed else None,
            "bull_pct": bull_pct,
            "mentions_7d": m7,
            "mentions_90d": m90,
            "industry": industry,
            "sector": price.get("sector"),
            "last_close": last_close,
            "vs_prior_pct": vs_prior_pct,
            "price_verification_failed": price_verification_failed,
            "market_cap_sanity_warning": market_cap_sanity_warning,
            "first_mention_at": first_at.isoformat() if first_at else None,
            **plan,
        })

    # 정렬 · tier_rank asc · mentions_7d desc · bull_pct desc
    passed.sort(key=lambda c: (c["tier_rank"], -c["mentions_7d"], -c["bull_pct"]))

    # 동일 industry 겹침 배지 (2+ 카드가 같은 industry 면 sector_overlap=True)
    from collections import Counter
    ind_count = Counter(c.get("industry") for c in passed if c.get("industry"))
    for c in passed:
        ind = c.get("industry")
        c["sector_overlap"] = bool(ind and ind_count[ind] >= 2)

    visible = passed[:MAX_VISIBLE_CARDS]
    rest = passed[MAX_VISIBLE_CARDS:]

    return {
        "as_of": now.isoformat(),
        "fx_rate": USDKRW_RATE,
        "fx_source": "hardcoded",
        "cards": visible,
        "cards_hidden": rest,     # "더 보기" 대상
        "rest_count": len(rest),
        "watch_only": watch_only,
        "excluded": excluded,
        "filters": {
            "bull_pct_min": BULL_PCT_MIN,
            "mentions_90d_min": MENTIONS_90D_MIN,
            "mentions_7d_min": MENTIONS_7D_MIN,
            "shell_industries": list(SHELL_INDUSTRIES),
        },
        "risk": {
            "slippage_limit_pct": SLIPPAGE_LIMIT_PCT,
            "sl_pct": SL_PCT,
            "sl_days": SL_DAYS,
            "tp_trigger_pct": TP_TRIGGER_PCT,
            "trail_pct": TRAIL_PCT,
            "position_krw": POSITION_KRW,
            "min_rr_warning": MIN_RR_WARNING,
        },
    }
