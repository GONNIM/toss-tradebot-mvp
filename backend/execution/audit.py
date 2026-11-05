"""order_audit 테이블 CRUD 헬퍼 — v2 트랙 C Phase 1.

스펙: docs/plans/tradebot-mvp-v2/02-omi-interface-spec.md §9

사용:
    await record_order_result(broker_kind, req, result)
    await get_order_audit(order_uuid)
    await list_recent_audits(ticker=..., broker_kind=..., limit=100)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from backend.services.db import get_session
from backend.services.models import OrderAudit, SniperSignal

from .models import BrokerKind, OrderRequest, OrderResult, OrderStatus

logger = logging.getLogger(__name__)


def _serialize_raw(raw: Optional[dict]) -> Optional[str]:
    if raw is None:
        return None
    try:
        return json.dumps(raw, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        logger.warning("raw_response JSON 직렬화 실패 — %s", exc)
        return str(raw)


async def record_order_result(
    broker_kind: BrokerKind,
    req: OrderRequest,
    result: OrderResult,
) -> None:
    """주문 시도(성공/실패/취소)를 order_audit 테이블에 upsert."""
    async with get_session() as session:
        row = await session.get(OrderAudit, result.order_uuid)
        if row is None:
            row = OrderAudit(
                order_uuid=result.order_uuid,
                broker_kind=broker_kind.value,
                broker_order_id=result.broker_order_id,
                ticker=req.ticker,
                side=req.side.value,
                order_type=req.order_type.value,
                qty=req.qty,
                price=req.price,
                signal_source=req.signal_source,
                signal_id=req.signal_id,
                status=result.status.value,
                filled_qty=result.filled_qty,
                avg_fill_price=result.avg_fill_price,
                total_fee=sum(f.fee for f in result.fills),
                error_code=result.error_code,
                error_message=result.error_message,
                submitted_at=result.submitted_at,
                completed_at=result.completed_at,
                raw_response=_serialize_raw(result.raw_response),
            )
            session.add(row)
        else:
            # 재호출 (idempotency 재시도 또는 상태 갱신) — 최신 상태로 UPDATE
            row.broker_order_id = result.broker_order_id or row.broker_order_id
            row.status = result.status.value
            row.filled_qty = result.filled_qty
            row.avg_fill_price = result.avg_fill_price
            row.total_fee = sum(f.fee for f in result.fills)
            row.error_code = result.error_code
            row.error_message = result.error_message
            row.submitted_at = result.submitted_at or row.submitted_at
            row.completed_at = result.completed_at or row.completed_at
            raw = _serialize_raw(result.raw_response)
            if raw:
                row.raw_response = raw


async def record_direct_order(order_manager, req: OrderRequest, result: OrderResult) -> None:
    """SignalRouter 를 거치지 않는 직접 주문 (sniper · watchlist) 의 감사 기록 (1025-02).

    하루 손익 · /execution 화면 · Toss 미체결 대조 (reconciler) 의 근거.
    기록 실패는 주문 흐름을 막지 않음 · 그 청산은 하루 손익에서 「계산 불가」 로 잡힘.
    """
    try:
        await record_order_result(order_manager.broker_kind, req, result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[audit] 직접 주문 기록 실패 · %s · %s", req.signal_id, exc)


# 1105-03 · 아직 체결 결과가 정해지지 않은 진입 (reconciler 가 30초마다 갱신)
_ENTRY_OPEN = {OrderStatus.PENDING.value, OrderStatus.ACCEPTED.value, OrderStatus.PARTIAL_FILL.value}


async def bot_entry_qty(entry_order_uuid: Optional[str]) -> Optional[int]:
    """봇이 이 진입으로 산 수량 (1105-03 · 청산 때 이 수량까지만 판다).

    - 감사 행 없음 → None (호출 쪽이 근사)
    - 체결 수량 > 0 → 체결 수량
    - 체결 0 이고 아직 열린 주문 (pending · accepted · partial) → 주문 수량 (reconciler 지연 대비)
    - 체결 0 이고 끝난 주문 (canceled · rejected · error 등) → 0 (팔 것 없음)
    """
    if not entry_order_uuid:
        return None
    row = await get_order_audit(entry_order_uuid)
    if row is None:
        return None
    filled = int(row.filled_qty or 0)
    if filled > 0:
        return filled
    if (row.status or "") in _ENTRY_OPEN:
        return int(row.qty or 0)
    return 0


async def get_order_audit(order_uuid: str) -> Optional[OrderAudit]:
    """단일 감사 로그 조회 (get_order_status 재구성용)."""
    async with get_session() as session:
        return await session.get(OrderAudit, order_uuid)


async def list_recent_audits(
    *,
    ticker: Optional[str] = None,
    broker_kind: Optional[BrokerKind] = None,
    signal_source: Optional[str] = None,
    limit: int = 100,
) -> list[OrderAudit]:
    """최근 감사 로그 조회 (Frontend `/execution` 페이지용)."""
    async with get_session() as session:
        stmt = select(OrderAudit).order_by(OrderAudit.created_at.desc()).limit(limit)
        if ticker:
            stmt = stmt.where(OrderAudit.ticker == ticker)
        if broker_kind:
            stmt = stmt.where(OrderAudit.broker_kind == broker_kind.value)
        if signal_source:
            stmt = stmt.where(OrderAudit.signal_source == signal_source)
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)


@dataclass
class DailyPnl:
    """하루 실현 손익 계산 결과 (1025-02).

    realized_krw: 짝이 맞는 청산의 순손익 합 (손실이면 음수)
    computed: 계산한 청산 수
    uncomputable: 계산하지 못한 청산 [(sniper_signal id, 사유)]
    """
    realized_krw: float = 0.0
    computed: int = 0
    uncomputable: list[tuple[int, str]] = field(default_factory=list)


_FILLED = {OrderStatus.FILLED.value, OrderStatus.PARTIAL_FILL.value}


def _naive_utc(dt: datetime) -> datetime:
    """order_audit.created_at 은 naive UTC (server_default now()) · 비교용으로 맞춤."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def pair_pnl(buy: Optional[OrderAudit], sell: Optional[OrderAudit]) -> tuple[Optional[float], Optional[str]]:
    """매수·매도 감사 행 한 쌍의 순손익 (원).

    q = min(매도 체결 수량, 매수 체결 수량)
    손익 = 매도 평균가×q − 매도 수수료×q/매도 수량 − (매수 평균가×q + 매수 수수료×q/매수 수량)
    Returns: (손익, None) 또는 (None, 계산 불가 사유)
    """
    if buy is None:
        return None, "buy_audit_missing"
    if sell is None:
        return None, "sell_audit_missing"
    if buy.status not in _FILLED:
        return None, f"buy_status:{buy.status}"
    if sell.status not in _FILLED:
        return None, f"sell_status:{sell.status}"
    bq = int(buy.filled_qty or 0)
    sq = int(sell.filled_qty or 0)
    if bq <= 0 or sq <= 0 or not buy.avg_fill_price or not sell.avg_fill_price:
        return None, "qty_or_price_missing"
    if sq > bq:
        # 초과분 원가를 모름 (기존 보유가 섞임 등) · 보수적으로 계산 불가
        return None, f"sell_qty>{bq}"
    q = sq
    proceeds = sell.avg_fill_price * q - (sell.total_fee or 0.0) * q / sq
    cost = buy.avg_fill_price * q + (buy.total_fee or 0.0) * q / bq
    return proceeds - cost, None


