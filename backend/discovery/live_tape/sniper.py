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

from backend.execution.audit import daily_pnl_detail
from backend.execution.brokers.paper_adapter import PaperAdapter
from backend.execution.brokers.toss_adapter import TossAdapter
from backend.execution.kill_switch import get_kill_switch
from backend.execution.models import BrokerKind
from backend.execution.order_manager import OrderManager

from .entry import execute_entry
from .exit import execute_exit
from .params import get_sniper_params
from .rankings import cleanup_old_snapshots, poll_rankings, tickers_with_snapshots
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
    # rankings 매치 티커 우선 · 부족분은 유니버스 시총 상위로 보충
    universe_map = {u["ticker"]: u for u in await list_universe(limit=500)}
    if not universe_map:
        return {"skipped": True, "reason": "empty_universe"}
    ranked = await tickers_with_snapshots(window_sec=600)
    scan_tickers = [t for t in ranked if t in universe_map][:n]
    if len(scan_tickers) < n:
        extra = [t for t in universe_map if t not in scan_tickers][: n - len(scan_tickers)]
        scan_tickers.extend(extra)

    order_manager = _resolve_order_manager()
    stats = {"scanned": 0, "candidates": 0, "entered": 0, "rejects": {}, "ranked_pool": len(ranked)}

    for ticker in scan_tickers:
        stats["scanned"] += 1
        try:
            sig = await score_ticker(ticker)
        except Exception as exc:  # noqa: BLE001
            logger.warning("score_ticker 실패 · %s · %s", ticker, exc)
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
# 같은 원인 알림·로그는 하루 1회 (5초 잡 · 1025-02) · 메모리 집합 · 재시작하면 다시 1회
_daily_once: set[str] = set()


def _once_today(key: str) -> bool:
    """오늘 (한국 날짜) 처음 보는 key 면 True."""
    from zoneinfo import ZoneInfo
    today = datetime.now(tz=ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    k = f"{today}:{key}"
    if k in _daily_once:
        return False
    if len(_daily_once) > 5000:
        _daily_once.clear()
    _daily_once.add(k)
    return True


async def _alert_uncomputable(items: list[tuple[int, str]]) -> None:
    """하루 손익을 계산하지 못한 청산 알림 · signal id 마다 하루 1회."""
    fresh = [(sid, why) for sid, why in items if _once_today(f"uncomputable:{sid}")]
    if not fresh:
        return
    lines = " · ".join(f"#{sid} {why}" for sid, why in fresh[:10])
    logger.warning("[sniper] 하루 손익 계산 불가 %d건 · %s", len(fresh), lines)
    try:
        from backend.services.notifier import TelegramNotifier
        await TelegramNotifier().send_warning(
            "하루 손익 계산 불가",
            f"청산 {len(fresh)}건의 손익을 계산하지 못했습니다. 이 건은 손실 자동 정지 판단에서 빠집니다.\n{lines}",
            category="execution",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[sniper] 계산 불가 알림 실패 · %s", exc)


async def check_daily_loss_and_trigger_ks() -> Optional[dict]:
    """일일 실현 손실이 params.daily_loss_limit_pct 이하면 Kill Switch 자동 발동.

    손익 = 오늘 청산된 진입 기록의 (매도 − 매수 − 수수료) 합 (`daily_pnl_detail` · 1025-02).
    하루 경계 UTC 00:00 = 한국 09:00 (한국 정규장 기준).
    조회 오류 시 발동하지 않음 (5초 잡 오작동 방지) · ERROR 로그 하루 1회.

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
        detail = await daily_pnl_detail(broker_kind, since)
    except Exception as exc:  # noqa: BLE001
        if _once_today(f"pnl_error:{type(exc).__name__}"):
            logger.error("[sniper] 하루 손익 조회 실패 · Kill Switch 판단 건너뜀 · %s", exc)
        return None

    if detail.uncomputable:
        await _alert_uncomputable(detail.uncomputable)

    seed = params.seed_cap_krw or 1.0
    realized_pct = detail.realized_krw / seed
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
