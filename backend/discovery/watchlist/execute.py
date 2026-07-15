"""Watchlist 개장 실행 · Sprint 2 Week 3 T64·T65·T66.

정체성 3원칙 실행 단계:
  · 마감 후 예측 결정 → Week 1·2 완료
  · 개장 전 최종 Watchlist → 08:30 KST finalize
  · 급등 전 매수 → 09:00~09:30 KST 이 모듈

로직:
  1. 활성창 (09:00~09:30 KST) 안에서만 실행
  2. 오늘 Watchlist 조회 (composite_score >= 임계값)
  3. 각 종목 현재가 vs 전일 종가 → 갭업 % 계산
  4. 갭업 min~max 사이 (상투 배제) → 진입 후보
  5. (옵션) rankings 매치 확인 (참고 지표 · 트리거 X)
  6. execute_entry 호출 (기존 Sprint 1 안전장치 재사용)

계획서: docs/plans/sniper/02-strategic-pivot-as-is-to-be.md §2-4 · 03-sprint2-week1-tasks.md Week 3
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.discovery.live_tape.entry import execute_entry
from backend.discovery.live_tape.params import get_sniper_params
from backend.discovery.live_tape.rankings import tickers_with_snapshots
from backend.discovery.live_tape.scoring import CandidateSignal
from backend.execution.brokers.paper_adapter import PaperAdapter
from backend.execution.brokers.toss_adapter import TossAdapter
from backend.execution.brokers.toss_client import get_toss_client
from backend.execution.order_manager import OrderManager

from .finalize import list_watchlist
from .store import next_trade_date

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class WatchlistExecutionCandidate:
    """Watchlist 진입 후보 · execute_entry 로 넘기기 전 중간 산출물."""
    ticker: str
    composite_score: float
    prev_close: float
    current_price: float
    gap_pct: float
    in_rankings: bool
    reject_reason: Optional[str] = None


# ─── 활성창 (09:00~09:30 KST) ─────────────────────
def _parse_kst_time(hhmm: str) -> Optional[dtime]:
    try:
        h, m = hhmm.split(":")
        return dtime(int(h), int(m))
    except (ValueError, AttributeError):
        return None


def _is_in_execute_window(params) -> bool:
    """09:00~09:30 KST 활성창 판정."""
    now_kst = datetime.now(tz=_KST)
    if now_kst.weekday() >= 5:
        return False
    start = _parse_kst_time(params.watchlist_execute_start_kst)
    end = _parse_kst_time(params.watchlist_execute_end_kst)
    if start is None or end is None:
        return False
    return start <= now_kst.time() < end


# ─── 가격 조회 ─────────────────────────────────
async def fetch_current_prices(tickers: list[str]) -> dict[str, float]:
    """TossClient · MARKET_DATA 그룹 · sync API 를 async wrapper 로.

    tests 는 이 함수를 monkeypatch.
    """
    if not tickers:
        return {}
    try:
        client = get_toss_client()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[watchlist.exec] TossClient 없음 · %s", exc)
        return {}

    def _sync_call(syms: list[str]) -> Any:
        return client.prices(syms)

    try:
        raw = await asyncio.to_thread(_sync_call, tickers)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[watchlist.exec] price fetch 실패 · %s", exc)
        return {}

    if not raw:
        return {}
    # 응답 형태 정합: [{symbol, price}, ...] 또는 {items: [...]}
    items = raw if isinstance(raw, list) else raw.get("items") or []
    result: dict[str, float] = {}
    for item in items:
        try:
            sym = item.get("symbol") or item.get("ticker")
            price = item.get("price") or item.get("last_price")
            if sym and price is not None:
                result[str(sym)] = float(price)
        except (TypeError, ValueError):
            continue
    return result


# ─── 진입 판정 ──────────────────────────────────
def compute_gap_pct(current: float, prev_close: float) -> Optional[float]:
    if prev_close is None or prev_close <= 0:
        return None
    return (current - prev_close) / prev_close


def _resolve_order_manager() -> OrderManager:
    """Sprint 1 sniper.py 와 동일 · EXECUTION_BROKER env → adapter."""
    import os
    broker = os.environ.get("EXECUTION_BROKER", "paper").lower()
    if broker == "toss":
        return TossAdapter()
    return PaperAdapter()


# ─── 스캔 · 진입 실행 ─────────────────────────
async def execute_watchlist_scan(force_window: bool = False) -> dict[str, Any]:
    """Watchlist 종목 스캔 → 갭업 진입.

    Args:
        force_window: True 면 활성창 무시 (수동 트리거·테스트용).

    Returns:
        {"skipped_reason"?, "trade_date", "watchlist_size", "candidates":[...],
         "entered": N, "rejects": {reason: count}}
    """
    params = get_sniper_params()
    if not params.watchlist_execute_enabled:
        return {"skipped_reason": "watchlist_execute_disabled"}

    if not force_window and not _is_in_execute_window(params):
        return {"skipped_reason": "outside_execute_window"}

    # trade_date · 실행 시점의 오늘 KST
    trade_date = datetime.now(tz=_KST).date().isoformat()
    items = await list_watchlist(trade_date)
    if not items:
        return {"skipped_reason": "empty_watchlist", "trade_date": trade_date}

    # 임계값 통과 종목만
    eligible = [
        it for it in items
        if it["composite_score"] >= params.watchlist_min_composite_score
    ]
    if not eligible:
        return {
            "trade_date": trade_date,
            "watchlist_size": len(items),
            "candidates": [],
            "entered": 0,
            "rejects": {"below_min_score": len(items)},
        }

    # 현재가 조회 (병렬)
    tickers = [it["ticker"] for it in eligible]
    prices = await fetch_current_prices(tickers)

    # rankings 매치 (선택 · 참고 지표)
    ranked_tickers: set[str] = set()
    if params.watchlist_use_rankings_confirm:
        try:
            ranked = await tickers_with_snapshots(window_sec=600)
            ranked_tickers = set(ranked)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[watchlist.exec] rankings 확인 실패 · %s · 스킵", exc)

    candidates: list[WatchlistExecutionCandidate] = []
    for it in eligible:
        ticker = it["ticker"]
        current = prices.get(ticker)
        prev_close = 0.0
        # v1: Watchlist item 에는 prev_close 저장 안됨 · LiveTapeUniverse 재조회 필요
        # TODO Week 4: Watchlist 저장 시 prev_close snapshot 하기
        # 임시로 current 사용 시 gap=0 · reject
        if current is None:
            candidates.append(WatchlistExecutionCandidate(
                ticker=ticker, composite_score=it["composite_score"],
                prev_close=0.0, current_price=0.0, gap_pct=0.0,
                in_rankings=(ticker in ranked_tickers),
                reject_reason="no_current_price",
            ))
            continue
        prev_close = await _fetch_prev_close(ticker)
        if prev_close <= 0:
            candidates.append(WatchlistExecutionCandidate(
                ticker=ticker, composite_score=it["composite_score"],
                prev_close=0.0, current_price=current, gap_pct=0.0,
                in_rankings=(ticker in ranked_tickers),
                reject_reason="no_prev_close",
            ))
            continue
        gap = compute_gap_pct(current, prev_close) or 0.0

        # 진입 조건: watchlist_gap_min ~ watchlist_gap_max 사이
        if gap < params.watchlist_gap_min_pct:
            reject = f"gap_below_min({gap*100:+.2f}%)"
        elif gap > params.watchlist_gap_max_pct:
            reject = f"gap_above_max_상투({gap*100:+.2f}%)"
        elif params.watchlist_use_rankings_confirm and ticker not in ranked_tickers:
            reject = "rankings_confirm_missing"
        else:
            reject = None

        candidates.append(WatchlistExecutionCandidate(
            ticker=ticker, composite_score=it["composite_score"],
            prev_close=prev_close, current_price=current, gap_pct=gap,
            in_rankings=(ticker in ranked_tickers),
            reject_reason=reject,
        ))

    # 진입 실행
    order_manager = _resolve_order_manager()
    entered = 0
    rejects: dict[str, int] = {}
    for c in candidates:
        if c.reject_reason:
            rejects[c.reject_reason] = rejects.get(c.reject_reason, 0) + 1
            continue

        # execute_entry 는 CandidateSignal 을 받으므로 합성
        synthetic = CandidateSignal(
            ticker=c.ticker,
            tape_score=c.composite_score,
            rank_velocity_score=1.0 if c.in_rankings else 0.0,
            trades_intensity_score=0.0,
            orderbook_score=0.0,
            last_price=c.current_price,
            return_pct=c.gap_pct,
            detected_at=datetime.now(tz=timezone.utc),
            raw_rank_delta=None,
            raw_trades_intensity=None,
            raw_bid_ratio=None,
        )
        result = await execute_entry(synthetic, order_manager)
        if result.ok:
            entered += 1
        else:
            rejects[result.reason or "entry_failed"] = rejects.get(result.reason or "entry_failed", 0) + 1

    stats = {
        "trade_date": trade_date,
        "watchlist_size": len(items),
        "eligible": len(eligible),
        "candidates": [
            {
                "ticker": c.ticker, "composite": c.composite_score,
                "gap_pct": round(c.gap_pct, 4),
                "prev_close": c.prev_close, "current": c.current_price,
                "in_rankings": c.in_rankings,
                "reject_reason": c.reject_reason,
            }
            for c in candidates
        ],
        "entered": entered,
        "rejects": rejects,
    }
    logger.info("[watchlist.exec] %s", stats)
    return stats


async def _fetch_prev_close(ticker: str) -> float:
    """전일 종가 조회 · LiveTapeUniverse.close_price 사용 (nightly refresh 값)."""
    from sqlalchemy import select
    from backend.services.db import get_session
    from backend.services.models import LiveTapeUniverse

    async with get_session() as session:
        stmt = select(LiveTapeUniverse.close_price).where(
            LiveTapeUniverse.ticker == ticker,
        )
        result = (await session.execute(stmt)).scalar_one_or_none()
    return float(result or 0.0)
