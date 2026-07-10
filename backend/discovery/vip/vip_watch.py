"""VIP 오케스트레이터 (VIP-agnostic — 종목은 config 에서 로드).

Entry:
    await run_price_tick()     — 폴링·이벤트 판정·알림 (30s 정규장 / 300s AH)
    await run_activist_tick()  — SEC EDGAR 폴링·활동주주 필링 감지·알림 (5분)
    await get_status()         — API `/vip/status` 스냅샷
    await get_config()         — API `/vip/config` GET
    await patch_config(patch)  — API `/vip/config` PATCH (activist override)

시장 판별: 미 정규장(NYSE/NASDAQ 09:30~16:00 ET) → 짧은 폴링, 그 외 → 긴 폴링.
서머타임 스위칭은 approximation 으로 EDT/EST 두 창을 커버 (오차 ≤1h).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from backend.services.notifier import TelegramNotifier

from . import activist_tracker
from . import config as cfg_mod
from . import exchange_client
from . import notifier as vip_notifier
from . import overrides as vip_overrides
from . import position, price_client, state as state_mod

logger = logging.getLogger(__name__)

_EDT_OPEN_UTC = 13 * 60 + 30
_EDT_CLOSE_UTC = 20 * 60
_EST_OPEN_UTC = 14 * 60 + 30
_EST_CLOSE_UTC = 21 * 60


def is_us_regular_hours(now_utc: datetime | None = None) -> bool:
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.weekday() >= 5:
        return False
    minutes = now_utc.hour * 60 + now_utc.minute
    return (
        (_EDT_OPEN_UTC <= minutes < _EDT_CLOSE_UTC)
        or (_EST_OPEN_UTC <= minutes < _EST_CLOSE_UTC)
    )


async def run_price_tick(
    notifier: TelegramNotifier | None = None,
) -> Dict[str, Any]:
    """가격 폴링 → 이벤트 판정 → cooldown 통과 시 알림."""
    cfg = cfg_mod.load()
    if not cfg.is_active:
        return {"skipped": True, "reason": "not_active"}

    quote = await price_client.fetch_us_quote(cfg.ticker)
    if quote is None:
        return {"skipped": True, "reason": "quote_fetch_failed"}

    state = state_mod.VipState.load(cfg.ticker)
    events = position.evaluate(quote.close_price, cfg, state)

    # VIP 이벤트 → Execution 시그널 매핑 (v2 트랙 C · Phase 1)
    _VIP_SELL_STRENGTH = {
        "TP1": 60,               # 1차 부분 익절
        "TP2": 80,               # 2차 익절
        "STOP_APPROACH": 100,    # 손절 접근 · 최우선
        "TRAIL_GIVEBACK": 90,    # trailing 되돌림
    }

    sent: list[str] = []
    if events:
        notifier = notifier or TelegramNotifier()
        for evt in events:
            if not state.can_send(evt.name):
                continue
            ok = await vip_notifier.send_position_event(notifier, evt, cfg)
            if ok:
                state.mark_sent(evt.name)
                sent.append(evt.name)

                # ─── Execution Layer 라우팅 ───
                # TP/STOP 이벤트만 매도 시그널 · TRAIL_ARMED/ACTIVIST 는 정보성
                strength = _VIP_SELL_STRENGTH.get(evt.name)
                if strength is not None:
                    try:
                        from backend.execution.signal_router import (
                            SignalEvent,
                            get_signal_router,
                        )
                        router = get_signal_router()
                        if router:
                            await router.route(
                                SignalEvent(
                                    ticker=cfg.ticker,
                                    action="sell",
                                    strength=strength,
                                    source="vip",
                                    signal_id=f"vip-{cfg.tag}-{evt.name}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
                                    metadata={
                                        "event": evt.name,
                                        "current_price": evt.current_price,
                                        "pnl": evt.pnl,
                                        "vip_tag": cfg.tag,
                                    },
                                )
                            )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[vip] router 실패 — %s", exc)

    state.save()
    pnl = position.compute_pnl(quote.close_price, cfg.avg_price)
    return {
        "skipped": False,
        "ticker": cfg.ticker,
        "close_price": quote.close_price,
        "pnl": pnl,
        "market_status": quote.market_status,
        "over_market_ratio": quote.over_market_ratio,
        "events_evaluated": len(events),
        "sent": sent,
    }


async def run_activist_tick(
    notifier: TelegramNotifier | None = None,
) -> Dict[str, Any]:
    """SEC EDGAR 폴링 → activist 신규 대상 필링 감지 → 알림."""
    cfg = cfg_mod.load()
    if not cfg.is_active:
        return {"skipped": True, "reason": "not_active"}
    if not cfg.is_activist_active:
        return {"skipped": True, "reason": "activist_not_configured"}

    filings = await activist_tracker.fetch_recent(cfg.activist_cik, cfg.sec_ua)
    if not filings:
        return {"skipped": True, "reason": "no_filings"}

    latest = activist_tracker.latest_target_filing(filings, cfg.activist_keywords)
    if latest is None:
        return {"skipped": True, "reason": "no_target_match"}

    state = state_mod.VipState.load(cfg.ticker)
    if state.activist_last_accession == latest.accession:
        return {
            "skipped": True,
            "reason": "duplicate_accession",
            "accession": latest.accession,
        }

    notifier = notifier or TelegramNotifier()
    ok = await vip_notifier.send_activist_filing(notifier, latest, cfg)
    if ok:
        state.activist_last_accession = latest.accession
        state.save()

    return {
        "skipped": False,
        "sent": ok,
        "accession": latest.accession,
        "form": latest.form,
        "filing_date": latest.filing_date,
    }


async def get_status() -> Dict[str, Any]:
    """대시보드/API 스냅샷."""
    cfg = cfg_mod.load()
    state = state_mod.VipState.load(cfg.ticker)

    snap: Dict[str, Any] = {
        "active": cfg.is_active,
        "activist_active": cfg.is_activist_active,
        "ticker": cfg.ticker,
        "company_name": cfg.company_name,
        "tag": cfg.tag,
        "avg_price": cfg.avg_price,
        "qty": cfg.qty,
        "thresholds": {
            "tp1_pct": cfg.tp1_pct,
            "tp2_pct": cfg.tp2_pct,
            "stop_pct": cfg.stop_pct,
            "trail_arm_pct": cfg.trail_arm_pct,
            "trail_giveback_pct": cfg.trail_giveback_pct,
        },
        "trail_armed_at": state.trail_armed_at,
        "trail_peak_pnl": state.trail_peak_pnl,
        "sent_events": state.sent,
        "activist_last_accession": state.activist_last_accession,
        "is_us_regular_hours": is_us_regular_hours(),
    }
    if cfg.is_active:
        quote = await price_client.fetch_us_quote(cfg.ticker)
        if quote is not None:
            snap["quote"] = {
                "close_price": quote.close_price,
                "fluctuations_ratio": quote.fluctuations_ratio,
                "compare_to_prev_close": quote.compare_to_prev_close,
                "market_status": quote.market_status,
                "over_market_ratio": quote.over_market_ratio,
                "local_traded_at": quote.local_traded_at,
                "stock_name_kor": quote.stock_name_kor,
                "stock_name_eng": quote.stock_name_eng,
                "item_logo_url": quote.item_logo_url,
                "exchange_name": quote.exchange_name,
            }
            if quote.market_stats is not None:
                snap["market_stats"] = {
                    k: v for k, v in quote.market_stats.__dict__.items() if v is not None
                }
            snap["pnl"] = position.compute_pnl(quote.close_price, cfg.avg_price)

    # 환율 (USD→KRW · 하루 1회 캐시)
    fx = await exchange_client.fetch_usd_krw()
    if fx is not None:
        snap["usd_krw"] = {
            "rate": fx.rate,
            "fluctuations_ratio": fx.fluctuations_ratio,
            "source": fx.source,
            "fetched_at": fx.fetched_at,
        }

    # activist 상세
    snap["activist"] = {
        "enabled": cfg.activist_enabled,
        "cik": cfg.activist_cik,
        "name": cfg.activist_name,
        "keywords": cfg.activist_keywords,
    }
    if cfg.is_activist_active:
        # activist-radar 수준 정보 재활용 (URL·힌트·SC 13D 정형 파싱)
        from backend.discovery.activist import hints as activist_hints
        from backend.discovery.activist import sec_filing_details

        filings = await activist_tracker.fetch_recent(cfg.activist_cik, cfg.sec_ua)
        latest = activist_tracker.latest_target_filing(filings, cfg.activist_keywords)

        # activist 자체 EDGAR 필링 검색 링크
        snap["activist"]["filer_search_url"] = activist_hints.sec_filer_search_url(cfg.activist_cik)

        if latest is not None:
            # SC 13D primary_doc.xml 파싱 (지분율·이슈어·수정차수 등)
            details = None
            if any(f in latest.form for f in ("13D", "13G", "SCHEDULE 13")):
                details = await sec_filing_details.fetch_and_parse(
                    cfg.activist_cik, latest.accession, cfg.sec_ua,
                )
            snap["activist"]["latest_target"] = {
                "accession": latest.accession,
                "form": latest.form,
                "form_hint": activist_hints.form_hint(latest.form),
                "filing_date": latest.filing_date,
                "primary_desc": latest.primary_desc,
                "primary_doc": latest.primary_doc,
                "filing_detail_url": activist_hints.sec_filing_detail_url(cfg.activist_cik, latest.accession),
                "details": {
                    "issuer_name": details.issuer_name if details else "",
                    "issuer_cik": details.issuer_cik if details else "",
                    "issuer_cusip": details.issuer_cusip if details else "",
                    "securities_class_title": details.securities_class_title if details else "",
                    "percent_of_class": details.percent_of_class if details else None,
                    "aggregate_amount_owned": details.aggregate_amount_owned if details else None,
                    "amendment_no": details.amendment_no if details else None,
                    "date_of_event": details.date_of_event if details else "",
                    "transaction_purpose": details.transaction_purpose if details else "",
                    "reporting_persons_count": details.reporting_persons_count if details else 0,
                } if details else {},
            }
        else:
            snap["activist"]["latest_target"] = None

        snap["activist"]["recent_forms"] = [
            {
                "form": f.form,
                "form_hint": activist_hints.form_hint(f.form),
                "date": f.filing_date,
                "accession": f.accession,
                "desc": f.primary_desc,
                "filing_detail_url": activist_hints.sec_filing_detail_url(cfg.activist_cik, f.accession),
            }
            for f in filings[:10]
        ]
    return snap


def get_config() -> Dict[str, Any]:
    """현재 config (env + overrides 반영) 반환. UI 편집 폼용."""
    cfg = cfg_mod.load()
    overrides_current = vip_overrides.load()
    return {
        "ticker": cfg.ticker,
        "company_name": cfg.company_name,
        "tag": cfg.tag,
        "activist": {
            "enabled": cfg.activist_enabled,
            "cik": cfg.activist_cik,
            "name": cfg.activist_name,
            "keywords": cfg.activist_keywords,
        },
        "overrides": overrides_current,
    }


def patch_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    """UI/API 편집 → JSON override 반영. 저장된 overrides + 재로드 config 반환."""
    activist = patch.get("activist") or {}
    to_save: Dict[str, Any] = {}
    if "enabled" in activist:
        to_save["activist_enabled"] = activist["enabled"]
    if "cik" in activist:
        to_save["activist_cik"] = activist["cik"]
    if "name" in activist:
        to_save["activist_name"] = activist["name"]
    if "keywords" in activist:
        to_save["activist_keywords"] = activist["keywords"]

    saved = vip_overrides.save(to_save) if to_save else vip_overrides.load()
    return {"overrides": saved, "config": get_config()}
