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
from . import subject_resolver
from .dart_poller import KrActivistDisclosure, poll_new_disclosures
from .dart_d002_poller import KrInsiderDisclosure, poll_new_insider_reports
from .sec_poller import poll_new_filings
from .state import ActivistEvent, ActivistState
from .universe import Activist, all_including_disabled, load as load_universe
from .us_form4_poller import Form4Filing, poll_new_form4

_INSIDER_WATCH_DAYS = 90  # activism 진입 후 이 기간 임원 매매 감시

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

        # Phase F · subject company resolve (target_cik/ticker 자동 저장)
        subject = await subject_resolver.resolve(nf.filing.primary_desc or "", cfg.sec_ua)
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
            target_ticker=subject.ticker if subject else None,
            target_cik=subject.cik if subject else None,
            score=score,
            intensity_label=label,
            wolf_pack=wolf_pack,
            detected_at=now,
        )

        state.mark_seen(nf.activist.key, nf.filing.accession)
        state.add_event(evt)

        # 알림: REGIME_CHANGE / CRITICAL / STRONG 발송
        if label in ("REGIME_CHANGE", "CRITICAL", "STRONG"):
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
    """한국 DART 대량보유공시 폴러 (Phase B).

    첫 tick backfill 방어: filer_last_seen 에 KR filer 없으면 baseline 모드.
    보유목적 근사: report_nm "일반/변동" → MANAGEMENT (강) / "약식" → PASSIVE (약).
    """
    universe = [a for a in load_universe() if a.country == "KR"]
    if not universe:
        return {"skipped": True, "reason": "empty_kr_universe"}

    state = ActivistState.load()
    # KR baseline 판정: KR filer 중 하나라도 last_seen 있으면 안 baseline
    kr_keys = {a.key for a in universe}
    kr_first_run = not any(k in state.filer_last_seen for k in kr_keys)

    matched = await poll_new_disclosures(universe, state.has_seen)
    if not matched:
        return {"skipped": False, "detected": 0, "backfill": kr_first_run}

    if kr_first_run:
        for m in matched:
            state.mark_seen(m.activist.key, m.disclosure.rcept_no)
        state.save()
        return {
            "skipped": False,
            "detected": len(matched),
            "backfill": True,
            "sent": 0,
            "reason": "kr_first_run_baseline",
        }

    notifier = notifier or TelegramNotifier()
    sent_count = 0
    events_created: List[Dict[str, Any]] = []
    now = time.time()

    for m in matched:
        form_key = f"KR_D001_{m.purpose}"   # scoring 에서 사용
        # 강도 스코어링 (스코어링 함수는 form 문자열 하나만 받으므로 form_key 로)
        prior_forms = [
            e.form for e in state.events
            if e.filer_key == m.activist.key
            and (m.disclosure.corp_name or "").upper() in (e.target_desc or "").upper()
        ]
        score, label, wolf_pack = scoring.score_event(
            m.activist,
            form_key,
            m.disclosure.corp_name or m.disclosure.report_nm,
            state,
            prior_forms_by_this_filer_on_target=prior_forms,
        )

        evt = ActivistEvent(
            id=f"kr:{m.activist.key}:{m.disclosure.rcept_no}",
            country="KR",
            filer_key=m.activist.key,
            filer_name=m.activist.name,
            form=f"대량보유 ({m.purpose})",
            accession=m.disclosure.rcept_no,
            filing_date=(m.disclosure.rcept_dt[:4] + "-" + m.disclosure.rcept_dt[4:6] + "-" + m.disclosure.rcept_dt[6:8]) if len(m.disclosure.rcept_dt) == 8 else m.disclosure.rcept_dt,
            target_desc=f"{m.disclosure.corp_name} — {m.disclosure.report_nm}",
            target_ticker=m.disclosure.stock_code,
            score=score,
            intensity_label=label,
            wolf_pack=wolf_pack,
            detected_at=now,
        )
        state.mark_seen(m.activist.key, m.disclosure.rcept_no)
        state.add_event(evt)

        if label in ("REGIME_CHANGE", "CRITICAL", "STRONG"):
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
            "target_ticker": m.disclosure.stock_code,
        })

    # ── Phase E · KR insider watchlist 통합 (D002 임원 매매) ──
    insider_result = await _process_kr_insider(state, notifier)
    for k, v in insider_result.items():
        if k == "events":
            events_created.extend(v)
        elif k in ("detected", "sent"):
            # merge counts (KR 폴러와 insider 폴러 합산)
            pass

    state.save()
    return {
        "skipped": False,
        "detected": len(matched),
        "sent": sent_count,
        "insider_detected": insider_result.get("detected", 0),
        "insider_sent": insider_result.get("sent", 0),
        "events": events_created,
    }


