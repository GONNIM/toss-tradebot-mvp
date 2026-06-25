"""미래 주가 예측 모듈 (B-2g).

계층 1 — Lagged Linear Regression + Bootstrap CI
계층 2 — Multi-horizon Forecast (1M / 3M / 6M)
계층 4 (간단) — OOS 70/30 검증

수학:
  - OLS: monthly_return(t+lag) = α + β·export_yoy(t) + ε
  - β̂ = Cov(x,y)/Var(x), α̂ = ȳ - β̂x̄
  - σ²_ε = Σε² / (n-2)
  - 예측 분산 = σ²_ε * (1 + 1/n + (x_new - x̄)²/SSx)
  - 95% CI ≈ ŷ ± 1.96·sqrt(예측 분산)  (작은 표본에선 z=1.96 근사 — t 사용 X, 의존성 회피)
  - R² = 1 - SS_res/SS_tot
  - hit-rate = 부호 일치 비율

표본 크기 < 10 시 신뢰도 매우 낮음 — 응답에 sample_warning 플래그.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional


# ─────────────────────────────────────────────────────────────────
# 데이터 모델
# ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RegressionResult:
    horizon_months: int
    n_samples: int
    alpha: float
    beta: float
    sigma: float                 # 잔차 표준편차
    r_squared: float
    p_value_approx: float        # z-기반 근사
    rmse: float
    hit_rate: float              # 부호 일치 비율
    x_mean: float
    x_var_sum: float             # SSx = Σ(x-x̄)²


@dataclass(frozen=True)
class HorizonForecast:
    horizon_months: int
    n_samples: int
    r_squared: float
    p_value_approx: float
    hit_rate: float
    alpha: float
    beta: float
    rmse: float
    latest_input_yoy: float
    point_estimate_pct: float
    ci_low_pct: float            # 95% CI
    ci_high_pct: float
    sample_warning: bool         # n < 10 또는 r² < 0.05


@dataclass(frozen=True)
class FanChartPoint:
    month_offset: int            # 1 = 1개월 후
    target_month: str            # 'YYYY-MM'
    point_estimate_pct: float
    sigma_pct: float
    ci_low_pct: float            # ±1.96σ
    ci_high_pct: float


@dataclass(frozen=True)
class OOSMetrics:
    train_n: int
    test_n: int
    mae: float
    rmse: float
    hit_rate: float              # test set 부호 일치
    directional_accuracy: float  # |actual| > 1% 기준만


@dataclass(frozen=True)
class HistoricalBand:
    """종목 N개월 rolling 누적 수익률의 실측 분위수.

    회귀 95% CI 의 음수 가격 문제를 회피하기 위해 도입 (2026-06-25).
    비모수적 — 실제 발생한 수익률 분포의 P10/P50/P90.
    """
    horizon_months: int
    n_windows: int               # rolling window 개수
    p10_pct: float               # 약세 분위수
    p50_pct: float               # 중앙값
    p90_pct: float               # 강세 분위수


@dataclass(frozen=True)
class Verdict:
    """종합 판정 — 사용자 의사결정 컨텍스트."""
    color: str         # green / amber / red
    label: str         # "강한 상승 시그널" / "약한 상승" / "중립" / "하락" / "이례" / "신뢰 낮음"
    context: str       # 한 줄 컨텍스트
    action_hint: str   # "진입 가치" / "관심" / "관망" / "비추천"


@dataclass(frozen=True)
class RiskReward:
    """수익/리스크 비율."""
    ratio: float           # upside / downside
    grade: str             # excellent / good / weak / too_high
    grade_label: str       # 한국어 라벨
    upside_pct: float
    downside_pct: float


@dataclass(frozen=True)
class StopTakeProfit:
    """권장 손절선·익절선."""
    stop_price: float
    stop_pct: float        # 현재가 대비
    stop_basis: str        # 산출 근거
    take_price: float
    take_pct: float
    take_basis: str


# ─────────────────────────────────────────────────────────────────
# OLS 회귀 (numpy 없이 — 명시적 계산)
# ─────────────────────────────────────────────────────────────────


Z_95 = 1.96  # 정규분포 임계값 (z=1.96 ≈ 95% CI, t-분포 대용)


def _ols(x: list[float], y: list[float]) -> Optional[RegressionResult]:
    """단변량 OLS — 외부 패키지 없이 직접 계산."""
    n = len(x)
    if n < 3 or n != len(y):
        return None
    x_mean = sum(x) / n
    y_mean = sum(y) / n
    ssx = sum((xi - x_mean) ** 2 for xi in x)
    if ssx < 1e-9:
        return None
    sxy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
    beta = sxy / ssx
    alpha = y_mean - beta * x_mean
    # residuals
    residuals = [yi - (alpha + beta * xi) for xi, yi in zip(x, y)]
    ss_res = sum(r * r for r in residuals)
    ss_tot = sum((yi - y_mean) ** 2 for yi in y)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 1e-9 else 0.0
    sigma2 = ss_res / max(n - 2, 1)
    sigma = math.sqrt(sigma2)
    # SE(β) for p-value approx
    se_beta = math.sqrt(sigma2 / ssx) if ssx > 0 else float("inf")
    t_stat = beta / se_beta if se_beta > 0 else 0.0
    # z 근사 양측 p-value
    p_value = 2 * (1 - _phi(abs(t_stat)))
    # hit rate — 부호 일치
    hits = 0
    for xi, yi in zip(x, y):
        pred = alpha + beta * xi
        if (yi >= 0) == (pred >= 0):
            hits += 1
    hit_rate = hits / n
    rmse = math.sqrt(ss_res / n)
    return RegressionResult(
        horizon_months=0, n_samples=n,
        alpha=alpha, beta=beta, sigma=sigma,
        r_squared=r_squared, p_value_approx=p_value,
        rmse=rmse, hit_rate=hit_rate,
        x_mean=x_mean, x_var_sum=ssx,
    )


def _phi(z: float) -> float:
    """표준정규 CDF — Abramowitz & Stegun 근사."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


