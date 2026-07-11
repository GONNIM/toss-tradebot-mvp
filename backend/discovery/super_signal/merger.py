"""Super Signal 병합기 — v2 트랙 C Phase 3.

30일 window 에서 티커별 히트 조회 → 2+ source AND intensity ≥ 임계 → SuperSignal INSERT.
중복 승격 방지: window 내 이미 승격된 티커는 스킵 (재승격은 이후 히트 도착 시 재판정).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from backend.services.db import get_session
from backend.services.models import SignalHit, SuperSignal

from .scoring import (
    PROMOTE_MIN_INTENSITY,
    PROMOTE_MIN_SOURCES,
    compute_intensity,
    source_weight,
)

logger = logging.getLogger(__name__)


WINDOW_DAYS = 30
REPROMOTE_COOLDOWN_HOURS = 24


async def promote_recent() -> list[SuperSignal]:
    """window 내 히트 검사 → 조건 만족 티커 승격.

    Returns:
        신규 승격된 SuperSignal 리스트.
    """
    now = datetime.now(tz=timezone.utc)
    window_start = now - timedelta(days=WINDOW_DAYS)
    cooldown_start = now - timedelta(hours=REPROMOTE_COOLDOWN_HOURS)

    promoted: list[SuperSignal] = []

    async with get_session() as session:
        # 최근 window 히트 전체
        rows = (
            await session.execute(
                select(SignalHit)
                .where(SignalHit.hit_at >= window_start)
                .where(SignalHit.action == "buy")   # Phase 3 는 매수만
                .order_by(SignalHit.hit_at.asc())
            )
        ).scalars().all()

        # 티커별 그룹핑
        by_ticker: dict[str, list[SignalHit]] = {}
        for r in rows:
            by_ticker.setdefault(r.ticker, []).append(r)

        # 최근 24h 내 이미 승격된 티커 조회 (중복 방지)
        recent_super = {
            row.ticker
            for row in (
                await session.execute(
                    select(SuperSignal).where(SuperSignal.promoted_at >= cooldown_start)
                )
            ).scalars().all()
        }

        for ticker, hits in by_ticker.items():
            if ticker in recent_super:
                continue
            sources = {h.source for h in hits}
            if len(sources) < PROMOTE_MIN_SOURCES:
                continue
            intensity = compute_intensity(
                [{"source": h.source, "score": h.score} for h in hits]
            )
            if intensity < PROMOTE_MIN_INTENSITY:
                continue

            entry = SuperSignal(
                ticker=ticker,
                intensity=intensity,
                sources="+".join(sorted(sources)),
                hit_count=len(hits),
                first_hit_at=hits[0].hit_at,
                last_hit_at=hits[-1].hit_at,
                metadata_json=json.dumps(
                    {
                        "hits": [
                            {
                                "source": h.source,
                                "signal_id": h.signal_id,
                                "score": h.score,
                                "at": h.hit_at.isoformat() if h.hit_at else None,
                            }
                            for h in hits
                        ],
                        "weights": {s: source_weight(s) for s in sources},
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
            session.add(entry)
            promoted.append(entry)
            logger.info(
                "🌟 Super Signal 승격 · %s · intensity=%.2f · sources=%s · hits=%d",
                ticker, intensity, entry.sources, len(hits),
            )

    return promoted


async def get_recent_super_signals(limit: int = 30) -> list[SuperSignal]:
    async with get_session() as session:
        rows = (
            await session.execute(
                select(SuperSignal)
                .order_by(SuperSignal.promoted_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)
