"""Meme Watch API 라우터 (Phase 1e).

엔드포인트:
  GET  /api/v1/meme-watch/top?limit=20  — 상위 N 종목 score
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import desc, select

from backend.api.schemas import (
    MemeIntensityResponse,
    MemeScoreHistoryPoint,
    MemeScoreHistoryResponse,
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
                intensity=(
                    MemeIntensityResponse(
                        intensity=r["intensity"].intensity,
                        label=r["intensity"].label,
                        emoji=r["intensity"].emoji,
                        return_1d=r["intensity"].return_1d,
                        return_5d=r["intensity"].return_5d,
                        acceleration=r["intensity"].acceleration,
                        volume_ratio=r["intensity"].volume_ratio,
                        score_delta_24h=r["intensity"].score_delta_24h,
                        time_in_blazing_7d=r["intensity"].time_in_blazing_7d,
                        mention_velocity_30m=r["intensity"].mention_velocity_30m,
                        sample_days=r["intensity"].sample_days,
                    )
                    if r.get("intensity")
                    else None
                ),
            )
        )

    return MemeWatchTopResponse(
        items=items,
        total=len(items),
        computed_at=datetime.utcnow().isoformat() + "Z",
        sources_status=sources,
    )


@router.get(
    "/tickers/{ticker}/history",
    response_model=MemeScoreHistoryResponse,
)
async def get_score_history(
    ticker: str,
    hours: int = Query(24, ge=1, le=168, description="조회 기간 (시간, 최대 7일)"),
):
    """종목별 Meme Score 시계열 (Phase 5)."""
    from datetime import timedelta

    from sqlalchemy import asc

    from backend.services.models import MemeScoreHistory

    cutoff = datetime.now() - timedelta(hours=hours)
    async with get_session() as session:
        rows = (
            await session.execute(
                select(MemeScoreHistory)
                .where(
                    MemeScoreHistory.ticker == ticker,
                    MemeScoreHistory.snapshot_at >= cutoff,
                )
                .order_by(asc(MemeScoreHistory.snapshot_at))
            )
        ).scalars().all()

    points = [
        MemeScoreHistoryPoint(
            snapshot_at=r.snapshot_at.isoformat(),
            score=r.score,
            label=r.label,
            active_signals=r.active_signals,
        )
        for r in rows
    ]
    return MemeScoreHistoryResponse(
        ticker=ticker,
        points=points,
        hours=hours,
    )


# ─────────────────────────────────────────────
# VIP 채널 (P-A · 종목 파라미터화 · 2026-07-08)
# ─────────────────────────────────────────────


@router.get("/vip/status")
async def get_vip_status():
    """VIP 감시 스냅샷 — 활성 여부·현재가·P&L·최근 이벤트·activist 최신 필링.

    감시 비활성(env VIP_ENABLED=false or VIP_AVG_PRICE=0) 시 quote·activist.latest
    필드 없이 thresholds·activist 설정만 반환.
    """
    from backend.discovery.vip.vip_watch import get_status

    return await get_status()


@router.get("/vip/config")
def get_vip_config():
    """편집 UI 용 — 현재 파라미터(ticker·company_name·tag·activist) + overrides 상태."""
    from backend.discovery.vip.vip_watch import get_config

    return get_config()


class _VipActivistPatch(BaseModel):
    enabled: Optional[bool] = None
    cik: Optional[str] = None
    name: Optional[str] = None
    keywords: Optional[list[str]] = None


class _VipConfigPatch(BaseModel):
    activist: Optional[_VipActivistPatch] = None


@router.patch("/vip/config")
def patch_vip_config(patch: _VipConfigPatch):
    """activist 설정 override — data/vip_overrides.json 에 저장. 재시작 없이 반영.

    허용 필드: activist.enabled / cik / name / keywords.
    빈 문자열·빈 리스트를 넘기면 해당 키 override 삭제(env 기본값 복귀).
    """
    from backend.discovery.vip.vip_watch import patch_config

    payload = patch.model_dump(exclude_none=True)
    return patch_config(payload)


# ─────────────────────────────────────────────
# Activist Radar (Phase A~C · 2026-07-09~)
# ─────────────────────────────────────────────


@router.get("/activist/status")
async def get_activist_status():
    """Activist Radar 최근 이벤트 스냅샷 · 강도 별 버킷."""
    from backend.discovery.activist.radar import get_status

    return await get_status()


@router.get("/activist/universe")
def get_activist_universe():
    """Universe 전체 · 활성/비활성 모두 · UI 편집 폼용."""
    from backend.discovery.activist.radar import get_universe

    return get_universe()


class _ActivistUpsert(BaseModel):
    key: str
    name: Optional[str] = None
    country: Optional[str] = None
    tier: Optional[int] = None
    cik: Optional[str] = None
    corp_code: Optional[str] = None
    keywords: Optional[list[str]] = None
    enabled: Optional[bool] = None


@router.patch("/activist/universe")
def patch_activist_universe(entry: _ActivistUpsert):
    """Universe upsert — key 기준. seed 항목은 override 되고 신규는 추가."""
    from backend.discovery.activist.radar import patch_universe

    return patch_universe(entry.model_dump(exclude_none=True))


@router.delete("/activist/universe/{key}")
def delete_activist_universe(key: str):
    """Universe 에서 완전 제거 (disabled_keys 등재)."""
    from backend.discovery.activist.radar import delete_universe

    return delete_universe(key)
