"""Sniper Orchestrator · 5단계 loop · Sprint 1 T50.

APScheduler 잡:
  · scan_and_enter — 30초 주기 · 신호대기→감지→매수
  · manage_positions — 5초 주기 · trailing → 매도

계획서: docs/plans/sniper/00-sprint1-plan.md §1-1 5단계 loop
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from datetime import datetime, timezone

from backend.execution.audit import daily_realized_pnl
from backend.execution.brokers.paper_adapter import PaperAdapter
from backend.execution.brokers.toss_adapter import TossAdapter
from backend.execution.kill_switch import get_kill_switch
from backend.execution.models import BrokerKind
from backend.execution.order_manager import OrderManager

from .entry import execute_entry
from .exit import execute_exit
from .params import get_sniper_params
from .rankings import cleanup_old_snapshots, poll_rankings
from .scoring import is_candidate, score_ticker
from .trailing_stop import open_positions, poll_trailing
from .universe import list_universe

logger = logging.getLogger(__name__)


def _resolve_order_manager() -> OrderManager:
    """EXECUTION_BROKER env → 어댑터.

    paper (default) · toss.
    """
    broker = os.environ.get("EXECUTION_BROKER", "paper").lower()
    if broker == "toss":
        return TossAdapter()
    return PaperAdapter()


# ─── 스캔 (신호 대기 · 감지 · 매수) ──────────────────────
async def scan_and_enter(top_n: Optional[int] = None) -> dict:
    """유니버스 상위 종목 스캔 → candidate 감지 → 매수 실행.

    APScheduler 30초 주기 잡.
    """
    params = get_sniper_params()
    if not params.enabled:
        return {"skipped": True, "reason": "sniper_disabled"}

    n = top_n or 30
    universe = await list_universe(limit=n)
    if not universe:
        return {"skipped": True, "reason": "empty_universe"}

    order_manager = _resolve_order_manager()
    stats = {"scanned": 0, "candidates": 0, "entered": 0, "rejects": {}}

    for u in universe:
        stats["scanned"] += 1
        try:
            sig = await score_ticker(u["ticker"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("score_ticker 실패 · %s · %s", u["ticker"], exc)
            continue
        if sig is None:
            continue
        ok, reason = is_candidate(sig)
        if not ok:
            stats["rejects"][reason or "unknown"] = stats["rejects"].get(reason or "unknown", 0) + 1
            continue
        stats["candidates"] += 1

        result = await execute_entry(sig, order_manager)
        if result.ok:
            stats["entered"] += 1
        else:
            stats["rejects"][result.reason or "entry_failed"] = stats["rejects"].get(result.reason or "entry_failed", 0) + 1

    logger.info("scan_and_enter · %s", stats)
    return stats


# ─── Daily loss 자동 Kill Switch 트리거 ──────────────
async def check_daily_loss_and_trigger_ks() -> Optional[dict]:
    """일일 실현 손실이 params.daily_loss_limit_pct 초과 시 Kill Switch 자동 발동.

    Returns:
        {"triggered": True, "reason": ..., "realized_pct": ...} 발동 시 · None 아니면.
    """
    params = get_sniper_params()
    ks = get_kill_switch()
    if ks.is_active():
        return None  # 이미 발동됨

    broker = os.environ.get("EXECUTION_BROKER", "paper").lower()
    broker_kind = BrokerKind.TOSS if broker == "toss" else BrokerKind.PAPER
    since = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        realized = await daily_realized_pnl(broker_kind, since)
    except Exception as exc:  # noqa: BLE001
        logger.warning("daily_realized_pnl 조회 실패 · %s", exc)
        return None

    seed = params.seed_cap_krw or 1.0
    realized_pct = realized / seed
    if realized_pct <= params.daily_loss_limit_pct:
        reason = f"daily_loss_limit_reached({realized_pct*100:+.2f}%)"
        ks.activate(reason=reason, actor="auto:sniper")
        logger.critical("[sniper] daily loss limit · Kill Switch 자동 발동 · %s", reason)
        return {"triggered": True, "reason": reason, "realized_pct": realized_pct}
    return None


# ─── 관리 (Trailing · 매도 · daily loss 감시) ────────────
async def manage_positions() -> dict:
    """미청산 SniperSignal 순회 · trailing 판정 · 청산 실행.

    APScheduler 5초 주기 잡.
    """
    params = get_sniper_params()
    if not params.enabled:
        return {"skipped": True, "reason": "sniper_disabled"}

    # daily loss 감시 → 임계 도달 시 Kill Switch 자동 발동
    ks_trigger = await check_daily_loss_and_trigger_ks()

    ids = await open_positions()
    if not ids:
        return {"open_positions": 0, "checked": 0, "exited": 0, "ks_trigger": ks_trigger}

    order_manager = _resolve_order_manager()
    stats = {"open_positions": len(ids), "checked": 0, "exited": 0, "no_action": 0}

    for signal_id in ids:
        stats["checked"] += 1
        try:
            decision = await poll_trailing(signal_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("poll_trailing 실패 · signal=%d · %s", signal_id, exc)
            continue
        if decision is None:
            stats["no_action"] += 1
            continue
        if not decision.should_exit:
            stats["no_action"] += 1
            continue

        result = await execute_exit(signal_id, order_manager, decision.reason or "unknown")
        if result.ok:
            stats["exited"] += 1

    logger.info("manage_positions · %s", stats)
    return stats


# ─── APScheduler 등록 헬퍼 ────────────────────────────
async def poll_rankings_job() -> dict:
    """rankings 폴링 잡 (10초 주기).

    sniper.enabled=False 여도 항상 실행 (rank_velocity 계산 원본 축적).
    유니버스가 있어야 유효 · 없으면 no-op.
    """
    try:
        return await poll_rankings()
    except Exception as exc:  # noqa: BLE001
        logger.warning("poll_rankings_job 실패 · %s", exc)
        return {"error": str(exc)}


async def cleanup_snapshots_job() -> dict:
    """rankings 스냅샷 청소 잡 (1시간 주기).

    6시간 이전 스냅샷 자동 삭제 (DB 크기 관리).
    """
    try:
        deleted = await cleanup_old_snapshots(keep_hours=6)
        return {"deleted": deleted}
    except Exception as exc:  # noqa: BLE001
        logger.warning("cleanup_snapshots_job 실패 · %s", exc)
        return {"error": str(exc)}


def register_sniper_jobs(scheduler) -> None:
    """main.py lifespan 에서 호출. 파라미터 store enabled=True 시 자동 실행."""
    params = get_sniper_params()
    scan_sec = 30
    manage_sec = max(3, params.poll_trailing_price_sec)
    rankings_sec = max(5, params.poll_rankings_sec)

    scheduler.add_job(
        scan_and_enter,
        "interval",
        seconds=scan_sec,
        id="sniper_scan",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        manage_positions,
        "interval",
        seconds=manage_sec,
        id="sniper_manage",
        max_instances=1,
        coalesce=True,
    )
    # rankings 폴러 · sniper.enabled 무관 · 상시 축적 (rank_velocity 원본)
    scheduler.add_job(
        poll_rankings_job,
        "interval",
        seconds=rankings_sec,
        id="sniper_rankings",
        max_instances=1,
        coalesce=True,
    )
    # 스냅샷 청소 · 1시간마다
    scheduler.add_job(
        cleanup_snapshots_job,
        "interval",
        hours=1,
        id="sniper_cleanup",
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "[sniper] jobs 등록 · scan=%ds · manage=%ds · rankings=%ds · cleanup=1h · sniper.enabled=%s",
        scan_sec, manage_sec, rankings_sec, params.enabled,
    )