# ─────────────────────────────────────────────────────────────────
# Multi-horizon Forecast
# ─────────────────────────────────────────────────────────────────


def _align_lagged(
    yoy_by_month: dict[str, float],
    return_by_month: dict[str, float],
    lag_months: int,
) -> tuple[list[float], list[float]]:
    """yoy(t)와 return(t+lag) 정합 (정렬된 월 시퀀스 기준)."""
    months_sorted = sorted(set(yoy_by_month.keys()) | set(return_by_month.keys()))
    xs: list[float] = []
    ys: list[float] = []
    for i, m in enumerate(months_sorted):
        x = yoy_by_month.get(m)
        target_idx = i + lag_months
        if target_idx < 0 or target_idx >= len(months_sorted):
            continue
        target_m = months_sorted[target_idx]
        y = return_by_month.get(target_m)
        if x is None or y is None:
            continue
        xs.append(x)
        ys.append(y)
    return xs, ys


def multi_horizon_forecast(
    yoy_by_month: dict[str, float],
    return_by_month: dict[str, float],
    latest_yoy: float,
    horizons: tuple[int, ...] = (1, 3, 6),
) -> list[HorizonForecast]:
    """1M / 3M / 6M 등 각 horizon별 OLS + 95% CI."""
    out: list[HorizonForecast] = []
    for h in horizons:
        x, y = _align_lagged(yoy_by_month, return_by_month, h)
        reg = _ols(x, y)
        if reg is None:
            continue
        # 점추정
        point = reg.alpha + reg.beta * latest_yoy
        # 예측 분산
        pred_var = reg.sigma ** 2 * (
            1 + 1 / reg.n_samples
            + (latest_yoy - reg.x_mean) ** 2 / reg.x_var_sum
        )
        margin = Z_95 * math.sqrt(pred_var)
        out.append(
            HorizonForecast(
                horizon_months=h,
                n_samples=reg.n_samples,
                r_squared=reg.r_squared,
                p_value_approx=reg.p_value_approx,
                hit_rate=reg.hit_rate,
                alpha=reg.alpha,
                beta=reg.beta,
                rmse=reg.rmse,
                latest_input_yoy=latest_yoy,
                point_estimate_pct=point,
                ci_low_pct=point - margin,
                ci_high_pct=point + margin,
                sample_warning=(reg.n_samples < 10 or reg.r_squared < 0.05),
            )
        )
    return out


