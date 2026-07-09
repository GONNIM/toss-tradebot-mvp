"""Activist Radar 오케스트레이터.

Entry:
    await run_us_tick()   — 미국 SC 13D/G 폴러 1회 실행 · 신규 이벤트 → 알림
    await run_kr_tick()   — 한국 DART 대량보유 폴러 (Phase B 예정 · 지금은 no-op)
    await get_status()    — API /activist/status 스냅샷
    await get_universe()  — API /activist/universe (조회)
    await patch_universe(entry) — API PATCH · UI 편집
    await delete_universe(key)  — API DELETE
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from backend.discovery.vip import config as vip_config
from backend.services.notifier import TelegramNotifier

from . import notifier as activist_notifier
from . import overrides as universe_overrides
from . import scoring
from .sec_poller import poll_new_filings
from .state import ActivistEvent, ActivistState
from .universe import Activist, all_including_disabled, load as load_universe

logger = logging.getLogger(__name__)


def _make_event_id(country: str, filer_cik: str, accession: str) -> str:
    return f"{country.lower()}:{filer_cik}:{accession}"


async def run_us_tick(
    notifier: TelegramNotifier | None = None,
) -> Dict[str, Any]:
    """미국 SEC 폴링 tick — 신규 필링 감지 → 강도 계산 → 알림 (SC filing 자체가 사건).

    **첫 tick backfill 방어**: filer_last_seen 이 비어있으면 알림 없이 seen 만 마킹 →
    다음 tick 부터 진짜 신규 필링만 감지·알림.
    """
    cfg = vip_config.load()   # SEC_EDGAR_UA 재활용
    universe = [a for a in load_universe() if a.country == "US" and a.cik]
    if not universe:
        return {"skipped": True, "reason": "empty_universe"}

    state = ActivistState.load()
    first_run = not state.filer_last_seen

    new_filings = await poll_new_filings(universe, cfg.sec_ua, state.has_seen)
    if not new_filings:
        return {"skipped": False, "detected": 0, "backfill": first_run}

    if first_run:
        # baseline 만 설정 (알림·이벤트 저장 skip)
        for nf in new_filings:
            state.mark_seen(nf.activist.key, nf.filing.accession)
        state.save()
        return {
            "skipped": False,
            "detected": len(new_filings),
            "backfill": True,
            "sent": 0,
            "reason": "first_run_baseline",
        }

    notifier = notifier or TelegramNotifier()
    sent_count = 0
    events_created: List[Dict[str, Any]] = []
    stale_marked = 0

    now = time.time()

    for nf in new_filings:
        # 오래된 필링(7일 초과)은 seen 만 마킹 · 알림·이벤트 저장 skip
        if not nf.is_recent:
            state.mark_seen(nf.activist.key, nf.filing.accession)
            stale_marked += 1
            continue
        # 강도 스코어링 (같은 filer 가 이전에 낸 filing form 이력 참조)
        prior_forms = [
            e.form for e in state.events
            if e.filer_key == nf.activist.key
            and (nf.filing.primary_desc or "").upper() in (e.target_desc or "").upper()
        ]
        score, label, wolf_pack = scoring.score_event(
            nf.activist,
            nf.filing.form,
            nf.filing.primary_desc or "",
            state,
            prior_forms_by_this_filer_on_target=prior_forms,
        )

        evt = ActivistEvent(
            id=_make_event_id("US", nf.activist.cik or "", nf.filing.accession),
            country="US",
            filer_key=nf.activist.key,
            filer_name=nf.activist.name,
            form=nf.filing.form,
            accession=nf.filing.accession,
            filing_date=nf.filing.filing_date,
            target_desc=nf.filing.primary_desc or "",
            target_ticker=None,
            score=score,
            intensity_label=label,
            wolf_pack=wolf_pack,
            detected_at=now,
        )

        state.mark_seen(nf.activist.key, nf.filing.accession)
        state.add_event(evt)

        # 알림: STRONG 이상만
        if label in ("CRITICAL", "STRONG"):
            ok = await activist_notifier.send_event(notifier, evt)
            if ok:
                sent_count += 1

        events_created.append({
            "id": evt.id,
            "filer_key": evt.filer_key,
            "form": evt.form,
            "score": score,
            "label": label,
            "wolf_pack": wolf_pack,
        })

    state.save()

    return {
        "skipped": False,
        "detected": len(new_filings),
        "stale_marked": stale_marked,
        "recent_processed": len(events_created),
        "sent": sent_count,
        "events": events_created,
    }


async def run_kr_tick(
    notifier: TelegramNotifier | None = None,
) -> Dict[str, Any]:
    """한국 DART 폴러 — Phase B 예정."""
    return {"skipped": True, "reason": "phase_b_pending"}


async def get_status() -> Dict[str, Any]:
    """API /activist/status 스냅샷 — 최근 이벤트 강도 순 정렬."""
    state = ActivistState.load()
    recent = state.recent_events(50)
    by_label: Dict[str, List[Dict[str, Any]]] = {
        "CRITICAL": [], "STRONG": [], "WATCH": [], "NOTE": [],
    }
    for e in recent:
        by_label.setdefault(e.intensity_label, []).append({
            "id": e.id,
            "country": e.country,
            "filer_key": e.filer_key,
            "filer_name": e.filer_name,
            "form": e.form,
            "accession": e.accession,
            "filing_date": e.filing_date,
            "target_desc": e.target_desc,
            "target_ticker": e.target_ticker,
            "score": e.score,
            "wolf_pack": e.wolf_pack,
            "detected_at": e.detected_at,
        })
    universe = load_universe()
    return {
        "universe_size": len(universe),
        "universe_us": sum(1 for a in universe if a.country == "US"),
        "universe_kr": sum(1 for a in universe if a.country == "KR"),
        "events_total": len(state.events),
        "buckets": by_label,
    }


def get_universe() -> Dict[str, Any]:
    """UI 편집 폼용 · 활성/비활성 모두 반환."""
    return {
        "activists": [
            {
                "key": a.key,
                "name": a.name,
                "country": a.country,
                "tier": a.tier,
                "cik": a.cik,
                "corp_code": a.corp_code,
                "keywords": a.keywords,
                "enabled": a.enabled,
            }
            for a in all_including_disabled()
        ],
        "overrides": universe_overrides.load(),
    }


def patch_universe(entry: Dict[str, Any]) -> Dict[str, Any]:
    """UI PATCH — key 기준 upsert."""
    saved = universe_overrides.upsert_activist(entry)
    return {"overrides": saved, "universe": get_universe()}


def delete_universe(key: str) -> Dict[str, Any]:
    """UI DELETE — key 완전 제거."""
    saved = universe_overrides.delete_activist(key)
    return {"overrides": saved, "universe": get_universe()}
