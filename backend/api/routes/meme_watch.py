"""Meme Watch API 라우터 (Phase 1e).

엔드포인트:
  GET  /api/v1/meme-watch/top?limit=20  — 상위 N 종목 score
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from sqlalchemy import desc, select

from backend.api.schemas import (
    MemeScoreResponse,
    MemeSignalContributionResponse,
    MemeWatchTopResponse,
)
from backend.discovery.meme_watch.top import compute_top_memes
from backend.services.db import get_session
from backend.services.models import MemeSocialSignal

router = APIRouter()


async def _sources_status() -> dict[str, str]:
    """최근 12시간 내 각 소스가 적재된 row 가 있는지로 상태 판정."""
    from datetime import timedelta

    cutoff = datetime.now() - timedelta(hours=12)
    out: dict[str, str] = {}
    async with get_session() as session:
        for src in ["apewisdom", "stocktwits", "google_trends", "reddit"]:
            row = (
                await session.execute(
                    select(MemeSocialSignal.id)
                    .where(
                        MemeSocialSignal.source == src,
                        MemeSocialSignal.fetched_at >= cutoff,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            out[src] = "ok" if row is not None else "blocked"
    return out


@router.get("/top", response_model=MemeWatchTopResponse)
async def get_top_memes(
    limit: int = Query(20, ge=1, le=100),
    market: Optional[str] = Query(
        None, pattern="^(US|KRX)$", description="시장 필터: US / KRX / (없음=전체)"
    ),
):
    """apewisdom 상위 종목 × 시그널 join → Meme Score 상위 N. market 필터 지원."""
    # market 필터는 compute_top_memes 내부에서 처리 — 정확한 top N 산출
    results = await compute_top_memes(top_n=limit, market=market)
    sources = await _sources_status()

    items = []
    for r in results:
        score = r["score"]
        meta = r.get("meta")
        vol = r.get("volume")
        items.append(
            MemeScoreResponse(
                ticker=score.ticker,
                name=(meta.name if meta else None),
                market=(meta.market if meta else None),
                sector=(meta.sector if meta else None),
                market_cap=(meta.market_cap if meta else None),
                score=score.score,
                label=score.label,
                emoji=score.emoji,
                active_signals=score.active_signals,
                strongest_signal=score.strongest_signal,
                confidence_label=score.confidence_label,
                sample_warning=score.sample_warning,
                contributions=[
                    MemeSignalContributionResponse(
                        name=c.name,
                        label=c.label,
                        raw_value=c.raw_value,
                        raw_label=c.raw_label,
                        normalized=c.normalized,
                        weight=c.weight,
                        contribution=c.contribution,
                        detail=c.detail,
                    )
                    for c in score.contributions
                ],
                current_price=(vol.close if vol else None),
                return_1d_pct=(vol.return_1d_pct if vol else None),
            )
        )

    return MemeWatchTopResponse(
        items=items,
        total=len(items),
        computed_at=datetime.utcnow().isoformat() + "Z",
        sources_status=sources,
    )