# ─────────────────────────────────────────────────────────────────
# Fan Chart Points
# ─────────────────────────────────────────────────────────────────


def fan_chart_points(
    yoy_by_month: dict[str, float],
    return_by_month: dict[str, float],
    latest_yoy: float,
    latest_data_month: str,
    n_horizons: int = 6,
) -> list[FanChartPoint]:
    """미래 1~n 개월의 점추정 + σ — 각 horizon 별 독립 회귀."""
    out: list[FanChartPoint] = []
    for h in range(1, n_horizons + 1):
        x, y = _align_lagged(yoy_by_month, return_by_month, h)
        reg = _ols(x, y)
        if reg is None:
            continue
        point = reg.alpha + reg.beta * latest_yoy
        pred_var = reg.sigma ** 2 * (
            1 + 1 / reg.n_samples
            + (latest_yoy - reg.x_mean) ** 2 / reg.x_var_sum
        )
        sigma = math.sqrt(pred_var)
        target_m = _shift_month(latest_data_month, h)
        out.append(
            FanChartPoint(
                month_offset=h,
                target_month=target_m,
                point_estimate_pct=point,
                sigma_pct=sigma,
                ci_low_pct=point - Z_95 * sigma,
                ci_high_pct=point + Z_95 * sigma,
            )
        )
    return out


def compute_verdict(
    horizon: HorizonForecast,
    band: Optional[HistoricalBand],
    oos_hit_rate: Optional[float],
) -> Verdict:
    """종합 판정 — 결론 한 줄 + 컨텍스트 + 액션 힌트."""
    pt = horizon.point_estimate_pct
    r2 = horizon.r_squared
    hit_input = horizon.hit_rate

    # 1) 신뢰도 매우 낮음 — 우선
    if horizon.sample_warning or (oos_hit_rate is not None and oos_hit_rate < 0.4):
        oos_text = (
            f"OOS 부호 적중 {(oos_hit_rate * 100):.0f}%"
            if oos_hit_rate is not None
            else "표본 부족"
        )
        return Verdict(
            color="red",
            label="신뢰 매우 낮음",
            context=f"{oos_text} — 모델 단독 판단 금지, 다른 변수와 함께 사용",
            action_hint="비추천",
        )

    # 2) 통계적 이례 — 24M 범위 외삽
    if band is not None:
        if pt > band.p90_pct:
            return Verdict(
                color="amber",
                label="강한 상승 시그널 — 통계적 이례",
                context=f"점추정({pt:+.1f}%)이 24M 강세 범위(P90 {band.p90_pct:+.1f}%) 초과 — 외삽 영역",
                action_hint="관심 (외삽 영역 주의)",
            )
        if pt < band.p10_pct:
            return Verdict(
                color="amber",
                label="강한 하락 시그널 — 통계적 이례",
                context=f"점추정({pt:+.1f}%)이 24M 약세 범위(P10 {band.p10_pct:+.1f}%) 미달 — 외삽 영역",
                action_hint="관심 (외삽 영역 주의)",
            )

    # 3) 표준 분류
    if pt >= 5 and r2 >= 0.15:
        return Verdict(
            color="green",
            label="강한 상승 시그널",
            context=f"진입 가치 있음 · R² {r2:.2f} · 표본 부호 적중 {(hit_input * 100):.0f}%",
            action_hint="관심 가치",
        )
    if pt >= 2 and r2 >= 0.05:
        return Verdict(
            color="green",
            label="약한 상승 시그널",
            context=f"방향 일관 · R² {r2:.2f} · 보조 신호로 활용",
            action_hint="관심",
        )
    if pt <= -5 and r2 >= 0.1:
        return Verdict(
            color="red",
            label="하락 시그널",
            context=f"진입 신중 권장 · R² {r2:.2f}",
            action_hint="비추천",
        )
    return Verdict(
        color="amber",
        label="중립 (시그널 약함)",
        context=f"수익률 절대값 작음 · 점추정 {pt:+.1f}% · R² {r2:.2f}",
        action_hint="관망",
    )


