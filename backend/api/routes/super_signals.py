"""Super Signal API — v2 트랙 C Phase 3.

- GET /api/v1/super-signals — 최근 승격 이벤트
- POST /api/v1/super-signals/promote — 수동 즉시 승격+실행 (Ops)
- GET /api/v1/super-signals/hits — 최근 SignalHit (디버그)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query
from sqlalchemy import select

from backend.discovery.super_signal import (
    get_recent_super_signals,
    promote_and_execute,
)
from backend.services.db import get_session
from backend.services.models import SignalHit, SuperSignal

router = APIRouter()


def _row_to_dict(row: SuperSignal) -> dict:
    try:
        meta = json.loads(row.metadata_json) if row.metadata_json else {}
    except (TypeError, ValueError):
        meta = {}
    return {
        "id": row.id,
        "ticker": row.ticker,
        "intensity": row.intensity,
        "sources": row.sources,
        "hit_count": row.hit_count,
        "first_hit_at": row.first_hit_at.isoformat() if row.first_hit_at else None,
        "last_hit_at": row.last_hit_at.isoformat() if row.last_hit_at else None,
        "promoted_at": row.promoted_at.isoformat() if row.promoted_at else None,
        "order_uuid": row.order_uuid,
        "oco_id": row.oco_id,
        "oco_status": row.oco_status,
        "metadata": meta,
    }


@router.get("")
async def list_super_signals(limit: int = Query(30, ge=1, le=200)):
    rows = await get_recent_super_signals(limit=limit)
    return [_row_to_dict(r) for r in rows]


@router.post("/promote")
async def manual_promote():
    """관리자 즉시 승격+OCO 실행 (스케줄러 대기 없이)."""
    results = await promote_and_execute()
    return {"count": len(results), "results": results}


@router.get("/hits")
async def recent_hits(
    ticker: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=90),
    limit: int = Query(100, ge=1, le=500),
):
    since = datetime.now(tz=timezone.utc) - timedelta(days=days)
    async with get_session() as session:
        stmt = (
            select(SignalHit)
            .where(SignalHit.hit_at >= since)
            .order_by(SignalHit.hit_at.desc())
            .limit(limit)
        )
        if ticker:
            stmt = stmt.where(SignalHit.ticker == ticker)
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "ticker": r.ticker,
            "source": r.source,
            "signal_id": r.signal_id,
            "score": r.score,
            "action": r.action,
            "hit_at": r.hit_at.isoformat() if r.hit_at else None,
        }
        for r in rows
    ]
