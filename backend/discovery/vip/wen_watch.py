"""WEN VIP 오케스트레이터.

Entry:
    await run_price_tick()  — 1회 폴링·판정·알림 (스케줄러 30s / 300s job)
    await run_trian_tick()  — 1회 SEC EDGAR 폴링·감지·알림 (스케줄러 5분 job)
    await get_status()      — API /vip/wen/status 용 스냅샷

시장 판별: 정규장(NYSE/NASDAQ 09:30~16:00 ET = KST 23:30~06:00 익일) 이면 폴링 짧게,
그 외(마감·주말) 는 길게. 판별 실패 시 안전하게 짧은 간격(정규장) 로 간주.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from backend.services.notifier import TelegramNotifier

from . import config as cfg_mod
from . import notifier as vip_notifier
from . import position, price_client, state as state_mod, trian_tracker

logger = logging.getLogger(__name__)

# ─── 정규장 시간대 판별 ───────────────────────────────
# 미국 동부 09:30~16:00. 서머타임 스위칭은 approximation 으로 UTC 13:30~21:00 (EDT)
# 또는 14:30~22:00 (EST) 커버. 오차는 <=1h — 폴링 간격 30s ↔ 300s 전환 목적이라 허용.

_EDT_OPEN_UTC = 13 * 60 + 30   # 13:30 UTC
_EDT_CLOSE_UTC = 20 * 60       # 20:00 UTC
_EST_OPEN_UTC = 14 * 60 + 30   # 14:30 UTC
_EST_CLOSE_UTC = 21 * 60       # 21:00 UTC


def is_us_regular_hours(now_utc: datetime | None = None) -> bool:
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.weekday() >= 5:  # 토(5)·일(6) 은 항상 폐장
        return False
    minutes = now_utc.hour * 60 + now_utc.minute
    return (
        (_EDT_OPEN_UTC <= minutes < _EDT_CLOSE_UTC)
        or (_EST_OPEN_UTC <= minutes < _EST_CLOSE_UTC)
    )


async def run_price_tick(
    notifier: TelegramNotifier | None = None,
) -> Dict[str, Any]:
    """가격 폴링 → 이벤트 판정 → cooldown 통과 시 알림.

    Returns: {"skipped": bool, "pnl": float, "events_evaluated": int, "sent": [names]}
    """
    cfg = cfg_mod.load()
    if not cfg.is_active:
        return {"skipped": True, "reason": "not_active"}

    quote = await price_client.fetch_us_quote(cfg.ticker)
    if quote is None:
        return {"skipped": True, "reason": "quote_fetch_failed"}

    state = state_mod.VipState.load()
    events = position.evaluate(quote.close_price, cfg, state)

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


async def run_trian_tick(
    notifier: TelegramNotifier | None = None,
) -> Dict[str, Any]:
    """SEC EDGAR 폴링 → Trian 신규 WEN 관련 필링 감지 → 알림."""
    cfg = cfg_mod.load()
    if not cfg.is_active:
        return {"skipped": True, "reason": "not_active"}

    filings = await trian_tracker.fetch_recent(cfg.trian_cik, cfg.sec_ua)
    if not filings:
        return {"skipped": True, "reason": "no_filings"}

    latest = trian_tracker.latest_wen_filing(filings)
    if latest is None:
        return {"skipped": True, "reason": "no_wen_match"}

    state = state_mod.VipState.load()
    if state.trian_last_accession == latest.accession:
        return {
            "skipped": True,
            "reason": "duplicate_accession",
            "accession": latest.accession,
        }

    notifier = notifier or TelegramNotifier()
    ok = await vip_notifier.send_trian_filing(notifier, latest)
    if ok:
        state.trian_last_accession = latest.accession
        state.save()

    return {
        "skipped": False,
        "sent": ok,
        "accession": latest.accession,
        "form": latest.form,
        "filing_date": latest.filing_date,
    }


async def get_status() -> Dict[str, Any]:
    """대시보드/API 스냅샷. 활성 여부·현재가·P&L·최근 이벤트·Trian 최신 필링."""
    cfg = cfg_mod.load()
    state = state_mod.VipState.load()

    snapshot: Dict[str, Any] = {
        "active": cfg.is_active,
        "ticker": cfg.ticker,
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
        "trian_last_accession": state.trian_last_accession,
        "is_us_regular_hours": is_us_regular_hours(),
    }
    if cfg.is_active:
        quote = await price_client.fetch_us_quote(cfg.ticker)
        if quote is not None:
            snapshot["quote"] = {
                "close_price": quote.close_price,
                "fluctuations_ratio": quote.fluctuations_ratio,
                "market_status": quote.market_status,
                "over_market_ratio": quote.over_market_ratio,
                "local_traded_at": quote.local_traded_at,
            }
            snapshot["pnl"] = position.compute_pnl(quote.close_price, cfg.avg_price)
    return snapshot
