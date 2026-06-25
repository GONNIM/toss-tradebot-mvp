"""Sector Leader 백테스트 + 월별 정합 + 최근 시그널 (B-2f).

세 가지 분석 함수:
- compute_yoy_buckets: 수출 YoY 구간별 익월(혹은 best_lag 적용) 주가 평균 수익률
- compute_monthly_join: 월별 수출 + 주가 + 시그널 라벨 정합 표
- latest_signal_hint: 최근 발표 + lag 기반 향후 윈도우 추정

음의 상관 종목 (r < 0) 처리:
- 백테스트 자체는 동일 (구간별 평균 수익률)
- 라벨/regime 은 부호 반전 (수출↑ 시 주가↓ 기대 = 동행 일치로 표기)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd


# ─────────────────────────────────────────────────────────────────
# 데이터 모델
# ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BacktestBucket:
    label: str                  # "≥+50%" 등
    threshold_low: Optional[float]
    threshold_high: Optional[float]
    n_months: int
    mean_return_pct: float       # 평균 (월간 수익률, lag 적용)
    cumulative_return_pct: float # 누적 수익률 (단순 합산)


@dataclass(frozen=True)
class MonthlyJoinRow:
    month: str                   # 'YYYY-MM'
    export_value_musd: Optional[float]
    export_yoy_pct: Optional[float]
    price_close: Optional[float]
    return_pct: Optional[float]
    signal: str                  # 'agree_up'/'agree_down'/'disagree'/'neutral'/'no_data'


@dataclass(frozen=True)
class LatestSignalHint:
    month: str
    export_yoy_pct: Optional[float]
    bucket_label: str
    expected_window: str         # e.g. "2026-06 ~ 2026-08"
    regime: str                  # 'strong_growth'/'mild_growth'/'flat'/'decline'/'inverse'
    direction: str               # 'up'/'down' (r 부호 반영)
    based_on_lag: int            # best_lag months


# 고정 임계값
THRESHOLDS = [-10.0, 10.0, 50.0]


def _bucket_for(yoy: Optional[float]) -> tuple[int, str, Optional[float], Optional[float]]:
    if yoy is None:
        return -1, "—", None, None
    if yoy < THRESHOLDS[0]:
        return 0, "< -10%", None, THRESHOLDS[0]
    if yoy < THRESHOLDS[1]:
        return 1, "-10% ~ +10%", THRESHOLDS[0], THRESHOLDS[1]
    if yoy < THRESHOLDS[2]:
        return 2, "+10% ~ +50%", THRESHOLDS[1], THRESHOLDS[2]
    return 3, "≥ +50%", THRESHOLDS[2], None


# ─────────────────────────────────────────────────────────────────
# (a) 백테스트 — 구간별 평균/누적 수익률
# ─────────────────────────────────────────────────────────────────


def compute_yoy_buckets(
    export_yoy_by_month: dict[str, float],
    return_by_month: dict[str, float],
    lag_months: int = 0,
) -> list[BacktestBucket]:
    """수출 YoY 구간 4개 × 익월 (lag_months 적용) 주가 수익률.

    lag_months > 0: 수출 YoY 발생 후 k 개월 후 수익률 사용 (수출 선행 가정)
    lag_months < 0: 주가가 수출 선행 — 그 시점 적용
    lag_months = 0: 동시 시점
    """
    buckets: dict[int, list[float]] = {0: [], 1: [], 2: [], 3: []}

    sorted_months = sorted(export_yoy_by_month.keys())
    for i, m in enumerate(sorted_months):
        yoy = export_yoy_by_month.get(m)
        if yoy is None:
            continue
        # lag 적용 target month
        target_idx = i + lag_months
        if target_idx < 0 or target_idx >= len(sorted_months):
            continue
        target_month = sorted_months[target_idx]
        ret = return_by_month.get(target_month)
        if ret is None:
            continue
        idx, _, _, _ = _bucket_for(yoy)
        if idx < 0:
            continue
        buckets[idx].append(ret)

    out: list[BacktestBucket] = []
    for idx in range(4):
        rets = buckets[idx]
        _, label, lo, hi = _bucket_for(
            -20.0 if idx == 0 else (0.0 if idx == 1 else (20.0 if idx == 2 else 60.0))
        )
        if not rets:
            out.append(
                BacktestBucket(
                    label=label, threshold_low=lo, threshold_high=hi,
                    n_months=0, mean_return_pct=0.0, cumulative_return_pct=0.0,
                )
            )
            continue
        mean = sum(rets) / len(rets)
        # 누적 수익률 — 1.01 * 1.02 * … - 1 (compound)
        cum = 1.0
        for r in rets:
            cum *= (1.0 + r / 100.0)
        cum_pct = (cum - 1.0) * 100.0
        out.append(
            BacktestBucket(
                label=label, threshold_low=lo, threshold_high=hi,
                n_months=len(rets), mean_return_pct=mean,
                cumulative_return_pct=cum_pct,
            )
        )
    return out


# ─────────────────────────────────────────────────────────────────
# (b) 월별 정합 표 + 시그널 라벨
# ─────────────────────────────────────────────────────────────────


def compute_monthly_join(
    export_yoy_by_month: dict[str, float],
    export_value_by_month: dict[str, float],
    monthly_close_by_month: dict[str, float],
    monthly_return_by_month: dict[str, float],
    correlation_sign: int = 1,
) -> list[MonthlyJoinRow]:
    """월별 수출 + 주가 + 시그널 라벨 정합 표.

    correlation_sign = +1: 정의 상관 (수출↑+주가↑ = agree_up)
    correlation_sign = -1: 음의 상관 (수출↑+주가↓ = agree_up — 동행성 일치)
    """
    all_months = sorted(
        set(export_yoy_by_month.keys())
        | set(monthly_close_by_month.keys())
    )
    out: list[MonthlyJoinRow] = []
    for m in all_months:
        yoy = export_yoy_by_month.get(m)
        val = export_value_by_month.get(m)
        close = monthly_close_by_month.get(m)
        ret = monthly_return_by_month.get(m)

        # signal 라벨
        signal = "no_data"
        if yoy is not None and ret is not None:
            yoy_up = yoy > 0
            ret_up = ret > 0
            effective_up = ret_up if correlation_sign >= 0 else (not ret_up)
            if abs(yoy) < 1.0 and abs(ret) < 1.0:
                signal = "neutral"
            elif yoy_up == effective_up:
                signal = "agree_up" if yoy_up else "agree_down"
            else:
                signal = "disagree"

        out.append(
            MonthlyJoinRow(
                month=m,
                export_value_musd=val,
                export_yoy_pct=yoy,
                price_close=close,
                return_pct=ret,
                signal=signal,
            )
        )
    return out


# ─────────────────────────────────────────────────────────────────
# (c) 최근 시그널 힌트
# ─────────────────────────────────────────────────────────────────


def _shift_month(ym: str, delta: int) -> str:
    y, m = ym.split("-")
    base = date(int(y), int(m), 1)
    nm = base.month + delta
    ny = base.year
    while nm > 12:
        nm -= 12
        ny += 1
    while nm < 1:
        nm += 12
        ny -= 1
    return f"{ny:04d}-{nm:02d}"


def latest_signal_hint(
    export_yoy_by_month: dict[str, float],
    best_lag_months: int,
    correlation_r: float,
) -> Optional[LatestSignalHint]:
    """최근 발표 데이터 + best_lag → 향후 윈도우 추정."""
    if not export_yoy_by_month:
        return None
    latest_month = max(export_yoy_by_month.keys())
    yoy = export_yoy_by_month.get(latest_month)
    if yoy is None:
        return None

    _, bucket_label, _, _ = _bucket_for(yoy)

    # regime
    if math.isnan(correlation_r) or abs(correlation_r) < 0.4:
        regime = "low_signal"
    elif correlation_r >= 0:
        if yoy >= 50:
            regime = "strong_growth"
        elif yoy >= 10:
            regime = "mild_growth"
        elif yoy >= -10:
            regime = "flat"
        else:
            regime = "decline"
    else:
        # 음의 상관 — 수출↑ 시 주가 부진 기대
        regime = "inverse"

    direction = "up"
    if correlation_r >= 0:
        direction = "up" if yoy > 0 else "down"
    else:
        direction = "down" if yoy > 0 else "up"

    # 윈도우: 발표 다음 달 ~ +best_lag (양수일 때) 또는 latest 기준
    if best_lag_months > 0:
        start = _shift_month(latest_month, 1)
        end = _shift_month(latest_month, best_lag_months + 1)
    else:
        start = _shift_month(latest_month, 1)
        end = _shift_month(latest_month, 3)

    return LatestSignalHint(
        month=latest_month,
        export_yoy_pct=yoy,
        bucket_label=bucket_label,
        expected_window=f"{start} ~ {end}",
        regime=regime,
        direction=direction,
        based_on_lag=best_lag_months,
    )


# ─────────────────────────────────────────────────────────────────
# DataFrame 헬퍼 — 일봉 → 월말 종가 / 월간 수익률 (분석 모듈과 동일 로직)
# ─────────────────────────────────────────────────────────────────


def daily_to_monthly(daily: list[tuple[str, float]]) -> tuple[dict[str, float], dict[str, float]]:
    """일봉 [(date_str, close), ...] → (월말 종가 dict, 월간 수익률 dict)."""
    if not daily:
        return {}, {}
    df = pd.DataFrame(daily, columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    monthly_close = df["close"].resample("ME").last()
    monthly_return = monthly_close.pct_change() * 100.0
    close_map = {idx.strftime("%Y-%m"): float(v) for idx, v in monthly_close.items() if not pd.isna(v)}
    ret_map = {idx.strftime("%Y-%m"): float(v) for idx, v in monthly_return.items() if not pd.isna(v)}
    return close_map, ret_map
