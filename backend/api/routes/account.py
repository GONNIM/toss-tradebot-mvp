"""1025-08 · 「내 계좌」 토스 실계좌 보유 (관리자 전용).

보유 + 종목별 사실 (보유 일수 · 최고가 대비 · 청산 계획 유무) + 토스증권 주문 화면 주소.
사이트는 주문을 넣지 않는다. 토스 원본 값 우선 · 미국 종목 원화는 토스 참고 환율.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from backend.api.auth import require_sniper_token
from backend.api.schemas import AccountHolding, AccountHoldingsResponse, BrokerLinkOut
from backend.services import broker_links, fx, holdings_swing, real_holdings

_log = logging.getLogger(__name__)
VIP_TOSS_ERROR = "토스 보유 조회에 실패했습니다. 잠시 뒤 다시 열어 주십시오."
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


# ─── 1108-02 · 보유 종목 사실 (스윙 2단계) · DB 만 읽음 (토스·외부 호출 없음) ─────────────────

class SwingHorizonBody(BaseModel):
    """보내지 않은 칸은 그대로 · deadline null = 기본값으로 되돌림 · memo "" = 지움."""

    horizon: Literal["long", "short", "unset"]  # 이 셋 말고는 422
    deadline: Optional[date] = None
    memo: Optional[str] = None

    @field_validator("memo")
    @classmethod
    def _memo(cls, v):
        return holdings_swing.clean_memo(v)  # 공백 정리 · 200자 · 제어 문자 → 422


@router.get("/swing", dependencies=[Depends(require_sniper_token)])
async def get_swing():
    today = datetime.now(timezone.utc).astimezone(real_holdings.KST).date()
    async with get_session() as session:
        cards = await holdings_swing.build_cards(session, today)
    return {"ok": True, "generated_at": datetime.now(timezone.utc), "cards": cards}


@router.get("/vip", dependencies=[Depends(require_sniper_token)])
async def get_vip_tabs():
    """1110-02 · VIP 탭 목록 — 토스 보유 조회 1번 + DB (그 밖의 외부 호출 없음). 토스 값은 그대로 낸다."""
    from backend.services import vip_tabs

    fetched_at = datetime.now(timezone.utc)
    try:
        from backend.execution.brokers.toss_client import get_toss_client

        raw = await asyncio.to_thread(get_toss_client().holdings)
    except Exception as exc:  # noqa: BLE001
        # 예외 글자에 계정 정보가 섞일 수 있어 응답에는 고정 문구만 · 자세한 내용은 서버 로그에만 (1110-02 Fable 관찰 ㉡)
        _log.warning("[account/vip] 토스 보유 조회 실패: %s: %s", type(exc).__name__, exc)
        return {"ok": False, "error_reason": VIP_TOSS_ERROR, "fetched_at": fetched_at,
                "tabs": [], "limits": []}
    rows = real_holdings.parse_items(raw)
    today = fetched_at.astimezone(real_holdings.KST).date()
    async with get_session() as session:
        out = await vip_tabs.build_tabs(session, rows, today, fetched_at)
    return {"ok": True, "fetched_at": fetched_at, **out}


@router.patch("/swing/{market}/{ticker}", dependencies=[Depends(require_sniper_token)])
async def patch_swing_horizon(
    body: SwingHorizonBody,
    market: Literal["KR", "US"],
    ticker: str = Path(pattern=r"^[A-Za-z0-9.\-]{1,16}$"),
):
    ticker = ticker.upper()
    async with get_session() as session:
        kw = {}
        if "deadline" in body.model_fields_set:
            kw["deadline"] = body.deadline
        if "memo" in body.model_fields_set:
            kw["memo"] = body.memo
        try:
            saved = await holdings_swing.save_horizon(session, market, ticker, body.horizon, **kw)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"market": market, "ticker": ticker, **saved}
