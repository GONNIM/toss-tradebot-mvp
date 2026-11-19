"""채점 엔진 · 순수 함수 (1119-03 ① · 기획서 3-3~3-6 · 4절 · Fable 조건 가).

가격은 모두 인자로 받는다 (①에서는 가격 저장 · 호출 없음 · 실제 판정 기간 성적은 계산하지 않는다).
기존 backtest 엔진은 부르지 않는다. 숫자는 「추정 · 보장 아님」.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Any, Optional, Sequence

# ─── 규칙 상수 (rules-v1 초안과 같은 값 · 고정 전에는 바뀔 수 있음) ─────────
ALPHA_ONE_SIDED = 0.0125          # 국내 유형 4개 · 한쪽 5% · Bonferroni
MIN_MONTHS = 12
MIN_EVENTS_ALL = 100
MIN_EVENTS_JUDGE = 50
MAX_NO_PRICE_RATIO = 0.05
JUDGE_START = date(2023, 1, 1)
TRIM_FRACTION = 0.01
EVENT_WINDOW_TRADING_DAYS = 5


# ═══ t 분포 ════════════════════════════════════════════════
def _betacf(a: float, b: float, x: float) -> float:
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """정규화 불완전 베타 I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_bt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(ln_bt) * _betacf(a, b, x) / a
    return 1.0 - math.exp(ln_bt) * _betacf(b, a, 1.0 - x) / b


def _t_cdf(t: float, df: float) -> float:
    x = df / (df + t * t)
    tail = 0.5 * _betainc(df / 2.0, 0.5, x)       # P(T > |t|)
    return 1.0 - tail if t > 0 else tail


def t_critical(n_months: int, alpha: float = ALPHA_ONE_SIDED) -> Optional[float]:
    """t 분포 한쪽 alpha 기준값 · 자유도 = 사건이 있는 달 수 − 1 (Fable 조건 가).

    달 수가 2 미만이면 None. scipy 가 있으면 scipy.stats.t.ppf, 없으면 아래 직접 구현(이분법)을 쓴다.
    """
    df = n_months - 1
    if df < 1:
        return None
    try:
        from scipy.stats import t as _scipy_t   # type: ignore[import-not-found]

        return float(_scipy_t.ppf(1.0 - alpha, df))
    except ImportError:
        return t_critical_pure(n_months, alpha)


def t_critical_pure(n_months: int, alpha: float = ALPHA_ONE_SIDED) -> Optional[float]:
    df = n_months - 1
    if df < 1:
        return None
    lo, hi = 0.0, 1000.0
    target = 1.0 - alpha
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if _t_cdf(mid, df) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ═══ 기초 통계 ═════════════════════════════════════════════
def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def trimmed_mean(xs: Sequence[float], fraction: float = TRIM_FRACTION) -> float:
    """위아래 fraction 씩 잘라 낸 평균 (권고 나) · 잘라 낼 개수는 내림."""
    s = sorted(xs)
    k = int(len(s) * fraction)
    core = s[k:len(s) - k] if len(s) - 2 * k > 0 else s
    return _mean(core)


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def clustered_t(excess_by_month: dict[str, list[float]]) -> Optional[float]:
    """진입 월 단위로 묶은 표준오차의 t (평균 초과수익 ÷ 표준오차) · 묶음 2개 미만이면 None."""
    groups = list(excess_by_month.values())
    g = len(groups)
    allx = [x for grp in groups for x in grp]
    n = len(allx)
    if g < 2 or n < 2:
        return None
    m = _mean(allx)
    ss = sum(sum(x - m for x in grp) ** 2 for grp in groups)
    var = ss * (g / (g - 1)) / (n * n)
    if var <= 0:
        return None
    return m / math.sqrt(var)


