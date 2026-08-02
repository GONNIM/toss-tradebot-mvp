"""Serenity 15원칙 스코어링 · Phase L4 · 2026-08-02.

원본: docs/plans/serenity-integration/02-backend-arch.md §5.

공식:
  Positive:
    bottleneck_score (0~10) × 10                       # 최대 100
    mag7_customer_count (0~7) × 15                     # 최대 105
    gaap_gross_margin > 60 → +30
    is_pre_ramp → +40
    contracted_arr_multiple > 3 → +50
    institutional_holdings_delta_30d < 0 → +30 (기관 미catch-up = edge)

  Negative:
    active_atm_pct_of_mc > 30 → -100
    len(anti_pattern_flags) × 20 → -20 per flag

  Auto-avoid rules (bool):
    active_atm_pct_of_mc > 40 → True
    financing_tier in (D, F)  → True
    serenity_tier == F        → True
    len(anti_pattern_flags) >= 3 → True
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.discovery.serenity.aggregators import (
    active_tickers,
    aggregate_signals,
)
from backend.services.db import get_session
from backend.services.models import DiscoverySerenityScore

logger = logging.getLogger(__name__)


AUTO_AVOID_TIERS = ("D", "F")


def _parse_csv(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _csv_from_list(items: Optional[list[str]]) -> Optional[str]:
    if not items:
        return None
    cleaned = [i.strip() for i in items if i and i.strip()]
    return ",".join(cleaned) if cleaned else None


def compute_serenity_score(row: dict[str, Any]) -> tuple[int, bool]:
    """티커별 총 스코어 + auto_avoid 판정.

    row 는 스코어 산정에 필요한 필드 dict (DB row · seed · aggregate 결과 병합).
    anti_pattern_flags 는 list[str] · domain_tags 는 list[str].
    """
    score = 0

    # ── Positive ────────────────────────────────────────────
    score += (row.get("bottleneck_score") or 0) * 10          # 최대 100
    score += (row.get("mag7_customer_count") or 0) * 15       # 최대 105
    if (row.get("gaap_gross_margin") or 0) > 60:
        score += 30
    if row.get("is_pre_ramp"):
        score += 40
    if (row.get("contracted_arr_multiple") or 0) > 3:
        score += 50
    if (row.get("institutional_holdings_delta_30d") or 0) < 0:
        score += 30

    # ── Negative ────────────────────────────────────────────
    atm_pct = row.get("active_atm_pct_of_mc") or 0
    if atm_pct > 30:
        score -= 100
    flags = row.get("anti_pattern_flags") or []
    score -= len(flags) * 20

    # ── Auto-avoid ─────────────────────────────────────────
    auto_avoid = False
    if atm_pct > 40:
        auto_avoid = True
    if row.get("financing_tier") in AUTO_AVOID_TIERS:
        auto_avoid = True
    if row.get("serenity_tier") == "F":
        auto_avoid = True
    if len(flags) >= 3:
        auto_avoid = True

    return score, auto_avoid


def _model_to_dict(model: DiscoverySerenityScore) -> dict[str, Any]:
    """DB 모델 → 스코어 계산용 dict (list 필드 파싱)."""
    return {
        "ticker": model.ticker,
        "bottleneck_score": model.bottleneck_score,
        "bom_pct": model.bom_pct,
        "contracted_arr_multiple": model.contracted_arr_multiple,
        "mag7_customer_count": model.mag7_customer_count,
        "gaap_gross_margin": model.gaap_gross_margin,
        "is_pre_ramp": model.is_pre_ramp,
        "active_atm_pct_of_mc": model.active_atm_pct_of_mc,
        "financing_tier": model.financing_tier,
        "short_interest_pct": model.short_interest_pct,
        "is_profitable": model.is_profitable,
        "institutional_holdings_delta_30d": model.institutional_holdings_delta_30d,
        "serenity_tier": model.serenity_tier,
        "anti_pattern_flags": _parse_csv(model.anti_pattern_flags),
        "domain_tags": _parse_csv(model.domain_tags),
    }


async def refresh_ticker_score(ticker: str, *, days: int = 90) -> Optional[dict]:
    """단일 티커 스코어 재계산 · 기존 seed 필드 + 최근 signal aggregate 병합.

    반환: 갱신 후 상태 dict (스코어·avoid 포함) · seed 없으면 None.
    """
    async with get_session() as session:
        existing = (await session.execute(
            select(DiscoverySerenityScore).where(DiscoverySerenityScore.ticker == ticker)
        )).scalar_one_or_none()
        if existing is None:
            logger.debug("[serenity] seed 없음 · ticker=%s · 스코어 계산 skip", ticker)
            return None

    row = _model_to_dict(existing)
    agg = await aggregate_signals(ticker, days=days)
    row["last_signal_at"] = agg["last_signal_at"]

    score, avoid = compute_serenity_score(row)

    async with get_session() as session:
        target = (await session.execute(
            select(DiscoverySerenityScore).where(DiscoverySerenityScore.ticker == ticker)
        )).scalar_one()
        target.total_score = score
        target.auto_avoid = avoid
        target.last_signal_at = agg["last_signal_at"]
        target.updated_at = datetime.utcnow()
        await session.commit()

    return {
        "ticker": ticker,
        "total_score": score,
        "auto_avoid": avoid,
        "mention_count": agg["mention_count"],
        "bullish_pct": agg["bullish_pct"],
        "last_signal_at": agg["last_signal_at"],
    }


async def refresh_all_scores(*, days: int = 90) -> dict:
    """seed 존재하는 티커 + 최근 signal 티커 union · 전체 스코어 재계산.

    반환: {"scored": N, "skipped": M, "avoided": K}
    """
    seed_tickers: list[str] = []
    async with get_session() as session:
        rows = (await session.execute(select(DiscoverySerenityScore.ticker))).scalars().all()
        seed_tickers = list(rows)
    signal_tickers = await active_tickers(days=days)
    targets = sorted(set(seed_tickers) | set(signal_tickers))

    scored = skipped = avoided = 0
    for tk in targets:
        result = await refresh_ticker_score(tk, days=days)
        if result is None:
            skipped += 1
            continue
        scored += 1
        if result["auto_avoid"]:
            avoided += 1
    return {"scored": scored, "skipped": skipped, "avoided": avoided, "targets": len(targets)}


async def upsert_seed(seed: dict[str, Any]) -> None:
    """단일 티커 seed upsert · IntegrityError race 시 안전.

    seed dict 예시:
      {"ticker": "NBIS", "financing_tier": "S", "serenity_tier": "S",
       "domain_tags": ["neocloud"], "anti_pattern_flags": [], "bottleneck_score": 9, ...}
    """
    ticker = seed["ticker"]

    def _apply(target: DiscoverySerenityScore) -> None:
        for key, val in seed.items():
            if key == "ticker":
                continue
            if key in ("anti_pattern_flags", "domain_tags"):
                setattr(target, key, _csv_from_list(val) if isinstance(val, list) else val)
                continue
            if hasattr(target, key):
                setattr(target, key, val)

    async with get_session() as session:
        existing = (await session.execute(
            select(DiscoverySerenityScore).where(DiscoverySerenityScore.ticker == ticker)
        )).scalar_one_or_none()
        if existing:
            _apply(existing)
            existing.updated_at = datetime.utcnow()
            await session.commit()
            return

        new_row = DiscoverySerenityScore(ticker=ticker)
        _apply(new_row)
        session.add(new_row)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            # race: 다른 프로세스가 방금 만든 seed → update 로 재시도
            async with get_session() as s2:
                target = (await s2.execute(
                    select(DiscoverySerenityScore).where(DiscoverySerenityScore.ticker == ticker)
                )).scalar_one()
                _apply(target)
                target.updated_at = datetime.utcnow()
                await s2.commit()
