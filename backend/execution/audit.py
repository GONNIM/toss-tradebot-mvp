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
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from backend.services.db import get_session
from backend.services.models import OrderAudit

from .models import BrokerKind, OrderRequest, OrderResult

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


async def daily_realized_pnl(broker_kind: BrokerKind, since: datetime) -> float:
    """일일 실현 손익 (Kill Switch 트리거 근거).

    간이 계산: since 이후 filled 매도 fills 만 집계 · 정확한 계산은 Phase 3.
    """
    async with get_session() as session:
        stmt = (
            select(OrderAudit)
            .where(OrderAudit.broker_kind == broker_kind.value)
            .where(OrderAudit.side == "sell")
            .where(OrderAudit.status.in_(["filled", "partial"]))
            .where(OrderAudit.created_at >= since)
        )
        rows = (await session.execute(stmt)).scalars().all()

    # 매우 단순한 근사치 — Phase 3 에서 매수 평단 대비 정확 계산
    total_fill_value = sum(
        (row.avg_fill_price or 0.0) * (row.filled_qty or 0) - (row.total_fee or 0.0)
        for row in rows
    )
    return total_fill_value
