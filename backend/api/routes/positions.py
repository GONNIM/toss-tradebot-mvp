"""포지션 라우트 — Phase K (Toss API) 활성 후 작동.

2026-08-14 · 보유 작전실 (`/plan`) 추가: Toss holdings + UserJudgment + Activist 통합.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select

from backend.api.auth import require_sniper_token
from backend.api.schemas import (
    PositionCard,
    PositionExitPlan,
    PositionResponse,
    PositionsPlanResponse,
)
from backend.services.db import get_session
from backend.services.models import AccountPosition, UserJudgment

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=list[PositionResponse])
async def list_positions():
    """현재 보유 종목 (Phase K 활성 후 데이터 채워짐)."""
    async with get_session() as session:
        stmt = select(AccountPosition)
        result = await session.execute(stmt)
        positions = result.scalars().all()
        return [
            PositionResponse(
                ticker=p.ticker,
                shares=p.qty or 0,
                avg_cost=p.avg_price or 0,
                current_price=None,
                unrealized_pnl_pct=None,
                risk_level="MED",
            )
            for p in positions
        ]


# ─── 보유 작전실 (2026-08-14 · Fable 5) ────────────────────────────────


def _to_float(v, default=None):
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


async def _latest_judgment(session, ticker: str) -> Optional[UserJudgment]:
    """티커별 최신 판정 1건 (있으면)."""
    stmt = (
        select(UserJudgment)
        .where(UserJudgment.ticker == ticker.upper())
        .order_by(desc(UserJudgment.ts))
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _build_exit_plan(judgment: Optional[UserJudgment], current_price: Optional[float]) -> PositionExitPlan:
    """판정 → 청산 계획 3칸."""
    if judgment is None:
        return PositionExitPlan(has_plan=False)

    inv = judgment.invalidation_price
    tgt = judgment.target_price
    horizon = judgment.horizon_days
    deadline = judgment.ts + timedelta(days=horizon) if horizon else None

    price_parts = []
    if inv is not None:
        price_parts.append(f"손절 {inv:.4f}")
    if tgt is not None:
        price_parts.append(f"목표 {tgt:.4f}")
    price_cond = " · ".join(price_parts) if price_parts else None

    thesis = (judgment.thesis_md or "").strip()
    excerpt = thesis[:200] + ("…" if len(thesis) > 200 else "") if thesis else None

    # 트리거 도달 판정 (broker-api-source-of-truth · 가격 원본으로 비교)
    trigger_hit = False
    trigger_reason = None
    if current_price is not None:
        if inv is not None and current_price <= inv:
            trigger_hit = True
            trigger_reason = "invalidation_hit"
        elif tgt is not None and current_price >= tgt:
            trigger_hit = True
            trigger_reason = "target_reached"

    return PositionExitPlan(
        has_plan=True,
        price_condition=price_cond,
        event_condition=None,  # thesis 안 사건 조건 구조화는 후속 (지금은 excerpt 로만)
        deadline=deadline,
        thesis_excerpt=excerpt,
        judgment_id=judgment.id,
        horizon_days=horizon,
        trigger_hit=trigger_hit,
        trigger_reason=trigger_reason,
    )


@router.get(
    "/plan",
    response_model=PositionsPlanResponse,
    dependencies=[Depends(require_sniper_token)],
)
async def get_positions_plan():
    """보유 작전실 · 실 보유 + 저널 청산 계획 + Activist 필링 통합.

    Fable 5 (2026-08-14): 청산 계획 없이 걸린 사활 = 감정에 넘긴 결정.
    이 endpoint 가 캠페인 트리거 (⚠ 미기록 종목 = 적색 카드).
    """
    fetched_at = datetime.now(timezone.utc)
    positions: list[PositionCard] = []
    missing = 0

    try:
        from backend.execution.brokers.toss_client import get_toss_client
        client = get_toss_client()
        holdings_dict = client.holdings() or {}
    except Exception as exc:  # noqa: BLE001
        return PositionsPlanResponse(
            ok=False,
            error_reason=f"{type(exc).__name__}: {str(exc)[:180]}",
            fetched_at=fetched_at,
        )

    items = holdings_dict.get("items") or []

    # Activist universe 조회 (심볼 매치용 · 실패해도 계속)
    activist_symbols: set[str] = set()
    try:
        from backend.discovery.activist.repository import list_universe_symbols  # type: ignore
        activist_symbols = set(await list_universe_symbols())
    except Exception:  # noqa: BLE001
        pass

    async with get_session() as session:
        for item in items:
            if not isinstance(item, dict):
                continue
            sym = str(item.get("symbol") or "").strip()
            if not sym:
                continue
            qty = _to_float(item.get("quantity"), 0) or 0
            if qty <= 0:
                continue
            avg = _to_float(item.get("averagePurchasePrice"), 0) or 0
            cur = _to_float(item.get("lastPrice"))
            currency = (item.get("currency") or "").upper() or ("KRW" if sym.isdigit() else "USD")
            name = item.get("name") or item.get("koreanName") or item.get("displayName")

            cost = round(qty * avg, 4)
            mv = round(qty * cur, 4) if cur else None
            pnl = round(mv - cost, 4) if mv is not None else None
            pnl_pct = round(pnl / cost * 100, 2) if (pnl is not None and cost > 0) else None

            if currency == "KRW":
                mv_krw = mv
            else:
                mv_krw = round((mv or 0) * 1330, 0) if mv is not None else None

            judgment = await _latest_judgment(session, sym)
            exit_plan = _build_exit_plan(judgment, cur)
            if not exit_plan.has_plan:
                missing += 1

            is_activist = sym.upper() in activist_symbols

            positions.append(PositionCard(
                symbol=sym,
                name=name,
                currency=currency,
                qty=qty,
                avg_price=avg,
                current_price=cur,
                market_value=mv,
                market_value_krw=mv_krw,
                unrealized_pnl=pnl,
                unrealized_pnl_pct=pnl_pct,
                exit_plan=exit_plan,
                activist_symbol=is_activist,
                recent_filings=[],  # 필링 상세는 후속 (activist 라우트에 별도 endpoint 존재 시 조인)
            ))

    return PositionsPlanResponse(
        ok=True,
        fetched_at=fetched_at,
        positions=positions,
        total_missing_plans=missing,
    )
