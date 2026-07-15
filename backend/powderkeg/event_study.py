"""이벤트 스터디 · CAR 계산 · Phase 7-4.

지시서 §7-4:
    이벤트 후 t+1일 시가 진입 가정 → 1/3/6/12개월 CAR, 승률, MDD.

취급 방식 (v1 · 절대 수익률):
    t=0 · 이벤트 발생일 (release_date)
    t+1 · 다음 거래일 시가 진입
    t+N · N 영업일 후 종가 청산
    return = (exit - entry) / entry

지수 대비 초과 수익 (CAR) 은 v2 로 이관.
v1 은 absolute return · 후속 라운드에서 KOSPI/KOSDAQ 벤치마크 차감.
"""
from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# 표준 window · 영업일 근사 (실 거래일 수) · 지시서 §7-4 명시
WINDOW_DAYS = {
    "1d": 1,
    "1m": 21,
    "3m": 63,
    "6m": 126,
    "12m": 252,
}


@dataclass(frozen=True)
class SingleEventReturn:
    ticker: str
    event_date: str                # YYYY-MM-DD (event day = t=0)
    entry_date: Optional[str]      # t+1 실 거래일
    entry_price: Optional[float]
    per_window_returns: dict[str, Optional[float]] = field(default_factory=dict)
    error: Optional[str] = None


def _next_trading_day_index(dates_index, event_date: date) -> Optional[int]:
    """dates_index 에서 event_date 초과 첫 인덱스."""
    for i, d in enumerate(dates_index):
        # d: datetime or pandas Timestamp
        try:
            di = d.date() if hasattr(d, "date") else d
        except Exception:  # noqa: BLE001
            continue
        if di > event_date:
            return i
    return None


async def compute_event_return(
    ticker: str,
    event_date: date,
    windows: dict[str, int] = WINDOW_DAYS,
    extra_padding_days: int = 30,
) -> SingleEventReturn:
    """단일 이벤트 · window 별 수익률.

    Args:
        ticker: 종목 코드 (KRX 6자리)
        event_date: 이벤트 발생일 (t=0)
        windows: {label: N_trading_days}
        extra_padding_days: 데이터 조회 여유 (max window + padding)
    """
    try:
        import FinanceDataReader as fdr
    except ImportError:
        return SingleEventReturn(
            ticker=ticker, event_date=event_date.isoformat(),
            entry_date=None, entry_price=None, error="fdr_not_installed",
        )

    # 여유롭게 조회 (event_date 포함 · 최대 window + padding)
    max_window = max(windows.values())
    end = event_date + timedelta(days=int(max_window * 1.5) + extra_padding_days)
    start = event_date - timedelta(days=5)

    try:
        df = fdr.DataReader(ticker, start, end)
    except Exception as exc:  # noqa: BLE001
        return SingleEventReturn(
            ticker=ticker, event_date=event_date.isoformat(),
            entry_date=None, entry_price=None, error=f"fdr_fetch_failed:{exc}",
        )

    if df is None or df.empty:
        return SingleEventReturn(
            ticker=ticker, event_date=event_date.isoformat(),
            entry_date=None, entry_price=None, error="no_price_data",
        )

    # 시가·종가 컬럼
    if "Open" not in df.columns or "Close" not in df.columns:
        return SingleEventReturn(
            ticker=ticker, event_date=event_date.isoformat(),
            entry_date=None, entry_price=None, error="missing_ohlc_columns",
        )

    idx = df.index.tolist()
    entry_i = _next_trading_day_index(idx, event_date)
    if entry_i is None:
        return SingleEventReturn(
            ticker=ticker, event_date=event_date.isoformat(),
            entry_date=None, entry_price=None, error="no_next_trading_day",
        )

    entry_price = float(df["Open"].iloc[entry_i])
    entry_date_str = idx[entry_i].date().isoformat() if hasattr(idx[entry_i], "date") else str(idx[entry_i])

    if entry_price <= 0:
        return SingleEventReturn(
            ticker=ticker, event_date=event_date.isoformat(),
            entry_date=entry_date_str, entry_price=None, error="entry_price_zero",
        )

    per_window: dict[str, Optional[float]] = {}
    for label, n in windows.items():
        target_i = entry_i + n
        if target_i >= len(df):
            per_window[label] = None   # 데이터 부족
            continue
        exit_price = float(df["Close"].iloc[target_i])
        if exit_price <= 0:
            per_window[label] = None
            continue
        per_window[label] = (exit_price - entry_price) / entry_price

    return SingleEventReturn(
        ticker=ticker, event_date=event_date.isoformat(),
        entry_date=entry_date_str, entry_price=entry_price,
        per_window_returns=per_window,
    )


# ─── 집계 ─────────────────────────────────
@dataclass
class WindowStats:
    label: str
    n: int
    mean_return: float
    median_return: float
    win_rate: float                # >0 비율
    std: float
    t_stat: float                  # mean / (std / sqrt(n))
    max_return: float
    min_return: float


@dataclass
class AggregatedResult:
    event_type: str
    total_events: int
    valid_events: int              # 가격 데이터 있어 계산 가능
    per_window: dict[str, WindowStats] = field(default_factory=dict)
    error_counts: dict[str, int] = field(default_factory=dict)


def aggregate_returns(
    event_type: str,
    returns: list[SingleEventReturn],
    windows: dict[str, int] = WINDOW_DAYS,
) -> AggregatedResult:
    """이벤트 반환들을 window 별 통계로 집계."""
    result = AggregatedResult(event_type=event_type, total_events=len(returns), valid_events=0)
    # 에러 카운트
    for r in returns:
        if r.error:
            result.error_counts[r.error] = result.error_counts.get(r.error, 0) + 1
    result.valid_events = sum(1 for r in returns if r.entry_price is not None)

    for label in windows:
        vals = [r.per_window_returns.get(label) for r in returns if r.entry_price is not None]
        vals = [v for v in vals if v is not None]
        if not vals:
            continue
        n = len(vals)
        mean_ret = statistics.mean(vals)
        median_ret = statistics.median(vals)
        win_rate = sum(1 for v in vals if v > 0) / n
        std = statistics.pstdev(vals) if n > 1 else 0.0
        t_stat = (mean_ret / (std / math.sqrt(n))) if std > 0 else 0.0
        result.per_window[label] = WindowStats(
            label=label, n=n, mean_return=round(mean_ret, 5),
            median_return=round(median_ret, 5), win_rate=round(win_rate, 4),
            std=round(std, 5), t_stat=round(t_stat, 3),
            max_return=round(max(vals), 5), min_return=round(min(vals), 5),
        )
    return result