async def daily_pnl_detail(broker_kind: BrokerKind, since: datetime) -> DailyPnl:
    """하루 실현 손익 (Kill Switch · 매수 전 손실 캡 근거 · 1025-02).

    대상: sniper_signal 중 exit_order_uuid 가 있는 청산 · 짝 감사 행 두 개 (매수 entry · 매도 exit).
    하루 경계: 매도 감사 행 created_at ≥ since (호출자는 UTC 00:00 = 한국 09:00 을 넘김 ·
    한국 정규장 기준 · 밤새 보유 뒤 다음 날 청산되면 다음 날 손익).
    매도 감사 행이 없는 오늘 청산은 sniper_signal 만으로는 날짜를 알 수 없어
    detected_at ≥ since 인 것만 계산 불가로 셈.
    signal_router 경로 주문 (sniper_signal 없음) 은 이 합계에 들어가지 않음.
    """
    since_n = _naive_utc(since)
    out = DailyPnl()
    async with get_session() as session:
        rows = (await session.execute(
            select(SniperSignal).where(SniperSignal.exit_order_uuid.is_not(None))
        )).scalars().all()
        for sig in rows:
            sell = await session.get(OrderAudit, sig.exit_order_uuid)
            if sell is not None:
                if sell.broker_kind != broker_kind.value or sell.created_at is None or sell.created_at < since_n:
                    continue
            else:
                det = sig.detected_at
                if det is None or _naive_utc(det) < since_n:
                    continue
            buy = await session.get(OrderAudit, sig.entry_order_uuid) if sig.entry_order_uuid else None
            pnl, why = pair_pnl(buy, sell)
            if pnl is None:
                out.uncomputable.append((sig.id, why or "unknown"))
            else:
                out.realized_krw += pnl
                out.computed += 1
    return out


async def daily_realized_pnl(broker_kind: BrokerKind, since: datetime) -> float:
    """하루 실현 손익 합 (원 · 손실 음수). 자세한 내용은 daily_pnl_detail."""
    return (await daily_pnl_detail(broker_kind, since)).realized_krw