async def run_us_form4_tick(
    notifier: TelegramNotifier | None = None,
) -> Dict[str, Any]:
    """Phase F · US Insider Watchlist Form 4 폴러 (별 job).

    최근 90일 US activism 진입 회사의 CIK 리스트 유지 → 각 회사 Form 4 신규 감지.
    parse_xml=True 로 방향(매수/매도) 자동 파싱.
    """
    cfg = vip_config.load()
    state = ActivistState.load()

    watchlist = state.us_insider_watchlist(time.time() - _INSIDER_WATCH_DAYS * 86400)
    if not watchlist:
        return {"skipped": True, "reason": "empty_watchlist"}

    # 첫 tick baseline: watchlist 어떤 회사도 seen 이력 없으면 baseline
    first_run = not any(
        state.filer_last_seen.get(f"form4_us:{w['cik']}") for w in watchlist
    )

    # Form 4 polling · dedup key 는 filer_last_seen 에 "form4_us:{cik}" 로 저장
    def _is_seen(cik: str, accession: str) -> bool:
        return state.has_seen(f"form4_us:{cik}", accession)

    filings = await poll_new_form4(
        watchlist, cfg.sec_ua, _is_seen, parse_xml=(not first_run),
    )
    if not filings:
        return {"skipped": False, "detected": 0, "watchlist_size": len(watchlist), "backfill": first_run}

    if first_run:
        for f in filings:
            state.mark_seen(f"form4_us:{f.subject_cik}", f.accession)
        state.save()
        return {
            "skipped": False,
            "detected": len(filings),
            "watchlist_size": len(watchlist),
            "backfill": True,
            "sent": 0,
            "reason": "form4_baseline",
        }

    notifier = notifier or TelegramNotifier()
    sent = 0
    events: List[Dict[str, Any]] = []
    now = time.time()

    for f in filings:
        # 방향에 따라 form 표기
        form_label = f"Form 4 ({f.direction})"
        # 스코어링: 매수(A)=STRONG 75, 매도(D)=WATCH 45, 그 외=WATCH 50
        if f.direction == "A":
            score, label = 75, "INSIDER"
        elif f.direction == "D":
            score, label = 45, "WATCH"
        else:
            score, label = 50, "INSIDER"

        evt = ActivistEvent(
            id=f"form4_us:{f.subject_cik}:{f.accession}",
            country="US",
            filer_key=f"form4_us:{f.subject_ticker}",
            filer_name=f"임원·주주 ({f.reporter_name or f.subject_ticker})",
            form=form_label,
            accession=f.accession,
            filing_date=f.filing_date,
            target_desc=f"{f.subject_ticker} · {f.subject_name}"
            + (f" · ${f.total_value_usd:,.0f}" if f.total_value_usd else ""),
            target_ticker=f.subject_ticker,
            target_cik=f.subject_cik,
            score=score,
            intensity_label=label,
            wolf_pack=[],
            detected_at=now,
            event_type="INSIDER",
        )
        state.mark_seen(f"form4_us:{f.subject_cik}", f.accession)
        state.add_event(evt)

        if label in ("INSIDER", "STRONG", "CRITICAL", "REGIME_CHANGE"):
            ok = await activist_notifier.send_event(notifier, evt)
            if ok:
                sent += 1
        events.append({
            "id": evt.id,
            "form": form_label,
            "target_ticker": f.subject_ticker,
            "direction": f.direction,
            "reporter": f.reporter_name,
            "value": f.total_value_usd,
            "score": score,
            "label": label,
        })

    state.save()
    return {
        "skipped": False,
        "detected": len(filings),
        "sent": sent,
        "watchlist_size": len(watchlist),
        "events": events,
    }


