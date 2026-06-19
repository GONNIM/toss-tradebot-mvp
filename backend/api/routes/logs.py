"""감사 로그 라우트."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import desc, select

from backend.api.schemas import LogEntry
from backend.services.db import get_session
from backend.services.models import Log

router = APIRouter()


@router.get("/", response_model=list[LogEntry])
async def list_logs(
    limit: int = Query(50, ge=1, le=500),
    level: str | None = Query(None, regex="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$"),
    category: str | None = None,
    hours: int = Query(24, ge=1, le=720),
):
    """최근 로그 (필터 옵션)."""
    cutoff = datetime.now() - timedelta(hours=hours)
    async with get_session() as session:
        stmt = select(Log).where(Log.created_at >= cutoff)
        if level:
            stmt = stmt.where(Log.level == level)
        if category:
            stmt = stmt.where(Log.category == category)
        stmt = stmt.order_by(desc(Log.created_at)).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()