def compute_rr_ratio(
    current_price: float,
    point_pct: float,
    band: Optional[HistoricalBand],
) -> Optional[RiskReward]:
    """수익/리스크 비율 — (target - current) / (current - P10_price)."""
    if band is None or current_price <= 0:
        return None
    target_price = current_price * (1 + point_pct / 100)
    p10_price = max(0.0, current_price * (1 + band.p10_pct / 100))

    upside = target_price - current_price
    downside = current_price - p10_price

    if downside < 1 or upside <= 0:
        # 손실 거의 없거나 점추정이 하락이면 R/R 계산 무의미
        return None

    ratio = upside / downside

    if ratio >= 10:
        grade = "too_high"
        grade_label = "⚠️ 너무 높음 (낙관 과대 의심)"
    elif ratio >= 3:
        grade = "excellent"
        grade_label = "⭐ 우수"
    elif ratio >= 1.5:
        grade = "good"
        grade_label = "✓ 양호"
    else:
        grade = "weak"
        grade_label = "△ 부족"

    return RiskReward(
        ratio=ratio,
        grade=grade,
        grade_label=grade_label,
        upside_pct=(target_price / current_price - 1) * 100,
        downside_pct=(p10_price / current_price - 1) * 100,
    )


def recommend_stop_take(
    current_price: float,
    point_pct: float,
    band: Optional[HistoricalBand],
) -> Optional[StopTakeProfit]:
    """Stop Loss = max(P10 가격, 현재가 -30%) · Take Profit = 점추정 80% 도달."""
    if band is None or current_price <= 0:
        return None
    p10_price = current_price * (1 + band.p10_pct / 100)
    # P10이 너무 낙폭 크면 -30%를 보수적 floor 로 사용
    drawdown_30_price = current_price * 0.7
    stop_price = max(p10_price, drawdown_30_price)
    stop_pct = (stop_price / current_price - 1) * 100

    target_price = current_price * (1 + point_pct / 100)
    if target_price <= current_price:
        # 상승 점추정이 아니면 take profit 불가
        return None
    take_price = current_price + (target_price - current_price) * 0.8
    take_pct = (take_price / current_price - 1) * 100

    return StopTakeProfit(
        stop_price=stop_price,
        stop_pct=stop_pct,
        stop_basis=(
            f"24M P10({band.p10_pct:+.1f}%) 또는 -30% 중 보수적"
            if p10_price >= drawdown_30_price
            else "24M P10 보다 보수적인 -30% floor 적용"
        ),
        take_price=take_price,
        take_pct=take_pct,
        take_basis=f"기본 시그널 점추정({point_pct:+.1f}%)의 80% 도달 시 익절 검토",
    )


