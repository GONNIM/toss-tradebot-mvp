"""Catalyst event ingest → meme_catalyst_event 적재 + 점수 산출 (Phase 3-B).

데이터 소스:
- DART (한국): 매시간 fetch 주요사항(B)/발행(C)/지분(D)/거래소(I) 공시
- (KRX VI, FINRA halt — Phase 4)

종목별 24h 윈도우 카운트 → catalyst_score:
  3+ events → 1.0 (확실한 catalyst)
  2 events  → 0.7
  1 event   → 0.4
  0         → None (시그널 부재)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import desc, func, select

from backend.discovery.data_sources.dart import (
    fetch_recent_disclosures,
    is_configured,
)
from backend.services.db import get_session
from backend.services.models import MemeCatalystEvent

logger = logging.getLogger(__name__)


# DART 공시 유형 — meme catalyst 가치
_DART_TYPES = ("B", "C", "D", "I")


async def build_dart_catalyst() -> dict:
    """DART 최근 1일 공시 4유형 fetch → MemeCatalystEvent UPSERT."""
    stats = {"fetched": 0, "inserted": 0, "skipped_existing": 0, "errors": 0}

    if not is_configured():
        logger.warning("[dart_catalyst] DART_API_KEY 미설정 — skip")
        return stats

    all_d = []
    for ty in _DART_TYPES:
        try:
            rows = await fetch_recent_disclosures(pblntf_ty=ty, only_listed=True)
            all_d.extend(rows)
        except Exception as e:
            logger.warning(f"[dart_catalyst] type={ty} failed: {e}")
            stats["errors"] += 1
    stats["fetched"] = len(all_d)
    if not all_d:
        return stats

    rcept_nos = [d.rcept_no for d in all_d if d.rcept_no]
    async with get_session() as session:
        existing = set(
            (
                await session.execute(
                    select(MemeCatalystEvent.event_id).where(
                        MemeCatalystEvent.source == "dart",
                        MemeCatalystEvent.event_id.in_(rcept_nos),
                    )
                )
            ).scalars().all()
        )

        for d in all_d:
            if not d.rcept_no or d.rcept_no in existing:
                stats["skipped_existing"] += 1
                continue
            try:
                occurred = datetime.strptime(d.rcept_dt, "%Y%m%d")
            except (ValueError, TypeError):
                continue
            session.add(
                MemeCatalystEvent(
                    ticker=d.stock_code,
                    source="dart",
                    event_type=d.pblntf_ty,
                    event_label=d.report_nm,
                    occurred_at=occurred,
                    event_id=d.rcept_no,
                    payload=json.dumps(
                        {
                            "corp_code": d.corp_code,
                            "corp_name": d.corp_name,
                            "corp_cls": d.corp_cls,
                        },
                        ensure_ascii=False,
                    ),
                )
            )
            stats["inserted"] += 1
        await session.commit()

    logger.info(f"[dart_catalyst] done stats={stats}")
    return stats


async def get_catalyst_scores(
    tickers: list[str], hours: int = 24
) -> dict[str, float]:
    """24h 윈도우 ticker 별 catalyst event 카운트 → score [0, 1.0].

    Returns: {ticker: catalyst_score} — event 부재 시 dict 에 없음 (계산 시 None).
    """
    if not tickers:
        return {}
    cutoff = datetime.now() - timedelta(hours=hours)

    async with get_session() as session:
        rows = (
            await session.execute(
                select(
                    MemeCatalystEvent.ticker,
                    func.count(MemeCatalystEvent.id).label("cnt"),
                )
                .where(
                    MemeCatalystEvent.ticker.in_(tickers),
                    MemeCatalystEvent.occurred_at >= cutoff,
                )
                .group_by(MemeCatalystEvent.ticker)
            )
        ).all()

    out: dict[str, float] = {}
    for ticker, cnt in rows:
        if cnt >= 3:
            out[ticker] = 1.0
        elif cnt >= 2:
            out[ticker] = 0.7
        elif cnt >= 1:
            out[ticker] = 0.4
    return out
