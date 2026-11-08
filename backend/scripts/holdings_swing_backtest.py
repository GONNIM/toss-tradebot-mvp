"""보유 종목 스윙 도움 1단계 백테스트 (계획 docs/plans/holdings-swing/2026-11-08-plan.md 3·4절).

- 자료는 CSV 로만 읽는다 (국내 = 운영 krx_daily_candles 읽기 전용 덤프, 미국 = yfinance Close).
- 이 파일은 DB·토스 API·.env 를 부르지 않는다. 종가만 쓴다.
- 규칙 값은 계획 3절 그대로다. 계획에 없는 값은 상수 옆에 「PO 값」으로 표시했다.

사용: python backend/scripts/holdings_swing_backtest.py --krx krx.csv --us us.csv --json out.json --tables tables.md
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# ── 비용 (계획 4절 · 추정 · 국내 거래세는 연도 상관없이 상한 0.20% 일괄) ──
COSTS = {
    "KR": {"buy": 0.00015, "sell": 0.00015 + 0.0020, "fx": 0.0},
    "US": {"buy": 0.001, "sell": 0.001, "fx": 0.001},  # fx 는 처음 매수·마지막 청산(통화가 바뀌는 거래)에만
}

HOLD_DAYS = 60
FIRST_START = 59  # 60일 평균이 처음 계산되는 날
CAP_RATIO = 0.66  # A 상한: 처음 투입금의 +66% (㉦②)
ADD_FRACTION = 1 / 3
MAX_ADDS_PER_TREND = 2
ADD_GAP_DAYS = 5  # PO 값: 계획에 없음. 같은 신호가 연달아 나와 추가 매수가 붙지 않게 두 번 사이 5거래일
WATERING_LOSS = -0.10  # PO 값: 물타기 참고 결과의 조건(평단 대비 -10% 이하 · 처음 수량 1/3 · 2번 · 같은 상한)
A_PNL = 0.05
B1_MIN_DROP = 0.05
B1_SIGMA_MULT = 1.5
B1_DEADLINE = 20
D_MIN_DD = 0.08
D_SIGMA_MULT = 2.5
B2_CONSEC = 2

RULE_SETS = {
    "A_L": {"A_L"},  # 장기: 추가만 (손절 상향 없음)
    "A_S": {"A_S"},  # 단기: 추가 + 추가 뒤 손절 상향
    "B1": {"B1"},
    "B2": {"B2"},
    "D": {"D"},
    "W": {"W"},  # 물타기 (참고)
    "S1": {"A_S", "B1", "D"},  # 단기 합본 (참고)
    "S2": {"A_S", "B2", "D"},  # 단기 합본 (참고)
}
RESERVE_RULES = {"A_L", "A_S", "W"}  # 추가 매수용 현금을 따로 두는 규칙


def uses_reserve(rules) -> bool:
    return bool(set(rules) & RESERVE_RULES)


@dataclass
class Indicators:
    c: np.ndarray
    ma20: np.ndarray
    ma60: np.ndarray
    sig20: np.ndarray  # 최근 20거래일 일간 수익률 표준편차(표본)


def indicators(closes) -> Indicators:
    c = np.asarray(closes, dtype=float)
    s = pd.Series(c)
    return Indicators(
        c=c,
        ma20=s.rolling(20).mean().to_numpy(),
        ma60=s.rolling(60).mean().to_numpy(),
        sig20=s.pct_change().rolling(20).std().to_numpy(),
    )


@dataclass
class SimResult:
    ret: float
    mdd: float
    fired: set = field(default_factory=set)
    events: list = field(default_factory=list)  # (index, kind)
    total_in: float = 1.0
    add_spent: float = 0.0
    qty_end: float = 0.0
    qty0: float = 0.0


def simulate(ind: Indicators, t0: int, market: str, rules: set, hold_days: int = HOLD_DAYS, reserve: bool | None = None) -> SimResult:
    """t0 종가에 매수해 hold_days 뒤 종가에 전량 청산. 신호는 종가 판정 · 다음 거래일 종가 체결.
    reserve=True 면 추가 매수용 현금(처음 투입금의 66%)을 따로 두고 총투입에 넣는다 (rules 가 비어도 '그대로' 쪽 비교용)."""
    cost = COSTS[market]
    fx, buyf, sellf = cost["fx"], cost["buy"], cost["sell"]
    c = ind.c
    end = t0 + hold_days
    if reserve is None:
        reserve = uses_reserve(rules)
    total_in = 1.0 + (CAP_RATIO if reserve else 0.0)

    outlay0 = 1.0 * (1 - fx)
    qty0 = outlay0 / (c[t0] * (1 + buyf))
    qty, basis = qty0, outlay0
    cash = (total_in - 1.0) * (1 - fx)
    cap_amount = CAP_RATIO * outlay0
    add_spent = 0.0
    peak = c[t0]
    adds_trend = 0
    adds_w = 0
    last_add = -10**9
    stop_up = False
    waiting = None
    waiting_thr = 0.0
    above60 = 0
    pending = None
    fired: set = set()
    events: list = []
    run_peak = -math.inf
    mdd = 0.0

    for i in range(t0, end + 1):
        px = c[i]
        if i > t0 and pending is not None:
            kind = pending
            pending = None
            if kind in ("A", "W") and qty > 0:
                unit = px * (1 + buyf)
                q = min(qty0 * ADD_FRACTION, (cap_amount - add_spent) / unit, cash / unit)
                if q > 1e-12:
                    spend = q * unit
                    qty += q
                    basis += spend
                    cash -= spend
                    add_spent += spend
                    last_add = i
                    if kind == "A":
                        adds_trend += 1
                        if "A_S" in rules:
                            stop_up = True
                    else:
                        adds_w += 1
                    fired.add(kind)
                    events.append((i, kind))
            elif kind == "B" and qty > 0:
                q = qty / 3
                basis -= basis * (q / qty)
                qty -= q
                cash += q * px * (1 - sellf)
                waiting = {"qty": q, "price": px, "exec": i, "thr": waiting_thr}
                above60 = 0
                fired.add("B")
                events.append((i, "B"))
            elif kind == "REBUY" and waiting is not None:
                unit = px * (1 + buyf)
                q = min(waiting["qty"], cash / unit)
                if q > 1e-12:
                    qty += q
                    basis += q * unit
                    cash -= q * unit
                waiting = None
                events.append((i, "REBUY"))
            elif kind in ("D", "STOP") and qty > 0:
                cash += qty * px * (1 - sellf)
                qty, basis = 0.0, 0.0
                waiting = None
                if kind == "D":
                    fired.add("D")
                events.append((i, kind))
        peak = max(peak, px)
        value = qty * px + cash
        run_peak = max(run_peak, value)
        mdd = min(mdd, value / run_peak - 1)
        if waiting is not None and i > waiting["exec"]:
            above60 = above60 + 1 if (not np.isnan(ind.ma60[i]) and px > ind.ma60[i]) else 0

        if i >= end or (qty <= 0 and waiting is None):
            continue
        m20, m60, sg = ind.ma20[i], ind.ma60[i], ind.sig20[i]
        if np.isnan(m20) or np.isnan(m60) or np.isnan(sg):
            continue
        if m20 < m60:
            adds_trend = 0
        if qty <= 0:
            continue
        avg = basis / qty
        pnl = px / avg - 1

        if "D" in rules and pnl > 0 and (peak - px) / peak >= max(D_MIN_DD, D_SIGMA_MULT * sg) and px < m20:
            pending = "D"
        elif stop_up and px < avg:
            pending = "STOP"
        elif waiting is not None:
            if "B1" in rules:
                if i > waiting["exec"] + B1_DEADLINE:
                    waiting = None
                elif i > waiting["exec"] and px <= waiting["price"] * (1 - waiting["thr"]):
                    pending = "REBUY"
            elif "B2" in rules and i > waiting["exec"]:
                if above60 >= B2_CONSEC or m20 > m60:
                    pending = "REBUY"
        elif ("B1" in rules or "B2" in rules) and pnl < 0 and px < m60 and px >= m20:
            pending = "B"
            waiting_thr = max(B1_MIN_DROP, B1_SIGMA_MULT * sg)
        elif (
            ("A_L" in rules or "A_S" in rules)
            and pnl >= A_PNL
            and px > m20 > m60
            and (px / m20 - 1) <= sg
            and adds_trend < MAX_ADDS_PER_TREND
            and add_spent < cap_amount - 1e-12
            and i - last_add >= ADD_GAP_DAYS
        ):
            pending = "A"
        elif "W" in rules and pnl <= WATERING_LOSS and adds_w < MAX_ADDS_PER_TREND and add_spent < cap_amount - 1e-12 and i - last_add >= ADD_GAP_DAYS:
            pending = "W"

    final = (qty * c[end] * (1 - sellf) + cash) * (1 - fx)
    return SimResult(ret=final / total_in - 1, mdd=mdd, fired=fired, events=events, total_in=total_in, add_spent=add_spent, qty_end=qty, qty0=qty0)


def breakeven_vs_d(ind: Indicators, t0: int, market: str, hold_days: int = HOLD_DAYS):
    """비교 ②: 평단 아래 5% 이상 내려갔다가 (매도 비용 반영) 평단을 회복한 창에서 본전 매도 vs D 로 보내기.
    해당하지 않으면 None. 반환 (본전 매도 수익률, D 수익률)."""
    cost = COSTS[market]
    fx, buyf, sellf = cost["fx"], cost["buy"], cost["sell"]
    c = ind.c
    end = t0 + hold_days
    avg = c[t0] * (1 + buyf)
    qty = (1 - fx) / avg
    dipped = False
    d = None
    for i in range(t0 + 1, end):  # 신호일 d ≤ end-1 (다음 날 체결이 창 안)
        if c[i] <= avg * 0.95:
            dipped = True
        elif dipped and c[i] * (1 - sellf) >= avg:
            d = i
            break
    if d is None:
        return None
    x = qty * c[d + 1] * (1 - sellf) * (1 - fx) - 1.0
    peak = c[t0:d + 1].max()
    sold_at = end
    for j in range(d, end):
        peak = max(peak, c[j])
        m20, sg = ind.ma20[j], ind.sig20[j]
        if np.isnan(m20) or np.isnan(sg):
            continue
        if c[j] / avg - 1 > 0 and (peak - c[j]) / peak >= max(D_MIN_DD, D_SIGMA_MULT * sg) and c[j] < m20:
            sold_at = j + 1
            break
    y = qty * c[sold_at] * (1 - sellf) * (1 - fx) - 1.0
    return x, y


# ── 표본 만들기 ──
def load_prices(path: Path, drop=()) -> dict:
    df = pd.read_csv(path, dtype={"ticker": str})
    out = {}
    for t, g in df.groupby("ticker"):
        if t in drop:
            continue
        g = g.sort_values("date").dropna(subset=["close"])
        out[t] = (g["date"].tolist(), g["close"].to_numpy(dtype=float))
    return out


def window_starts(n: int, step: int, hold_days: int = HOLD_DAYS):
    return range(FIRST_START, n - hold_days, step)


def run_market(prices: dict, market: str, step: int):
    """종목·창마다 모든 규칙 변형과 그대로 들고 있기를 돌린다. 행 = dict."""
    rows = []
    for t, (dates, closes) in prices.items():
        ind = indicators(closes)
        for t0 in window_starts(len(closes), step):
            h_plain = simulate(ind, t0, market, set(), reserve=False)
            h_res = simulate(ind, t0, market, set(), reserve=True)
            row = {"ticker": t, "start": dates[t0], "i": t0, "hold_plain": h_plain, "hold_res": h_res}
            for name, rs in RULE_SETS.items():
                row[name] = simulate(ind, t0, market, rs)
            row["be"] = breakeven_vs_d(ind, t0, market)
            rows.append(row)
    return rows


def hold_of(row, name):
    """그대로 쪽. 추가 현금을 쓰는 규칙은 같은 총투입(현금 이자 0)의 그대로 쪽과 비교한다."""
    return row["hold_res"] if uses_reserve(RULE_SETS[name]) else row["hold_plain"]


def bootstrap_mean_ci(by_ticker: dict, n_boot: int = 2000, seed: int = 20261108):
    """종목 블록 부트스트랩: 종목을 복원 추출해 창 평균을 다시 구한다. 90% 구간."""
    keys = list(by_ticker)
    sums = np.array([np.sum(by_ticker[k]) for k in keys])
    cnts = np.array([len(by_ticker[k]) for k in keys], dtype=float)
    if len(keys) == 0 or cnts.sum() == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(keys), size=(n_boot, len(keys)))
    num, den = sums[idx].sum(axis=1), cnts[idx].sum(axis=1)
    ok = den > 0
    means = num[ok] / den[ok]
    return (float(np.percentile(means, 5)), float(np.percentile(means, 95)))


def split_rows(rows, cut_date):
    return [r for r in rows if r["start"] < cut_date], [r for r in rows if r["start"] >= cut_date]


def stats(rows, name, n_boot=2000):
    sel = [r for r in rows if r[name].fired]
    if not sel:
        return {"n": 0, "n_all": len(rows), "fire_rate": 0.0}
    rr = np.array([r[name].ret for r in sel])
    hh = np.array([hold_of(r, name).ret for r in sel])
    diff = rr - hh
    by_t: dict = {}
    for r, d in zip(sel, diff):
        by_t.setdefault(r["ticker"], []).append(d)
    lo, hi = bootstrap_mean_ci(by_t, n_boot)
    return {
        "n": len(sel),
        "n_all": len(rows),
        "fire_rate": len(sel) / len(rows),
        "mean_diff": float(diff.mean()),
        "median_diff": float(np.median(diff)),
        "ci_lo": lo,
        "ci_hi": hi,
        "p5_rule": float(np.percentile(rr, 5)),
        "p5_hold": float(np.percentile(hh, 5)),
        "p5_diff": float(np.percentile(rr, 5) - np.percentile(hh, 5)),
        "mdd_rule_mean": float(np.mean([r[name].mdd for r in sel])),
        "mdd_hold_mean": float(np.mean([hold_of(r, name).mdd for r in sel])),
        "mdd_rule_worst": float(np.min([r[name].mdd for r in sel])),
        "mdd_hold_worst": float(np.min([hold_of(r, name).mdd for r in sel])),
    }


EXTREME_HOLD = 1.0  # 참고용: 그대로 들고 있기 수익이 +100% 를 넘은 창


def trimmed(rows, name):
    """극단 창(그대로 +100% 초과)을 뺀 평균 차이와 뺀 창 수. 판정에는 쓰지 않는 참고 값."""
    sel = [r for r in rows if r[name].fired]
    keep = [r for r in sel if hold_of(r, name).ret <= EXTREME_HOLD]
    if not keep:
        return {"n": 0, "dropped": len(sel)}
    return {"n": len(keep), "dropped": len(sel) - len(keep), "mean_diff": float(np.mean([r[name].ret - hold_of(r, name).ret for r in keep]))}


def verdict(ins: dict, out: dict, n_total_fired: int):
    """통과 기준 (가)~(라) + 표본 ≥ 200 (안+밖 비겹침 발동 창 합계). (가)~(다)는 표본 안, (라)는 표본 밖."""
    if ins.get("n", 0) == 0:
        return {"ga": None, "na": None, "da": None, "ra": None, "n_ok": False, "pass": False}
    ga = ins["mean_diff"] >= 0
    na = ins["ci_lo"] > -0.01
    da = ins["p5_diff"] >= -0.02
    ra = out.get("n", 0) > 0 and out["mean_diff"] >= 0
    n_ok = n_total_fired >= 200
    return {"ga": bool(ga), "na": bool(na), "da": bool(da), "ra": bool(ra), "n_ok": n_ok, "pass": bool(ga and na and da and ra and n_ok)}


def compare_b1_b2(ins_rows, out_rows):
    """미리 등록한 비교 ①: 표본 안에서 평균 차이가 큰 쪽을 고르고 표본 밖에서 한 번 판정."""
    def mean_vs_hold(rows, name):
        sel = [r for r in rows if r[name].fired]
        return (float(np.mean([r[name].ret - r["hold_plain"].ret for r in sel])), len(sel)) if sel else (float("nan"), 0)

    m1, n1 = mean_vs_hold(ins_rows, "B1")
    m2, _ = mean_vs_hold(ins_rows, "B2")
    pick = "B1" if (m1 >= m2 or math.isnan(m2)) else "B2"
    other = "B2" if pick == "B1" else "B1"
    sel = [r for r in out_rows if r[pick].fired]
    res = {"in_B1": m1, "in_B2": m2, "n_in": n1, "pick": pick, "n_out": len(sel)}
    if sel:
        res["out_pick_vs_hold"] = float(np.mean([r[pick].ret - r["hold_plain"].ret for r in sel]))
        res["out_pick_vs_other"] = float(np.mean([r[pick].ret - r[other].ret for r in sel]))
        res["keep"] = bool(res["out_pick_vs_other"] >= 0)
    return res


def compare_breakeven(rows):
    sel = [r["be"] for r in rows if r["be"] is not None]
    if not sel:
        return {"n": 0}
    x = np.array([s[0] for s in sel])
    y = np.array([s[1] for s in sel])
    d = y - x
    res = {"n": len(sel), "mean_x": float(x.mean()), "mean_y": float(y.mean()), "mean_diff": float(d.mean()), "median_diff": float(np.median(d)), "p5_x": float(np.percentile(x, 5)), "p5_y": float(np.percentile(y, 5))}
    res["verdict"] = "판정 없이 사실만 (표본 100 미만)" if len(sel) < 100 else ("D 쪽이 낫거나 같음" if res["mean_diff"] >= 0 else "본전 매도 쪽이 나음")
    return res


def drawdown_frequency(prices: dict, threshold: float = 0.08):
    """달력 연도마다 그 해 안에서 고점 대비 8% 이상 하락이 한 번이라도 있었던 종목 비율."""
    per_year: dict = {}
    for _, (dates, closes) in prices.items():
        s = pd.Series(closes, index=pd.to_datetime(dates))
        for y, g in s.groupby(s.index.year):
            if len(g) < 20:
                continue
            per_year.setdefault(int(y), []).append(bool((g / g.cummax() - 1).min() <= -threshold))
    return {y: {"n": len(v), "share": float(np.mean(v))} for y, v in sorted(per_year.items())}


def jump_days(prices: dict, limit: float = 0.30):
    return sum(int((np.abs(pd.Series(cl).pct_change().dropna().to_numpy()) > limit).sum()) for _, (_, cl) in prices.items())


def c_fact_rate(prices: dict):
    """C 손절 사실: 종가 < 평단×0.85 이고 종가 < 60일 평균인 창 비율 (평단 = 창 시작 종가 · 비겹침)."""
    hit = tot = 0
    for _, (_, closes) in prices.items():
        ind = indicators(closes)
        for t0 in window_starts(len(closes), HOLD_DAYS):
            tot += 1
            if any(ind.c[i] < ind.c[t0] * 0.85 and ind.c[i] < ind.ma60[i] for i in range(t0 + 1, t0 + HOLD_DAYS)):
                hit += 1
    return {"n": tot, "hit": hit, "rate": hit / tot if tot else 0.0}


def run_all(krx_csv: Path, us_csv: Path, n_boot: int = 2000):
    markets = {
        "KR": load_prices(krx_csv),
        "US": load_prices(us_csv, drop=("GOOG",)),  # GOOG·GOOGL 은 같은 회사 · GOOGL 만 씀
    }
    result: dict = {"markets": {}}
    for m, prices in markets.items():
        all_dates = sorted({d for dates, _ in prices.values() for d in dates})
        cut = all_dates[int(len(all_dates) * 2 / 3)]
        res = {"n_tickers": len(prices), "cut": cut, "date_min": all_dates[0], "date_max": all_dates[-1], "jump_days": jump_days(prices), "variants": {}}
        rows = run_market(prices, m, step=HOLD_DAYS)
        rows10 = run_market(prices, m, step=10)
        ins, out = split_rows(rows, cut)
        res["n_windows"] = {"all": len(rows), "in": len(ins), "out": len(out), "step10": len(rows10)}
        for name in RULE_SETS:
            si, so, sa = stats(ins, name, n_boot), stats(out, name, n_boot), stats(rows, name, n_boot)
            res["variants"][name] = {"trim_in": trimmed(ins, name), "trim_out": trimmed(out, name), "in": si, "out": so, "all": sa, "step10": stats(rows10, name, n_boot=200), "verdict": verdict(si, so, sa.get("n", 0))}
        res["cmp1"] = compare_b1_b2(ins, out)
        res["cmp2"] = compare_breakeven(rows)
        res["cmp2_step10"] = compare_breakeven(rows10)
        res["c_rate"] = c_fact_rate(prices)
        res["dd_freq"] = drawdown_frequency(prices)
        result["markets"][m] = res
    return result


# ── 보고서 표 ──
NAMES = {
    "A_L": "A 흑자 추가 (장기 · 추가만)",
    "A_S": "A 흑자 추가 (단기 · 추가+손절 상향)",
    "B1": "B 일부 매도 + B1 재매수",
    "B2": "B 일부 매도 + B2 재매수",
    "D": "D 이익 보호 (전량)",
    "W": "물타기 (참고 · 판정 없음)",
    "S1": "단기 합본 A+B1+D (참고)",
    "S2": "단기 합본 A+B2+D (참고)",
}


def _nan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def pp(x):
    return "-" if _nan(x) else f"{x * 100:+.2f}%p"


def pc(x):
    return "-" if _nan(x) else f"{x * 100:.1f}%"


def mark(v):
    return "-" if v is None else ("O" if v else "X")


def render_tables(result):
    lines = []
    for m, label in (("KR", "국내 (krx_daily_candles 49종목)"), ("US", "미국 (S&P 100 고정 명단)")):
        r = result["markets"][m]
        lines += [f"### {label}", "", f"- 종목 {r['n_tickers']}개 · 기간 {r['date_min']}~{r['date_max']} · 표본 안/밖 경계 {r['cut']} · 비겹침 창 {r['n_windows']['all']}개 (안 {r['n_windows']['in']} · 밖 {r['n_windows']['out']}) · 10일 간격 참고 창 {r['n_windows']['step10']}개 · 하루 ±30% 넘는 종가 변동 {r['jump_days']}일", ""]
        lines += ["| 규칙 | 구분 | 표본 수 | 발동률 | 평균 차이 | 중앙값 차이 | 90% 구간 | 하위 5% 차이 | 평균 최대 낙폭 (규칙/그대로) | 최악 낙폭 (규칙/그대로) |", "|---|---|---|---|---|---|---|---|---|---|"]
        for name in RULE_SETS:
            v = r["variants"][name]
            for key, lab in (("in", "표본 안"), ("out", "표본 밖"), ("step10", "10일 간격 참고")):
                s = v[key]
                if s["n"] == 0:
                    lines.append(f"| {NAMES[name]} | {lab} | 0 | {pc(s['fire_rate'])} | - | - | - | - | - | - |")
                    continue
                lines.append(f"| {NAMES[name]} | {lab} | {s['n']} | {pc(s['fire_rate'])} | {pp(s['mean_diff'])} | {pp(s['median_diff'])} | {pp(s['ci_lo'])} ~ {pp(s['ci_hi'])} | {pp(s['p5_diff'])} | {pc(s['mdd_rule_mean'])} / {pc(s['mdd_hold_mean'])} | {pc(s['mdd_rule_worst'])} / {pc(s['mdd_hold_worst'])} |")
        lines += [""]
    return lines


def final_label(name, vd):
    if name in ("S1", "S2"):
        return "참고(판정 안 함)"
    if vd["pass"]:
        return "통과"
    if vd["ga"] and vd["na"] and vd["da"] and vd["ra"] and not vd["n_ok"]:
        return "미통과 (표본 부족)"
    return "미통과"


def render_verdicts(result):
    lines = ["| 시장 | 규칙 | (가) 평균≥0 | (나) 90%구간 하한>-1%p | (다) 하위5% 악화≤2%p | (라) 표본 밖 (가) | 표본≥200 (안+밖 발동 창) | 판정 |", "|---|---|---|---|---|---|---|---|"]
    for m in ("KR", "US"):
        for name in RULE_SETS:
            if name == "W":
                continue
            v = result["markets"][m]["variants"][name]
            vd = v["verdict"]
            lines.append(f"| {m} | {NAMES[name]} | {mark(vd['ga'])} | {mark(vd['na'])} | {mark(vd['da'])} | {mark(vd['ra'])} | {v['all'].get('n', 0)} {'O' if vd['n_ok'] else 'X'} | {final_label(name, vd)} |")
    return lines


def render_cmp(result):
    lines = ["### 비교 ① B1 vs B2", "", "| 시장 | 표본 안 평균 차이 (B1 / B2, 그대로 대비) | 표본 안에서 고른 쪽 | 표본 밖 창 수 | 표본 밖: 고른 쪽 − 그대로 | 표본 밖: 고른 쪽 − 다른 쪽 | 판정 |", "|---|---|---|---|---|---|---|"]
    for m in ("KR", "US"):
        c = result["markets"][m]["cmp1"]
        j = ("선택 유지 (고른 쪽이 표본 밖에서도 같거나 나음)" if c["keep"] else "선택 뒤집힘 (표본 밖에서는 다른 쪽이 나음)") if "keep" in c else "표본 밖 없음"
        lines.append(f"| {m} | {pp(c['in_B1'])} / {pp(c['in_B2'])} (안 {c['n_in']}창) | {c['pick']} | {c['n_out']} | {pp(c.get('out_pick_vs_hold'))} | {pp(c.get('out_pick_vs_other'))} | {j} |")
    lines += ["", "### 비교 ② 본전 매도 vs D 로 보내기", "", "| 시장 | 적용 창 수 (비겹침) | 본전 매도 평균 | D 평균 | 차이 (D − 본전) 평균 | 중앙값 | 하위 5% (본전/D) | 판정 | 10일 간격 참고 창 수 |", "|---|---|---|---|---|---|---|---|---|"]
    for m in ("KR", "US"):
        c = result["markets"][m]["cmp2"]
        c10 = result["markets"][m]["cmp2_step10"]["n"]
        if c["n"] == 0:
            lines.append(f"| {m} | 0 | - | - | - | - | - | 해당 창 없음 | {c10} |")
        else:
            lines.append(f"| {m} | {c['n']} | {pc(c['mean_x'])} | {pc(c['mean_y'])} | {pp(c['mean_diff'])} | {pp(c['median_diff'])} | {pc(c['p5_x'])} / {pc(c['p5_y'])} | {c['verdict']} | {c10} |")
    return lines


def render_trim(result):
    lines = ["| 시장 | 규칙 | 표본 안 평균 차이 (뺀 창 수) | 표본 밖 평균 차이 (뺀 창 수) |", "|---|---|---|---|"]
    for m in ("KR", "US"):
        for name in RULE_SETS:
            v = result["markets"][m]["variants"][name]
            a, b = v["trim_in"], v["trim_out"]
            lines.append(f"| {m} | {NAMES[name]} | {pp(a.get('mean_diff'))} ({a['dropped']}) | {pp(b.get('mean_diff'))} ({b['dropped']}) |")
    return lines


def render_misc(result):
    lines = ["| 시장 | 연도 | 종목 수 | 그 해 안에서 고점 대비 8% 이상 하락이 있었던 종목 비율 |", "|---|---|---|---|"]
    for m in ("KR", "US"):
        for y, v in result["markets"][m]["dd_freq"].items():
            lines.append(f"| {m} | {y} | {v['n']} | {pc(v['share'])} |")
    k, u = result["markets"]["KR"]["c_rate"], result["markets"]["US"]["c_rate"]
    lines += ["", f"- C 손절 사실(종가 < 창 시작가×0.85 이고 < 60일 평균) 발동 창: 국내 {k['hit']}/{k['n']} ({pc(k['rate'])}) · 미국 {u['hit']}/{u['n']} ({pc(u['rate'])}). 사실 표시라 수익 비교는 없음."]
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--krx", required=True, type=Path)
    ap.add_argument("--us", required=True, type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--tables", type=Path, help="표 조각을 쓸 markdown 파일")
    ap.add_argument("--boot", type=int, default=2000)
    a = ap.parse_args()
    result = run_all(a.krx, a.us, a.boot)
    if a.json:
        a.json.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    if a.tables:
        parts = ["## 규칙·시장별 결과", ""] + render_tables(result) + ["## 통과 판정", ""] + render_verdicts(result) + ["", "## 비교 2건", ""] + render_cmp(result) + ["", "## 극단 창 제외 참고 (판정에 쓰지 않음)", ""] + render_trim(result) + ["", "## 대형주 하락 빈도 · C 사실", ""] + render_misc(result)
        a.tables.write_text("\n".join(parts) + "\n")


if __name__ == "__main__":
    main()
