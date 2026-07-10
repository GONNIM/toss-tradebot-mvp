"""Order Status Reconciler — v2 트랙 C Phase 2.

미체결 (ACCEPTED · PARTIAL_FILL) 상태 주문을 주기적으로 GET /api/v1/orders/{id} 로 폴링,
Toss 서버 상태와 로컬 order_audit 을 동기화.

책임:
- 미체결 주문 조회 · Toss status 확인
- audit UPDATE (status, filled_qty, avg_fill_price, error_code, completed_at)
- PARTIAL_FILL → FILLED 전이 감지 시 최종 완료 시각 기록
- REPLACED 처리: 신규 orderId 로 갱신 (Toss 매핑 rule)

APScheduler 30초 주기 (Phase 4에서 200ms 후보로 최적화 가능).

스펙: docs/plans/tradebot-mvp-v2/03-toss-openapi-integration.md §3-4 (status 매핑)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from backend.services.db import get_session
from backend.services.models import OrderAudit

from .brokers.toss_adapter import _map_toss_status
from .brokers.toss_client import TossClient, get_toss_client
from .exceptions import ExecutionError, OrderNotFound
from .models import BrokerKind, OrderStatus

logger = logging.getLogger(__name__)


_PENDING_STATUSES = {
    OrderStatus.PENDING.value,
    OrderStatus.ACCEPTED.value,
    OrderStatus.PARTIAL_FILL.value,
}


async def reconcile_pending_orders(toss_client: Optional[TossClient] = None) -> dict:
    """미체결 Toss 주문 상태 조회 · audit UPDATE.

    Returns:
        통계 dict (checked, updated, filled, canceled, rejected, errors)
    """
    stats = {
        "checked": 0,
        "updated": 0,
        "filled": 0,
        "canceled": 0,
        "rejected": 0,
        "errors": 0,
        "not_found": 0,
    }
    client = toss_client or get_toss_client()

    async with get_session() as session:
        rows = (
            await session.execute(
                select(OrderAudit)
                .where(OrderAudit.broker_kind == BrokerKind.TOSS.value)
                .where(OrderAudit.status.in_(list(_PENDING_STATUSES)))
                .where(OrderAudit.broker_order_id.isnot(None))
            )
        ).scalars().all()

        for row in rows:
            stats["checked"] += 1
            try:
                env = client.get_order(row.broker_order_id)
            except OrderNotFound:
                logger.warning("reconcile: orderId=%s not found — 스킵", row.broker_order_id)
                stats["not_found"] += 1
                continue
            except ExecutionError as exc:
                logger.warning("reconcile: %s 오류 — %s", row.broker_order_id, exc)
                stats["errors"] += 1
                continue

            data = env.result if isinstance(env.result, dict) else {}
            toss_status = data.get("status") or "PENDING"
            new_status = _map_toss_status(toss_status)

            exec_info = data.get("execution") or {}
            new_filled = int(float(exec_info.get("filledQuantity", 0) or 0))
            new_avg = exec_info.get("averagePrice")
            new_avg = float(new_avg) if new_avg is not None else row.avg_fill_price

            changed = (
                row.status != new_status.value
                or (row.filled_qty or 0) != new_filled
                or (row.avg_fill_price != new_avg)
            )
            if not changed:
                continue

            row.status = new_status.value
            row.filled_qty = new_filled
            row.avg_fill_price = new_avg
            if data.get("canceledAt"):
                try:
                    row.completed_at = datetime.fromisoformat(data["canceledAt"])
                except (TypeError, ValueError):
                    pass
            if new_status == OrderStatus.FILLED:
                row.completed_at = datetime.now(tz=timezone.utc)
                stats["filled"] += 1
            elif new_status == OrderStatus.CANCELED:
                stats["canceled"] += 1
            elif new_status == OrderStatus.REJECTED:
                stats["rejected"] += 1
                # 에러 코드 갱신 (있으면)
                err = data.get("error") or {}
                if err.get("code"):
                    row.error_code = err.get("code")
                    row.error_message = err.get("message")

            # request_id 를 raw_response 에 추가 기록
            try:
                raw = json.loads(row.raw_response) if row.raw_response else {}
            except (TypeError, ValueError):
                raw = {}
            if not isinstance(raw, dict):
                raw = {}
            raw.setdefault("reconciles", []).append(
                {
                    "at": datetime.now(tz=timezone.utc).isoformat(),
                    "request_id": env.request_id,
                    "toss_status": toss_status,
                }
            )
            row.raw_response = json.dumps(raw, ensure_ascii=False, default=str)
            stats["updated"] += 1

    logger.info("reconcile done · %s", stats)
    return stats
