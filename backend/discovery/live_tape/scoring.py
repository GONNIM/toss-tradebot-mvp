"""KR live tape composite score · Sprint 1 T43.

3개 소스(rank velocity · trades intensity · orderbook imbalance) 를 z-score 로 정규화 →
가중 합산 tape_score 산출 · 임계 초과 · 진입 조건 통과 시 candidate.

계획서: docs/plans/sniper/00-sprint1-plan.md §1-4 Composite Score 공식
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .orderbook import OrderbookSnapshot, poll_orderbook
from .params import get_sniper_params
from .rankings import rank_velocity
from .trades import TradesSnapshot, poll_trades

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CandidateSignal:
    ticker: str
    tape_score: float
    rank_velocity_score: float
    trades_intensity_score: float
    orderbook_score: float
    last_price: float
    return_pct: Optional[float]
    detected_at: datetime
    # 세부 raw 값 (감사 기록용)
    raw_rank_delta: Optional[int]
    raw_trades_intensity: Optional[float]
    raw_bid_ratio: Optional[float]


# ─── z-score 정규화 (베이스라인은 Sprint 1 단순 정적 · Sprint 1.5 이후 rolling) ───

def _rank_delta_to_z(delta: Optional[int]) -> float:
    """rank delta (양수 = 순위 상승) → z-score 근사.

    Baseline (KOSDAQ 일반): delta 0~5 (평범), 10 (관심), 20+ (급등 시작), 50+ (폭발).
    z = delta / 10.0 · z=2 는 delta=20 · z=5 는 delta=50.
    """
    if delta is None:
        return 0.0
    return max(0.0, delta / 10.0)


def _trades_intensity_to_z(intensity: Optional[float]) -> float:
    """초당 체결 건수 → z-score 근사.

    Baseline (KOSDAQ 평균): 0.5~3/s (평범), 10/s (관심), 30/s (급등).
    z = (intensity - 5) / 5 · z=2 는 15/s · z=5 는 30/s.
    Sprint 1.5 에서 종목별 rolling baseline 으로 대체 예정.
    """
    if intensity is None or intensity <= 0:
        return 0.0
    return max(0.0, (intensity - 5.0) / 5.0)


def _orderbook_ratio_to_z(bid_ratio: Optional[float]) -> float:
    """bid ratio (0.0~1.0) → z-score 근사.

    Baseline: 0.5 균형 · 0.6 소폭 우세 · 0.7+ 매수 강 · 0.8+ 폭등 setup.
    z = (bid_ratio - 0.5) / 0.05 · z=2 는 bid_ratio=0.6 · z=5 는 0.75.
    """
    if bid_ratio is None:
        return 0.0
    return max(0.0, (bid_ratio - 0.5) / 0.05)


async def score_ticker(ticker: str) -> Optional[CandidateSignal]:
    """단일 종목 composite score 산출.

    Returns:
        CandidateSignal or None (데이터 부족)
    """
    params = get_sniper_params()
    now = datetime.now(tz=timezone.utc)

    # 3 소스 병렬 조회
    rv = await rank_velocity(ticker, window_sec=300)   # 5분 window
    tr = await poll_trades(ticker)
    ob = await poll_orderbook(ticker)

    if rv is None and tr is None and ob is None:
        return None

    z_rank = _rank_delta_to_z(rv["delta"] if rv else None)
    z_trades = _trades_intensity_to_z(tr.intensity if tr else None)
    z_ob = _orderbook_ratio_to_z(ob.bid_ratio if ob else None)

    tape = (
        params.score_weight_rank * z_rank
        + params.score_weight_trades * z_trades
        + params.score_weight_orderbook * z_ob
    )

    last_price = 0.0
    if tr and tr.last_price:
        last_price = tr.last_price
    elif ob and ob.mid_price:
        last_price = ob.mid_price
    elif rv and rv.get("last_price"):
        last_price = rv["last_price"]

    return CandidateSignal(
        ticker=ticker,
        tape_score=round(tape, 3),
        rank_velocity_score=round(z_rank, 3),
        trades_intensity_score=round(z_trades, 3),
        orderbook_score=round(z_ob, 3),
        last_price=last_price,
        return_pct=rv.get("last_return_pct") if rv else None,
        detected_at=now,
        raw_rank_delta=rv["delta"] if rv else None,
        raw_trades_intensity=tr.intensity if tr else None,
        raw_bid_ratio=ob.bid_ratio if ob else None,
    )


def is_candidate(signal: CandidateSignal) -> tuple[bool, Optional[str]]:
    """candidate 진입 조건 통과 여부.

    조건 (AND):
    - tape_score >= tape_score_threshold
    - rank_velocity_score >= rank_velocity_z_min
    - trades_intensity_score >= trades_intensity_z_min
    - orderbook_score >= orderbook_z_min
    - return_pct in [entry_return_min_pct, entry_return_max_pct]

    Returns:
        (True, None) if 통과 · (False, reason) otherwise
    """
    params = get_sniper_params()

    if signal.tape_score < params.tape_score_threshold:
        return False, f"tape_score<{params.tape_score_threshold}"
    if signal.rank_velocity_score < params.rank_velocity_z_min:
        return False, f"rank_z<{params.rank_velocity_z_min}"
    if signal.trades_intensity_score < params.trades_intensity_z_min:
        return False, f"trades_z<{params.trades_intensity_z_min}"
    if signal.orderbook_score < params.orderbook_z_min:
        return False, f"orderbook_z<{params.orderbook_z_min}"

    if signal.return_pct is None:
        return False, "no_return"
    if signal.return_pct < params.entry_return_min_pct:
        return False, f"return<{params.entry_return_min_pct}"
    if signal.return_pct > params.entry_return_max_pct:
        return False, f"return>{params.entry_return_max_pct}"

    return True, None
