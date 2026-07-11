"""Toss orderbook 폴러 · Sprint 1 T41.

20초 주기 GET /api/v1/orderbook?symbol=... 폴링.
매수/매도 상위 5호가 잔량 분석 → imbalance 산출:
  · bid_top5_volume, ask_top5_volume
  · bid_ratio = bid / (bid + ask) — 1.0 → 극단적 매수 우세
  · spread_pct = (ask1 - bid1) / mid — 유동성 지표 (좁을수록 두터움)
  · mid_price

계획서: docs/plans/sniper/00-sprint1-plan.md §2-2
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from backend.execution.brokers.toss_client import TossClient, get_toss_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrderbookSnapshot:
    ticker: str
    bid_top5_volume: float
    ask_top5_volume: float
    bid_ratio: float                # 0.0~1.0
    spread_pct: float               # (ask1-bid1) / mid
    mid_price: float
    captured_at: datetime


async def poll_orderbook(ticker: str, toss_client: Optional[TossClient] = None) -> Optional[OrderbookSnapshot]:
    """단일 종목 호가 스냅샷.

    Returns:
        OrderbookSnapshot or None (오류·빈 응답)
    """
    client = toss_client or get_toss_client()
    now = datetime.now(tz=timezone.utc)
    try:
        env = client.orderbook(ticker)
    except Exception as exc:  # noqa: BLE001
        logger.warning("orderbook poll 실패 · %s · %s", ticker, exc)
        return None

    data = env.result if isinstance(env.result, dict) else {}
    bids = data.get("bids") or []
    asks = data.get("asks") or []
    if not bids or not asks:
        return None

    top5_bid_vol = sum(float(b.get("volume", 0) or 0) for b in bids[:5])
    top5_ask_vol = sum(float(a.get("volume", 0) or 0) for a in asks[:5])
    total = top5_bid_vol + top5_ask_vol
    bid_ratio = top5_bid_vol / total if total > 0 else 0.5

    bid1 = float(bids[0].get("price", 0) or 0)
    ask1 = float(asks[0].get("price", 0) or 0)
    mid = (bid1 + ask1) / 2 if (bid1 and ask1) else max(bid1, ask1)
    spread_pct = (ask1 - bid1) / mid if mid > 0 else 0.0

    return OrderbookSnapshot(
        ticker=ticker,
        bid_top5_volume=top5_bid_vol,
        ask_top5_volume=top5_ask_vol,
        bid_ratio=bid_ratio,
        spread_pct=spread_pct,
        mid_price=mid,
        captured_at=now,
    )
