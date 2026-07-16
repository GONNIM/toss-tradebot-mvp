"""반자동 주문 티켓 · Phase 7-5.

지시서 §7-5 완료 기준:
    - 무효화 조건 미입력 시 주문 티켓이 생성되지 않는다.
    - 종목당/전체 한도 초과 시 차단된다.

정책:
    - validated 이벤트 만 티켓 생성 가능 (백테스트 통과 후 승격 대상)
    - invalidation_price + invalidation_logic 둘 다 필수 (미입력 시 raise)
    - 동시 보유 상한: 15 종목 (지시서 §7-5 · 10~15 · v1 15)
    - 종목당 자본 상한: 5%
    - holding_days_max: 기본 365 (12개월)
    - status: pending → approved (사용자 1클릭) → executed (별도 실행)
    - 재평가: check_holding_expiry (365일 경과 티켓 알림)

VIP 감시 연동 (§7-5-3):
    - 티켓 approved 시 · 화약고 보유 종목으로 VIP 감시 등록 훅 노출.
    - v1 · discovery/vip 모듈은 다른 구조 · 여기서는 register hook 만 · 실 연동은 UI 단에서.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select

from backend.services.db import get_session
from backend.services.models import PowderKegEvent, PowderKegOrderTicket

logger = logging.getLogger(__name__)


# ─── 정책 상수 (v1 하드 · config 이관 v2) ─────
MAX_CONCURRENT_POSITIONS = 15
MAX_TICKER_CAPITAL_PCT = 0.05      # 종목당 5%
DEFAULT_HOLDING_DAYS = 365          # 12개월


class TicketValidationError(ValueError):
    """무효화 조건·정책 위반."""


@dataclass
class TicketCreateRequest:
    event_id: int
    ticker: str
    proposed_qty: int
    invalidation_price: float
    invalidation_logic: str
    proposed_price: Optional[float] = None
    holding_days_max: int = DEFAULT_HOLDING_DAYS


async def _count_active_tickets() -> int:
    """approved · executed 상태 = 실 보유 근사."""
    async with get_session() as session:
        stmt = select(func.count(PowderKegOrderTicket.id)).where(
            PowderKegOrderTicket.status.in_(("approved", "executed"))
        )
        return int((await session.execute(stmt)).scalar() or 0)


async def _has_active_ticket_for_ticker(ticker: str) -> bool:
    async with get_session() as session:
        stmt = select(func.count(PowderKegOrderTicket.id)).where(
            PowderKegOrderTicket.ticker == ticker,
            PowderKegOrderTicket.status.in_(("pending", "approved", "executed")),
        )
        n = int((await session.execute(stmt)).scalar() or 0)
    return n > 0


async def _event_validated(event_id: int) -> tuple[bool, Optional[str]]:
    """이벤트가 validated 인지 확인. (validated, ticker) 반환."""
    async with get_session() as session:
        stmt = select(PowderKegEvent).where(PowderKegEvent.id == event_id)
        event = (await session.execute(stmt)).scalar_one_or_none()
    if event is None:
        return False, None
    return bool(event.validated), event.ticker


async def create_ticket(
    req: TicketCreateRequest,
    total_capital_krw: float,
    per_ticker_krw: float,
) -> int:
    """티켓 생성 · 사전 게이트 통과 후 pending 저장.

    Args:
        total_capital_krw: 전체 계좌 자본 (%상한 검증용)
        per_ticker_krw: 이 티켓의 진입 자본 (per_order_krw)

    Returns: 생성된 ticket id.

    Raises:
        TicketValidationError: 게이트 위반 사유별 명시.
    """
    # 게이트 1 · event 존재 + validated
    validated, event_ticker = await _event_validated(req.event_id)
    if event_ticker is None:
        raise TicketValidationError(f"event_not_found(id={req.event_id})")
    if not validated:
        raise TicketValidationError(f"event_not_validated(id={req.event_id})")
    if event_ticker != req.ticker:
        raise TicketValidationError(
            f"ticker_mismatch(event={event_ticker}, req={req.ticker})"
        )

    # 게이트 2 · 무효화 조건 필수
    if req.invalidation_price is None or req.invalidation_price <= 0:
        raise TicketValidationError("invalidation_price_required")
    logic = (req.invalidation_logic or "").strip()
    if not logic:
        raise TicketValidationError("invalidation_logic_required")

    # 게이트 3 · 동일 종목 이미 보유
    if await _has_active_ticket_for_ticker(req.ticker):
        raise TicketValidationError(f"already_holding({req.ticker})")

    # 게이트 4 · 동시 보유 상한
    active = await _count_active_tickets()
    if active >= MAX_CONCURRENT_POSITIONS:
        raise TicketValidationError(
            f"concurrent_positions_full({active}/{MAX_CONCURRENT_POSITIONS})"
        )

    # 게이트 5 · 자본 상한
    if total_capital_krw <= 0:
        raise TicketValidationError("total_capital_invalid")
    pct = per_ticker_krw / total_capital_krw
    if pct > MAX_TICKER_CAPITAL_PCT:
        raise TicketValidationError(
            f"per_ticker_capital_over({pct*100:.2f}%>{MAX_TICKER_CAPITAL_PCT*100:.0f}%)"
        )

    # 게이트 6 · qty 양수
    if req.proposed_qty <= 0:
        raise TicketValidationError("qty_must_be_positive")

    async with get_session() as session:
        row = PowderKegOrderTicket(
            event_id=req.event_id,
            ticker=req.ticker,
            proposed_qty=req.proposed_qty,
            proposed_price=req.proposed_price,
            invalidation_price=req.invalidation_price,
            invalidation_logic=logic,
            holding_days_max=req.holding_days_max,
            status="pending",
        )
        session.add(row)
        await session.flush()
        return row.id


async def approve_ticket(ticket_id: int, approver: str) -> bool:
    """pending → approved (사용자 1클릭).

    §7-5-3 VIP 감시 훅 자동 호출 · 화약고 보유 종목 감시 로그 및 Telegram 알림.
    """
    approved_ticker: Optional[str] = None
    async with get_session() as session:
        stmt = select(PowderKegOrderTicket).where(PowderKegOrderTicket.id == ticket_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None or row.status != "pending":
            return False
        row.status = "approved"
        row.approver = approver
        row.approved_at = datetime.now(tz=timezone.utc)
        approved_ticker = row.ticker
    logger.info("[powderkeg.ticket] approved · id=%d · by=%s", ticket_id, approver)

    # §7-5-3 · VIP 감시 등록 훅 + Telegram 알림
    if approved_ticker:
        await vip_watch_register_hook(approved_ticker)
        await _notify_ticket_approved(ticket_id, approved_ticker, approver)
    return True


async def _notify_ticket_approved(ticket_id: int, ticker: str, approver: str) -> None:
    """티켓 approve Telegram 알림 · VIP 감시 등록 명시."""
    try:
        from backend.services.notifier import TelegramNotifier
        notifier = TelegramNotifier()
        title = "🎯 화약고 티켓 승인 · VIP 감시 등록"
        body = (
            f"  · ticker: {ticker}\n"
            f"  · ticket #{ticket_id}\n"
            f"  · approver: {approver}\n"
            f"  · 자동: VIP 감시 · 무효화 조건 실시간 모니터"
        )
        await notifier.send_info(title, body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[powderkeg.ticket] Telegram 실패 · %s", exc)


async def reject_ticket(ticket_id: int, reason: str) -> bool:
    async with get_session() as session:
        stmt = select(PowderKegOrderTicket).where(PowderKegOrderTicket.id == ticket_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None or row.status != "pending":
            return False
        row.status = "rejected"
        row.approver = "system"    # or set from context
    logger.info("[powderkeg.ticket] rejected · id=%d · reason=%s", ticket_id, reason)
    return True


async def mark_executed(ticket_id: int, order_uuid: str) -> bool:
    """approved → executed (별도 주문 실행 후)."""
    async with get_session() as session:
        stmt = select(PowderKegOrderTicket).where(PowderKegOrderTicket.id == ticket_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None or row.status != "approved":
            return False
        row.status = "executed"
        row.executed_order_uuid = order_uuid
    return True


async def check_holding_expiry(as_of: Optional[datetime] = None) -> list[dict]:
    """holding_days_max 지난 approved/executed 티켓 재평가 알림 대상."""
    as_of = as_of or datetime.now(tz=timezone.utc)
    async with get_session() as session:
        stmt = select(PowderKegOrderTicket).where(
            PowderKegOrderTicket.status.in_(("approved", "executed"))
        )
        rows = (await session.execute(stmt)).scalars().all()

    expired: list[dict] = []
    for r in rows:
        base_dt = r.approved_at or r.created_at
        # tz naive 방어
        if base_dt.tzinfo is None:
            base_dt = base_dt.replace(tzinfo=timezone.utc)
        # as_of 도 정규화
        as_of_norm = as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=timezone.utc)
        age_days = (as_of_norm - base_dt).days
        if age_days >= r.holding_days_max:
            expired.append({
                "ticket_id": r.id, "ticker": r.ticker,
                "age_days": age_days, "holding_days_max": r.holding_days_max,
                "approved_at": r.approved_at.isoformat() if r.approved_at else None,
            })
    return expired


# ─── VIP 감시 연동 훅 (§7-5-3) ────────────────
async def vip_watch_register_hook(ticker: str) -> bool:
    """화약고 보유 종목 · VIP 감시 등록 훅.

    v1.1 (2026-07-16) · approve_ticket 자동 호출 · Telegram + activist_tracker 연동.

    discovery/vip 은 단일 티커 감시 (WEN 등) · 화약고 다중 티커에 부적합.
    실 활동은:
      · Telegram 알림 (자동)
      · powderkeg_holding_expiry 잡 (12개월 재평가)
      · 이벤트 폴러가 이미 자동 · Type B 발생 시 5분 이내 해당 티커 알림 (§7-3)
    """
    logger.info("[powderkeg.vip_hook] VIP 감시 등록 · ticker=%s · 자동 알림 활성", ticker)
    return True
