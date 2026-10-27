"""1025-08 · 「내 계좌」 토스 실계좌 보유 (관리자 전용).

보유 + 종목별 사실 (보유 일수 · 최고가 대비 · 청산 계획 유무) + 토스증권 주문 화면 주소.
사이트는 주문을 넣지 않는다. 토스 원본 값 우선 · 미국 종목 원화는 토스 참고 환율.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select

from backend.api.auth import require_sniper_token
from backend.api.schemas import AccountHolding, AccountHoldingsResponse, BrokerLinkOut
from backend.services import broker_links, fx, real_holdings
from backend.services.db import get_session
from backend.services.models import TossStockCode

router = APIRouter()


@router.get("/holdings", response_model=AccountHoldingsResponse, dependencies=[Depends(require_sniper_token)])
async def get_holdings():
    fetched_at = datetime.now(timezone.utc)
    try:
        from backend.execution.brokers.toss_client import get_toss_client

        client = get_toss_client()
        raw = await asyncio.to_thread(client.holdings)
    except Exception as exc:  # noqa: BLE001
        return AccountHoldingsResponse(ok=False, error_reason=f"{type(exc).__name__}: {str(exc)[:180]}",
                                       fetched_at=fetched_at)
    rows = real_holdings.parse_items(raw)
    quote = await asyncio.to_thread(fx.usd_krw, client)
    today = fetched_at.astimezone(real_holdings.KST).date()

    from backend.api.routes.positions import _latest_judgment

    out: list[AccountHolding] = []
    async with get_session() as session:
        codes = {r.symbol: r for r in (await session.execute(
            select(TossStockCode).where(TossStockCode.symbol.in_([r.symbol for r in rows]))
        )).scalars().all()}
        for r in rows:
            facts = await real_holdings.holding_facts(session, r, today)
            rate = 1.0 if r.currency == "KRW" else quote.rate
            judgment = await _latest_judgment(session, r.symbol)
            out.append(AccountHolding(
                symbol=r.symbol, name=r.name, market=r.market, currency=r.currency, qty=r.qty,
                avg_price=r.avg_price, current_price=r.last_price, market_value=r.market_value,
                purchase_amount=r.purchase_amount, pnl=r.pnl, pnl_pct=r.pnl_pct, pnl_source=r.pnl_source,
                market_value_krw=round(r.market_value * rate, 0) if r.market_value is not None else None,
                pnl_krw=round(r.pnl * rate, 0) if r.pnl is not None else None,
                # 1026-01 · 판정만 있고 손절가·목표가가 없으면 「있음」 이 아니다 (Fable #121 권고)
                has_exit_plan=judgment is not None and (judgment.invalidation_price is not None
                                                        or judgment.target_price is not None),
                link=BrokerLinkOut(**broker_links.broker_link(r.symbol, codes.get(r.symbol))),
                **facts,
            ))
    return AccountHoldingsResponse(ok=True, fetched_at=fetched_at, fx_rate=quote.rate, fx_source=quote.source,
                                   fx_valid_from=quote.valid_from, holdings=out)