async def _process_kr_insider(
    state: ActivistState,
    notifier: TelegramNotifier,
) -> Dict[str, Any]:
    """Phase E: KR insider watchlist D002 폴링 → INSIDER 이벤트 생성.

    watchlist 자동 유지: 최근 90일 KR ACTIVIST 이벤트에서 stock_code 추출.
    """
    since = time.time() - (_INSIDER_WATCH_DAYS * 86400)
    watchlist = state.kr_insider_watchlist(since)
    if not watchlist:
        return {"detected": 0, "sent": 0, "events": [], "reason": "empty_watchlist"}

    matched = await poll_new_insider_reports(watchlist, state.has_seen)
    if not matched:
        return {"detected": 0, "sent": 0, "events": [], "watchlist_size": len(watchlist)}

    sent = 0
    events: List[Dict[str, Any]] = []
    now = time.time()
    for m in matched:
        d = m.disclosure
        filing_date = (
            f"{d.rcept_dt[:4]}-{d.rcept_dt[4:6]}-{d.rcept_dt[6:8]}"
            if len(d.rcept_dt) == 8 else d.rcept_dt
        )
        evt = ActivistEvent(
            id=f"insider_kr:{d.stock_code}:{d.rcept_no}",
            country="KR",
            filer_key="insider_kr",
            filer_name=f"임원·주요주주 ({d.corp_name})",
            form=f"D002 ({m.direction})",
            accession=d.rcept_no,
            filing_date=filing_date,
            target_desc=f"{d.corp_name} — {d.report_nm}",
            target_ticker=d.stock_code,
            score=70,   # INSIDER 는 고정 STRONG 급
            intensity_label="INSIDER",
            wolf_pack=[],
            detected_at=now,
            event_type="INSIDER",
        )
        state.mark_seen("insider_kr", d.rcept_no)
        state.add_event(evt)

        ok = await activist_notifier.send_event(notifier, evt)
        if ok:
            sent += 1
        events.append({
            "id": evt.id,
            "form": evt.form,
            "target_ticker": d.stock_code,
            "target_desc": evt.target_desc,
            "score": evt.score,
            "label": evt.intensity_label,
        })

    return {
        "detected": len(matched),
        "sent": sent,
        "events": events,
        "watchlist_size": len(watchlist),
    }


async def get_status() -> Dict[str, Any]:
    """API /activist/status 스냅샷 — 최근 이벤트 강도 순 정렬."""
    state = ActivistState.load()
    recent = state.recent_events(50)
    by_label: Dict[str, List[Dict[str, Any]]] = {
        "REGIME_CHANGE": [], "CRITICAL": [], "STRONG": [],
        "INSIDER": [], "WATCH": [], "NOTE": [],
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
            "event_type": e.event_type,
        })
    universe = load_universe()
    from time import time as _now
    since = _now() - _INSIDER_WATCH_DAYS * 86400
    kr_watchlist = state.kr_insider_watchlist(since)
    us_watchlist = state.us_insider_watchlist(since)
    return {
        "universe_size": len(universe),
        "universe_us": sum(1 for a in universe if a.country == "US"),
        "universe_kr": sum(1 for a in universe if a.country == "KR"),
        "events_total": len(state.events),
        "insider_watchlist_kr": kr_watchlist,
        "insider_watchlist_us": us_watchlist,
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
