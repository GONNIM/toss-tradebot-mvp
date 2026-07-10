"""Idempotency 캐시 — v2 트랙 C Phase 1.

order_uuid 를 키로 이전 OrderResult 를 24h 재사용.
`order_audit` 테이블 재활용 (별도 파일/캐시 불필요 · 감사와 자연 정합).

스펙: docs/plans/tradebot-mvp-v2/02-omi-interface-spec.md §6-1 idempotency
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.services.models import OrderAudit

from .audit import get_order_audit
from .models import Fill, OrderResult, OrderStatus

logger = logging.getLogger(__name__)

_IDEMPOTENCY_WINDOW = timedelta(hours=24)


def _row_to_result(row: OrderAudit) -> OrderResult:
    """order_audit row → OrderResult 재구성.

    fills 는 raw_response 에 저장되어 있을 수 있으므로 파싱 시도;
    실패 시 avg_fill_price·filled_qty 로 단일 Fill 재구성.
    """
    raw: Optional[dict] = None
    if row.raw_response:
        try:
            raw = json.loads(row.raw_response)
        except json.JSONDecodeError:
            raw = None

    fills: list[Fill] = []
    if row.filled_qty and row.avg_fill_price:
        fills.append(
            Fill(
                price=row.avg_fill_price,
                qty=row.filled_qty,
                executed_at=row.completed_at or row.created_at,
                fee=row.total_fee or 0.0,
            )
        )

    try:
        status = OrderStatus(row.status)
    except ValueError:
        logger.warning("알 수 없는 status=%r · ERROR 로 정규화", row.status)
        status = OrderStatus.ERROR

    return OrderResult(
        order_uuid=row.order_uuid,
        broker_order_id=row.broker_order_id,
        status=status,
        fills=fills,
        avg_fill_price=row.avg_fill_price,
        filled_qty=row.filled_qty or 0,
        remaining_qty=max(0, row.qty - (row.filled_qty or 0)),
        error_code=row.error_code,
        error_message=row.error_message,
        submitted_at=row.submitted_at,
        completed_at=row.completed_at,
        raw_response=raw,
    )


async def find_cached_result(order_uuid: str) -> Optional[OrderResult]:
    """24h 이내 동일 order_uuid 로 처리된 이전 결과가 있으면 반환."""
    row = await get_order_audit(order_uuid)
    if row is None:
        return None
    created_at = row.created_at
    if created_at is None:
        return _row_to_result(row)
    # SQLite 는 naive datetime 저장 · UTC 로 가정
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if datetime.now(tz=timezone.utc) - created_at > _IDEMPOTENCY_WINDOW:
        logger.info(
            "idempotency 캐시 만료 · uuid=%s · 신규 주문 허용", order_uuid[:8]
        )
        return None
    return _row_to_result(row)
