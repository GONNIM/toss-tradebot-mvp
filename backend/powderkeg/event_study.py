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

    # entry_price_zero fallback · B3 (거래정지) 이벤트 시 t+1 시가 부재 필연
    #   최대 5 거래일 후행 검색 · 첫 유효 시가 사용 (거래재개 후 진입 가정)
    MAX_FALLBACK_DAYS = 5
    fallback_limit = min(entry_i + MAX_FALLBACK_DAYS + 1, len(df))
    entry_price = 0.0
    while entry_i < fallback_limit:
        candidate = float(df["Open"].iloc[entry_i])
        if candidate > 0:
            entry_price = candidate
            break
        entry_i += 1

    entry_date_str = (
        idx[entry_i].date().isoformat() if entry_i < len(df) and hasattr(idx[entry_i], "date")
        else None
    )

    if entry_price <= 0:
        return SingleEventReturn(
            ticker=ticker, event_date=event_date.isoformat(),
            entry_date=entry_date_str, entry_price=None,
            error=f"entry_price_zero_within_{MAX_FALLBACK_DAYS}d_fallback",
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
    # 이중 리포트 · 상폐 -100% imputation (v1.10 · 2026-07-16 · 생존 편향 fix)
    n_imputed: int = 0                             # imputed 표본 (survived + delisted)
    delisted_count: int = 0                        # -1.0 imputation 대상
    mean_return_imputed: float = 0.0               # 상폐 -100% 포함
    win_rate_imputed: float = 0.0
    t_stat_imputed: float = 0.0


@dataclass
class AggregatedResult:
    event_type: str
    total_events: int
    valid_events: int              # 가격 데이터 있어 계산 가능
    per_window: dict[str, WindowStats] = field(default_factory=dict)
    error_counts: dict[str, int] = field(default_factory=dict)
    imputed_events: int = 0        # 상폐 imputation 대상 (delisted proxy)


# 상폐 proxy · 이 error 종류는 -100% imputation 대상
# (지시서 §7-4 · 백테스트 게이트 정확성 · 리뷰어 생존 편향 지적 대응)
_DELISTING_PROXIES = frozenset({
    "entry_price_zero_within_5d_fallback",   # 5일 fallback 후에도 시가 0 · 대부분 상폐
    "no_next_trading_day",                    # event 이후 거래일 부재 · 상폐
    "no_price_data",                          # FDR 응답 empty · 티커 존재 안함
})
_IMPUTED_RETURN = -1.0                        # 상폐 -100% (원금 전액 손실 가정 · 보수적)


def aggregate_returns(
    event_type: str,
    returns: list[SingleEventReturn],
    windows: dict[str, int] = WINDOW_DAYS,
) -> AggregatedResult:
    """이벤트 반환들을 window 별 통계로 집계 · 상폐 imputation 이중 리포트.

    v1.10 (2026-07-16 · 리뷰어 지적):
      "-100%에 수렴한 최악의 1,318건이 표본에서 통째로 빠진 채 살아남은 종목만으로 계산한 평균"
      → 상폐 proxy error 를 -1.0 imputation · window별 두 개 통계 병기.
    """
    result = AggregatedResult(event_type=event_type, total_events=len(returns), valid_events=0)
    for r in returns:
        if r.error:
            result.error_counts[r.error] = result.error_counts.get(r.error, 0) + 1
    result.valid_events = sum(1 for r in returns if r.entry_price is not None)
    result.imputed_events = sum(1 for r in returns if r.error in _DELISTING_PROXIES)

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

        # imputed · 상폐 proxy 를 -1.0 로 포함
        vals_imputed = list(vals) + [_IMPUTED_RETURN] * result.imputed_events
        n_i = len(vals_imputed)
        mean_i = statistics.mean(vals_imputed)
        win_i = sum(1 for v in vals_imputed if v > 0) / n_i
        std_i = statistics.pstdev(vals_imputed) if n_i > 1 else 0.0
        t_i = (mean_i / (std_i / math.sqrt(n_i))) if std_i > 0 else 0.0

        result.per_window[label] = WindowStats(
            label=label, n=n, mean_return=round(mean_ret, 5),
            median_return=round(median_ret, 5), win_rate=round(win_rate, 4),
            std=round(std, 5), t_stat=round(t_stat, 3),
            max_return=round(max(vals), 5), min_return=round(min(vals), 5),
            n_imputed=n_i,
            delisted_count=result.imputed_events,
            mean_return_imputed=round(mean_i, 5),
            win_rate_imputed=round(win_i, 4),
            t_stat_imputed=round(t_i, 3),
        )
    return result