def calendar_time_t(excess_by_month: dict[str, list[float]]) -> Optional[float]:
    """달력 시간 포트폴리오 t · 그달 진입 사건들의 평균 초과수익을 한 표본으로 본다."""
    series = [_mean(v) for v in excess_by_month.values() if v]
    if len(series) < 2:
        return None
    m = _mean(series)
    sd = math.sqrt(sum((x - m) ** 2 for x in series) / (len(series) - 1))
    if sd == 0:
        return None
    return m / (sd / math.sqrt(len(series)))


def newey_west_t(excess_by_month: dict[str, list[float]]) -> Optional[float]:
    """참고 줄 · 달력 시간 월별 평균에 이웃 달 상관 한 칸(Newey-West 1)을 반영한 t (Fable 권고 ㄷ)."""
    keys = sorted(excess_by_month)
    series = [_mean(excess_by_month[k]) for k in keys if excess_by_month[k]]
    n = len(series)
    if n < 3:
        return None
    m = _mean(series)
    dev = [x - m for x in series]
    g0 = sum(d * d for d in dev) / n
    g1 = sum(dev[i] * dev[i - 1] for i in range(1, n)) / n
    var = (g0 + 2.0 * 0.5 * g1) / n          # Bartlett 가중 1/2
    if var <= 0:
        return None
    return m / math.sqrt(var)


# ═══ 성적 한 줄 ════════════════════════════════════════════
def compute_outcome(
    entry_price: Optional[float], exit_price: Optional[float],
    index_entry: Optional[float], index_exit: Optional[float],
    cost_pct: float, status: str = "ok",
) -> dict[str, Any]:
    """진입 · 청산 가격으로 수익률 · 지수 수익률 · 초과(비용 뒤)를 계산한다. 가격이 없으면 「가격 없음」."""
    if not entry_price or not exit_price or not index_entry or not index_exit or entry_price <= 0 or index_entry <= 0:
        return {"status": "no_price", "return_pct": None, "index_return_pct": None, "excess_pct": None,
                "cost_pct": cost_pct}
    ret = (exit_price / entry_price - 1.0) * 100.0
    idx = (index_exit / index_entry - 1.0) * 100.0
    return {"status": status, "return_pct": ret, "index_return_pct": idx,
            "excess_pct": ret - idx - cost_pct, "cost_pct": cost_pct}


def next_trading_day(d: date, trading_days: Sequence[date]) -> Optional[date]:
    """d 다음 거래일 (d 자신은 포함하지 않음) · trading_days 는 오름차순."""
    for t in trading_days:
        if t > d:
            return t
    return None


def build_outcome(
    establish_date: date, horizon: int, bars: dict[date, dict[str, float]],
    index_bars: dict[date, dict[str, float]], cost_pct: float,
) -> dict[str, Any]:
    """성립 날짜 → 다음 거래일 시가 진입 · 진입일로부터 horizon 번째 거래일 종가 청산 (기획서 3-4 · 3-5).

    bars · index_bars = {날짜: {"open":, "close":}} · 지수 거래일이 달력이다.
    종목 일봉이 청산일 전에 끊기면 마지막 종가로 청산하고 status 를 delisted 로 둔다 (표본에서 빼지 않음).
    종목 일봉이 진입일에 없으면 「가격 없음」.
    """
    days = sorted(index_bars)
    entry = next_trading_day(establish_date, days)
    if entry is None:
        return {"status": "no_price", "entry_date": None, "exit_date": None, "return_pct": None,
                "index_return_pct": None, "excess_pct": None, "cost_pct": cost_pct}
    idx_after = [d for d in days if d >= entry]
    if len(idx_after) <= horizon:
        return {"status": "no_price", "entry_date": entry, "exit_date": None, "return_pct": None,
                "index_return_pct": None, "excess_pct": None, "cost_pct": cost_pct}
    exit_day = idx_after[horizon]
    if entry not in bars:
        return {"status": "no_price", "entry_date": entry, "exit_date": exit_day, "return_pct": None,
                "index_return_pct": None, "excess_pct": None, "cost_pct": cost_pct}
    status = "ok"
    if exit_day in bars:
        exit_price = bars[exit_day]["close"]
    else:
        last_day = max(d for d in bars if d <= exit_day)
        exit_price = bars[last_day]["close"]
        status = "delisted"
    out = compute_outcome(bars[entry]["open"], exit_price,
                          index_bars[entry]["open"], index_bars[exit_day]["close"], cost_pct, status)
    out.update({"entry_date": entry, "exit_date": exit_day,
                "entry_price": bars[entry]["open"], "exit_price": exit_price})
    return out