def historical_quantiles(
    monthly_close_by_month: dict[str, float],
    horizon_months: int,
) -> Optional[HistoricalBand]:
    """월말 종가 dict + horizon → 누적 수익률 rolling window의 P10/P50/P90.

    예) 24M 종가 + horizon=3 → 22개 rolling window의 3M 누적 수익률 분위수.
    """
    sorted_months = sorted(monthly_close_by_month.keys())
    if len(sorted_months) < horizon_months + 2:
        return None
    cum_returns: list[float] = []
    for i in range(len(sorted_months) - horizon_months):
        start_close = monthly_close_by_month[sorted_months[i]]
        end_close = monthly_close_by_month[sorted_months[i + horizon_months]]
        if start_close <= 0:
            continue
        cum_returns.append((end_close / start_close - 1) * 100.0)
    if not cum_returns:
        return None
    cum_returns.sort()
    n = len(cum_returns)

    def quantile(q: float) -> float:
        idx = q * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return cum_returns[lo] * (1 - frac) + cum_returns[hi] * frac

    return HistoricalBand(
        horizon_months=horizon_months,
        n_windows=n,
        p10_pct=quantile(0.1),
        p50_pct=quantile(0.5),
        p90_pct=quantile(0.9),
    )


def _shift_month(ym: str, delta: int) -> str:
    y, m = ym.split("-")
    yy, mm = int(y), int(m)
    mm += delta
    while mm > 12:
        mm -= 12
        yy += 1
    while mm < 1:
        mm += 12
        yy -= 1
    return f"{yy:04d}-{mm:02d}"


# ─────────────────────────────────────────────────────────────────
# Bootstrap Bucket CI (사용자 결정: 계층 1 포함)
# ─────────────────────────────────────────────────────────────────


def bootstrap_mean_ci(
    samples: list[float],
    n_iter: int = 2000,
    ci: float = 0.95,
    seed: int = 42,
) -> tuple[float, float, float]:
    """단순 부트스트랩 평균의 (mean, ci_low, ci_high)."""
    if not samples:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    means: list[float] = []
    n = len(samples)
    for _ in range(n_iter):
        resample = [samples[rng.randrange(n)] for _ in range(n)]
        means.append(sum(resample) / n)
    means.sort()
    lo = means[int((1 - ci) / 2 * n_iter)]
    hi = means[int((1 + ci) / 2 * n_iter)]
    return sum(samples) / n, lo, hi


# ─────────────────────────────────────────────────────────────────
# OOS 70/30 검증
# ─────────────────────────────────────────────────────────────────


def oos_validate(
    yoy_by_month: dict[str, float],
    return_by_month: dict[str, float],
    lag_months: int,
    train_ratio: float = 0.7,
) -> Optional[OOSMetrics]:
    """70/30 시간 순서 split — train 회귀 → test 예측 평가."""
    x, y = _align_lagged(yoy_by_month, return_by_month, lag_months)
    n = len(x)
    if n < 10:
        return None
    train_n = int(n * train_ratio)
    if train_n < 5 or n - train_n < 3:
        return None
    x_train, y_train = x[:train_n], y[:train_n]
    x_test, y_test = x[train_n:], y[train_n:]

    reg = _ols(x_train, y_train)
    if reg is None:
        return None

    preds = [reg.alpha + reg.beta * xi for xi in x_test]
    errors = [yi - pi for yi, pi in zip(y_test, preds)]
    mae = sum(abs(e) for e in errors) / len(errors)
    rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
    sign_hits = sum(1 for yi, pi in zip(y_test, preds) if (yi >= 0) == (pi >= 0))
    hit_rate = sign_hits / len(preds)
    # directional accuracy — |actual| > 1% 만 대상
    meaningful = [(yi, pi) for yi, pi in zip(y_test, preds) if abs(yi) > 1.0]
    if meaningful:
        dir_hits = sum(1 for yi, pi in meaningful if (yi >= 0) == (pi >= 0))
        dir_acc = dir_hits / len(meaningful)
    else:
        dir_acc = float("nan")

    return OOSMetrics(
        train_n=train_n,
        test_n=len(preds),
        mae=mae,
        rmse=rmse,
        hit_rate=hit_rate,
        directional_accuracy=dir_acc,
    )