# ═══ 유형 성적표 · 「검증됨」 판정 ═════════════════════════
def summarize_type(rows: Sequence[dict[str, Any]], total_events: int, judge_start: date = JUDGE_START) -> dict[str, Any]:
    """한 유형의 판정 기간 성적표와 4-4 기준 판정.

    rows 한 줄 = {"entry_date": date, "excess_pct": float|None, "status": str} · 지어낸 자료로만 시험한다.
    total_events = 전체 사건 수 (규칙 기간 포함).
    """
    judge = [r for r in rows if r["entry_date"] >= judge_start]
    priced = [r for r in judge if r["status"] in ("ok", "delisted", "halted") and r["excess_pct"] is not None]
    unpriced = [r for r in judge if r not in priced]
    n_judge = len(judge)
    no_price_ratio = (len(unpriced) / n_judge) if n_judge else None

    by_month: dict[str, list[float]] = defaultdict(list)
    for r in priced:
        by_month[month_key(r["entry_date"])].append(r["excess_pct"])
    xs = [r["excess_pct"] for r in priced]
    months = len(by_month)

    t_cluster = clustered_t(by_month)
    t_cal = calendar_time_t(by_month)
    t_used = min(t for t in (t_cluster, t_cal) if t is not None) if (t_cluster is not None and t_cal is not None) else None
    crit = t_critical(months)          # 달 수에서 구한다 (상수로 박지 않음 · 12개월 미만은 아래에서 따로 탈락)

    # 보수 줄: 가격 없음 · 거래정지 청산을 −100% 로 넣어 다시 계산한 평균
    conservative = [r["excess_pct"] for r in priced if r["status"] != "halted"] + [-100.0] * (
        len(unpriced) + sum(1 for r in priced if r["status"] == "halted"))
    cons_mean = _mean(conservative) if conservative else None

    reasons = []
    if total_events < MIN_EVENTS_ALL:
        reasons.append("전체 사건 부족")
    if n_judge < MIN_EVENTS_JUDGE:
        reasons.append("판정 기간 사건 부족")
    mean_x = _mean(xs) if xs else None
    if mean_x is None or mean_x <= 0:
        reasons.append("평균 초과수익 0 이하")
    if months < MIN_MONTHS:
        reasons.append("사건이 있는 달 부족")
    if t_used is None or crit is None or t_used < crit:
        reasons.append("t 값이 기준값 미만")
    if no_price_ratio is None or no_price_ratio > MAX_NO_PRICE_RATIO:
        reasons.append("가격 없음 비율 초과")
    if cons_mean is None or cons_mean <= 0:
        reasons.append("보수 줄 평균 0 이하")

    return {
        "n_judge": n_judge, "n_priced": len(priced), "total_events": total_events, "months": months,
        "mean_pct": mean_x, "median_pct": _median(xs) if xs else None,
        "trimmed_mean_pct": trimmed_mean(xs) if xs else None,
        "win_rate": (sum(1 for x in xs if x > 0) / len(xs)) if xs else None,
        "t_cluster": t_cluster, "t_calendar": t_cal, "t_used": t_used, "t_critical": crit,
        "t_newey_west": newey_west_t(by_month),
        "no_price_ratio": no_price_ratio, "conservative_mean_pct": cons_mean,
        "verified": not reasons, "fail_reasons": reasons,
    }
