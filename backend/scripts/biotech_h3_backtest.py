"""H3 백테스트 엔진 (B97 · 2026-09-06).

사양 (README §3-5 · 사후 조정 금지):
- 진입: D+1 종가 (adj_close) · 미래 참조 배제
- 창: D+1~D+30 (단기) · D+1~D+180 (장기)
- benchmark: XBI 주 · IWM 참고
- net = 왕복 거래비용 1.0% 차감 · 민감도 0.5/2.0/5.0% 병기
- bootstrap 10,000회 · seed 고정 · block bootstrap (종목 클러스터)
- 버킷: mcap [$50M,$300M)/[$300M,$1B)/[$1B,$5B] × subsector (SIC 2834/2836)
- mcap = companyfacts 발행주식수 × 원시 종가 (filing 시점)
- 이벤트 적격: [D-30, D+180] 가격 실존 · 미충족 제외

입력:
- h3_events CSV (event_id · target_cik · ticker · event_type · event_date · accession · institution)
- h3_prices_merged (ticker · date · adj_close · close · ...)
- benchmarks (XBI · IWM · adj_close)
- 원장 (mcap · subsector · form25_date)

출력:
- backend/data/h3_backtest_events_{git_sha}_{run}.csv (이벤트별)
- backend/data/h3_backtest_summary_{git_sha}_{run}.json (요약 · 버킷 · 민감도)

실행:
    python -m backend.scripts.biotech_h3_backtest --events <path> [--seed 42]
    python -m backend.scripts.biotech_h3_backtest --dry-run
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import csv
import json
import logging
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

LOG = logging.getLogger("biotech_h3_backtest")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# 사양 상수 (사후 조정 금지)
ENTRY_OFFSET_DAYS = 1  # D+1 진입
HORIZONS = [30, 180]  # D+1~D+30 · D+1~D+180
COST_BPS = 100  # 1.0% 왕복
COST_BPS_SENSITIVITIES = [50, 100, 200, 500]  # 0.5/1.0/2.0/5.0%
BOOTSTRAP_ITER = 10_000
DEFAULT_SEED = 42
MCAP_BUCKETS = [(50_000_000, 300_000_000, "small"),
                (300_000_000, 1_000_000_000, "mid"),
                (1_000_000_000, 5_000_000_000, "large")]
BENCHMARK_TICKER = "XBI"
BENCHMARK_REF_TICKER = "IWM"

# B101-1 · 진입 지연 상한 (달력일)
ENTRY_LAG_MAX_DAYS = 7
# B101-2 · exit overshoot 임계 (달력일 · 목표일 이후)
EXIT_OVERSHOOT_DAYS = 15

# B100 · H3 알파 임계 (§2 H3 커밋값 · 사후 조정 금지)
ALPHA_THRESHOLDS = {
    "H3": {
        "h_30d": {"mean_ne_min": 5.0, "hit_min": 35.0, "ci_lo_positive": True},
        "h_180d": {"mean_ne_min": 15.0, "hit_min": 35.0, "ci_lo_positive": True},
    },
    # §2-0 서열: 1차 mean · 2차 hit. mean 미달 시 hit 무관 alpha 부재.
}


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=False,
            cwd=Path(__file__).resolve().parent.parent.parent,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def load_prices(prices_path: Path) -> dict[str, dict[str, float]]:
    """{ticker: {date: adj_close}} 로드."""
    out: dict[str, dict[str, float]] = defaultdict(dict)
    with open(prices_path) as f:
        for r in csv.DictReader(f):
            try:
                out[r["ticker"]][r["date"]] = float(r["adj_close"] or r["close"] or 0)
            except (ValueError, KeyError):
                continue
    return dict(out)


def load_benchmarks(bench_path: Path) -> dict[str, dict[str, float]]:
    """{ticker: {date: adj_close}}."""
    return load_prices(bench_path)


def next_trading_date(prices: dict[str, float], target: str) -> str | None:
    """target 날짜 이후 (포함) 첫 거래일."""
    sorted_dates = sorted(prices.keys())
    for d in sorted_dates:
        if d >= target:
            return d
    return None


def find_price_at_offset(prices: dict[str, float], event_date: str, offset_days: int) -> tuple[str | None, float | None]:
    """event_date + offset_days 이후 첫 거래일 종가 (엔트리용)."""
    try:
        base = datetime.strptime(event_date, "%Y-%m-%d") + timedelta(days=offset_days)
    except ValueError:
        return None, None
    target_str = base.strftime("%Y-%m-%d")
    d = next_trading_date(prices, target_str)
    if d is None:
        return None, None
    return d, prices[d]


def find_exit_with_shortening(prices: dict[str, float], target_date: str) -> tuple[str | None, float | None, bool]:
    """B99 · exit 종가 · 창 단축 청산 지원.
    반환: (exit_date, exit_price, window_shortened)
    - 목표일 이후 바 존재 → 첫 바 사용 · shortened=False
    - 목표일 이후 바 없고 마지막 바 < 목표일 → 마지막 바 사용 · shortened=True
    - 프라이스 자체 부재 → (None, None, False)
    """
    if not prices:
        return None, None, False
    sorted_dates = sorted(prices.keys())
    # 목표일 이후 첫 바
    for d in sorted_dates:
        if d >= target_date:
            return d, prices[d], False
    # 마지막 바가 목표일 이전 · 창 단축 청산 (인수·파산으로 시계열 종료)
    last_d = sorted_dates[-1]
    return last_d, prices[last_d], True


def check_eligibility(prices: dict[str, float], event_date: str) -> bool:
    """[D-30, D+180] 가격 실존 검사."""
    try:
        ev = datetime.strptime(event_date, "%Y-%m-%d")
    except ValueError:
        return False
    d_minus = (ev - timedelta(days=30)).strftime("%Y-%m-%d")
    d_plus = (ev + timedelta(days=180)).strftime("%Y-%m-%d")
    dates_in_range = [d for d in prices.keys() if d_minus <= d <= d_plus]
    return len(dates_in_range) > 0


def compute_return(prices: dict[str, float], event_date: str, horizon_days: int) -> tuple[float | None, dict]:
    """진입 D+1 종가 → D+1+horizon 종가 return.
    B99 · 창 단축 청산: 마지막 바 < 목표일 시 마지막 바 사용 · shortened=True
    B101-1 · entry_lag 사후 판정: entry_date > event+7d 이면 exclude_reason=entry_lag
    B101-2 · exit overshoot 사후 판정: exit_date > 목표일+15d flag (제외 아님)
    반환: (return_pct or None, meta)
    """
    entry_d, entry_p = find_price_at_offset(prices, event_date, ENTRY_OFFSET_DAYS)
    # exit: 창 단축 청산 지원
    try:
        ev = datetime.strptime(event_date, "%Y-%m-%d")
    except ValueError:
        return None, {"entry_date": None, "exit_date": None, "exclude_reason": "date_parse_fail"}
    target_exit_str = (ev + timedelta(days=ENTRY_OFFSET_DAYS + horizon_days)).strftime("%Y-%m-%d")
    exit_d, exit_p, shortened = find_exit_with_shortening(prices, target_exit_str)

    meta = {
        "entry_date": entry_d, "entry_price": entry_p,
        "exit_date": exit_d, "exit_price": exit_p,
        "target_exit_date": target_exit_str,
        "window_shortened": shortened, "actual_days": None,
        "entry_lag_days": None, "exit_overshoot": False,
        "exclude_reason": None,
    }
    if entry_p is None:
        meta["exclude_reason"] = "no_entry"
        return None, meta
    # B101-1 · entry_lag
    try:
        entry_dt = datetime.strptime(entry_d, "%Y-%m-%d")
        lag_days = (entry_dt - ev).days - ENTRY_OFFSET_DAYS  # ENTRY_OFFSET 초과분
        meta["entry_lag_days"] = lag_days
        if lag_days > ENTRY_LAG_MAX_DAYS:
            meta["exclude_reason"] = "entry_lag"
            return None, meta
    except (ValueError, TypeError):
        pass
    if exit_p is None or entry_p <= 0:
        meta["exclude_reason"] = "no_exit_data"
        return None, meta
    # actual_days
    try:
        exit_dt = datetime.strptime(exit_d, "%Y-%m-%d")
        meta["actual_days"] = (exit_dt - entry_dt).days
        # B101-2 · overshoot
        target_dt = datetime.strptime(target_exit_str, "%Y-%m-%d")
        if (exit_dt - target_dt).days > EXIT_OVERSHOOT_DAYS:
            meta["exit_overshoot"] = True
    except (ValueError, TypeError):
        pass
    ret = (exit_p - entry_p) / entry_p * 100
    return ret, meta


def compute_bench_return(bench_prices: dict[str, float], event_date: str, horizon_days: int) -> float | None:
    """벤치는 창 단축 없음 (지수 시계열 종료 안 함) · 목표일 첫 바만."""
    entry_d, entry_p = find_price_at_offset(bench_prices, event_date, ENTRY_OFFSET_DAYS)
    try:
        ev = datetime.strptime(event_date, "%Y-%m-%d")
    except ValueError:
        return None
    target_str = (ev + timedelta(days=ENTRY_OFFSET_DAYS + horizon_days)).strftime("%Y-%m-%d")
    exit_d = next_trading_date(bench_prices, target_str)
    if exit_d is None or entry_p is None or entry_p <= 0:
        return None
    return (bench_prices[exit_d] - entry_p) / entry_p * 100


def bootstrap_ci(values: list[float], iterations: int, seed: int, block_key: list | None = None) -> tuple[float, float, float]:
    """bootstrap 95% CI (하한·중앙·상한).
    block_key 주어지면 종목 클러스터 재추출 (block bootstrap).
    """
    import random
    if not values:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    n = len(values)
    means = []
    if block_key is None or len(block_key) != n:
        for _ in range(iterations):
            sample = [values[rng.randint(0, n - 1)] for _ in range(n)]
            means.append(sum(sample) / n)
    else:
        # block bootstrap · 티커 단위 재추출
        by_block: dict = defaultdict(list)
        for v, k in zip(values, block_key):
            by_block[k].append(v)
        blocks = list(by_block.keys())
        nb = len(blocks)
        for _ in range(iterations):
            sampled = []
            for _ in range(nb):
                b = blocks[rng.randint(0, nb - 1)]
                sampled.extend(by_block[b])
            means.append(sum(sampled) / len(sampled) if sampled else 0.0)
    means.sort()
    lo = means[int(len(means) * 0.025)]
    mid = means[int(len(means) * 0.5)]
    hi = means[int(len(means) * 0.975)]
    return lo, mid, hi


def hit_rate(values: list[float], threshold: float = 0.0) -> float:
    if not values:
        return 0.0
    return sum(1 for v in values if v > threshold) / len(values) * 100


def bucket_mcap(mcap: float | None) -> str | None:
    if mcap is None or mcap <= 0:
        return None
    for lo, hi, name in MCAP_BUCKETS:
        if lo <= mcap < hi:
            return name
    return None


def run_backtest(events: list[dict], prices_by_tkr: dict[str, dict[str, float]],
                 bench_prices: dict[str, float], mcap_lookup: dict, sic_lookup: dict,
                 seed: int) -> dict:
    """이벤트별 수익률 산출 + 요약."""
    per_event = []
    excluded = {"no_prices": 0, "not_eligible": 0, "no_entry": 0, "entry_lag": 0,
                "no_exit_data_30d": 0, "no_exit_data_180d": 0}
    shortened_counts = {f"h_{h}d": 0 for h in HORIZONS}
    overshoot_counts = {f"h_{h}d": 0 for h in HORIZONS}
    for ev in events:
        tkr = ev["ticker"]; date_ = ev["event_date"]
        prices = prices_by_tkr.get(tkr)
        if not prices:
            excluded["no_prices"] += 1
            continue
        if not check_eligibility(prices, date_):
            excluded["not_eligible"] += 1
            continue
        row = {**ev, "excluded": None, "returns": {}, "bench_returns": {}, "net_excess": {},
               "shortened": {}, "actual_days": {}, "overshoot": {}}
        skip_event = False
        for h in HORIZONS:
            ret, meta = compute_return(prices, date_, h)
            bench_ret = compute_bench_return(bench_prices, date_, h)
            if ret is None:
                reason = meta.get("exclude_reason", "no_exit_data")
                if reason == "no_entry":
                    excluded["no_entry"] += 1; skip_event = True; break
                if reason == "entry_lag":
                    excluded["entry_lag"] += 1; skip_event = True; break
                # no_exit_data 는 horizon 별
                excluded[f"no_exit_data_{h}d"] += 1
                row["returns"][f"ret_{h}d"] = None
                row["net_excess"][f"ne_{h}d"] = None
                continue
            row["returns"][f"ret_{h}d"] = ret
            row["bench_returns"][f"bench_{h}d"] = bench_ret
            row["shortened"][f"h_{h}d"] = meta.get("window_shortened", False)
            row["actual_days"][f"h_{h}d"] = meta.get("actual_days")
            row["overshoot"][f"h_{h}d"] = meta.get("exit_overshoot", False)
            if meta.get("window_shortened"): shortened_counts[f"h_{h}d"] += 1
            if meta.get("exit_overshoot"): overshoot_counts[f"h_{h}d"] += 1
            if bench_ret is not None:
                cost_pct = COST_BPS / 100.0
                net_excess = (ret - bench_ret) - cost_pct
                row["net_excess"][f"ne_{h}d"] = net_excess
        if skip_event:
            continue
        # mcap bucket · SIC
        mcap = mcap_lookup.get(ev["target_cik"])
        row["mcap"] = mcap; row["mcap_bucket"] = bucket_mcap(mcap)
        row["sic"] = sic_lookup.get(ev["target_cik"], "")
        per_event.append(row)

    # 요약
    summary = {"per_event_count": len(per_event), "excluded": excluded,
               "shortened_counts": shortened_counts, "overshoot_counts": overshoot_counts,
               "horizons": {}, "buckets": {}, "subsector_buckets": {}, "sensitivity": {}}
    for h in HORIZONS:
        vals = [r["net_excess"].get(f"ne_{h}d") for r in per_event if r["net_excess"].get(f"ne_{h}d") is not None]
        block_keys = [r["ticker"] for r in per_event if r["net_excess"].get(f"ne_{h}d") is not None]
        if not vals:
            summary["horizons"][f"h_{h}d"] = {"n": 0}
            continue
        mean_ne = sum(vals) / len(vals)
        hr = hit_rate(vals)
        lo, mid, hi = bootstrap_ci(vals, BOOTSTRAP_ITER, seed)
        lo_b, mid_b, hi_b = bootstrap_ci(vals, BOOTSTRAP_ITER, seed, block_key=block_keys)
        summary["horizons"][f"h_{h}d"] = {
            "n": len(vals), "mean_net_excess": round(mean_ne, 4),
            "hit_rate_pct": round(hr, 2),
            "ci_iid_95_lo": round(lo, 4), "ci_iid_95_mid": round(mid, 4), "ci_iid_95_hi": round(hi, 4),
            "ci_block_95_lo": round(lo_b, 4), "ci_block_95_mid": round(mid_b, 4), "ci_block_95_hi": round(hi_b, 4),
        }
        # 민감도
        summary["sensitivity"][f"h_{h}d"] = {}
        for cbps in COST_BPS_SENSITIVITIES:
            cost_diff = (cbps - COST_BPS) / 100.0  # net excess 이미 1.0% 차감된 상태 · 재조정
            adj_vals = [v - cost_diff for v in vals]
            adj_mean = sum(adj_vals) / len(adj_vals)
            adj_lo, _, _ = bootstrap_ci(adj_vals, BOOTSTRAP_ITER, seed)
            summary["sensitivity"][f"h_{h}d"][f"cost_{cbps}bps"] = {
                "mean_net_excess": round(adj_mean, 4), "ci_iid_95_lo": round(adj_lo, 4),
            }
        # 버킷 (mcap)
        summary["buckets"][f"h_{h}d"] = {}
        for lo_m, hi_m, name in MCAP_BUCKETS:
            bvals = [r["net_excess"].get(f"ne_{h}d") for r in per_event
                     if r["net_excess"].get(f"ne_{h}d") is not None and r["mcap_bucket"] == name]
            if bvals:
                bmean = sum(bvals) / len(bvals)
                blo, _, _ = bootstrap_ci(bvals, BOOTSTRAP_ITER, seed)
                summary["buckets"][f"h_{h}d"][name] = {
                    "n": len(bvals), "mean_ne": round(bmean, 4), "ci_lo": round(blo, 4),
                }
            else:
                summary["buckets"][f"h_{h}d"][name] = {"n": 0}
        # B101-3 · subsector 버킷 (SIC 2834 / 2836 / other)
        summary["subsector_buckets"][f"h_{h}d"] = {}
        for sic_key in ("2834", "2836", "other"):
            svals = [r["net_excess"].get(f"ne_{h}d") for r in per_event
                     if r["net_excess"].get(f"ne_{h}d") is not None
                     and (r.get("sic") == sic_key if sic_key != "other" else r.get("sic") not in ("2834", "2836"))]
            if svals:
                smean = sum(svals) / len(svals)
                slo, _, _ = bootstrap_ci(svals, BOOTSTRAP_ITER, seed)
                summary["subsector_buckets"][f"h_{h}d"][sic_key] = {
                    "n": len(svals), "mean_ne": round(smean, 4), "ci_lo": round(slo, 4),
                }
            else:
                summary["subsector_buckets"][f"h_{h}d"][sic_key] = {"n": 0}

    # B100 · alpha_confirmed (H3 커밋값 · §2 · Fable 검수 대기)
    alpha = {"status": "Fable 검수 대기", "hypothesis": "H3", "thresholds": ALPHA_THRESHOLDS["H3"]}
    for h in HORIZONS:
        s = summary["horizons"].get(f"h_{h}d", {})
        th = ALPHA_THRESHOLDS["H3"].get(f"h_{h}d", {})
        if s.get("n", 0) > 0 and th:
            pass_ci = s.get("ci_iid_95_lo", 0) > 0 if th.get("ci_lo_positive") else True
            pass_mean = s.get("mean_net_excess", 0) >= th.get("mean_ne_min", 0)
            pass_hr = s.get("hit_rate_pct", 0) >= th.get("hit_min", 0)
            # §2-0 서열: 1차 mean · 2차 hit. mean 미달 시 hit 무관 alpha 부재
            alpha[f"h_{h}d_conditions"] = {
                "ci_lo>0": pass_ci,
                f"mean>={th['mean_ne_min']}%": pass_mean,
                f"hr>={th['hit_min']}%": pass_hr,
            }
            alpha[f"h_{h}d_alpha_confirmed"] = pass_ci and pass_mean and pass_hr
    summary["alpha_confirmed"] = alpha

    return {"per_event": per_event, "summary": summary}


def main() -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=str, default=None, help="h3_events CSV 경로")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run-tag", type=str, default="run1")
    args = ap.parse_args()

    git_sha = _git_sha()

    if args.dry_run:
        print(f"\n== DRY-RUN B97 백테스트 엔진 ==")
        print(f"git_sha:         {git_sha}")
        print(f"entry:           D+{ENTRY_OFFSET_DAYS} adj_close")
        print(f"horizons:        {HORIZONS}")
        print(f"benchmark:       {BENCHMARK_TICKER} (ref {BENCHMARK_REF_TICKER})")
        print(f"cost:            {COST_BPS}bps · 민감도 {COST_BPS_SENSITIVITIES}")
        print(f"bootstrap:       {BOOTSTRAP_ITER}회 · seed={args.seed}")
        print(f"buckets:         mcap {MCAP_BUCKETS}")
        return 0

    if not args.events:
        LOG.error("--events 필수")
        return 1

    events_path = Path(args.events)
    if not events_path.exists():
        LOG.error("events 파일 부재: %s", events_path)
        return 1

    with open(events_path) as f:
        events = list(csv.DictReader(f))
    LOG.info("events 로드: %d", len(events))

    prices = load_prices(DATA_DIR / "h3_prices_merged_add7af7.csv")
    LOG.info("prices tickers: %d", len(prices))

    # benchmarks
    bench_all = load_prices(DATA_DIR / "benchmarks_add7af7.csv")
    bench_prices = bench_all.get(BENCHMARK_TICKER, {})
    LOG.info("benchmark %s: %d dates", BENCHMARK_TICKER, len(bench_prices))

    # mcap · SIC 조회 (mcap: companyfacts 부재 시 None · SIC: B101-3 h3_targets_v2 배선)
    mcap_lookup: dict = {}
    sic_lookup: dict = {}
    targets_path = DATA_DIR / "h3_targets_v2_add7af7.csv"
    if targets_path.exists():
        with open(targets_path) as f:
            for r in csv.DictReader(f):
                cik = r.get("target_cik", "")
                if cik:
                    sic_lookup[cik] = r.get("sic", "")
        LOG.info("SIC 배선 · %d targets", len(sic_lookup))

    result = run_backtest(events, prices, bench_prices, mcap_lookup, sic_lookup, args.seed)

    # 저장
    events_out = DATA_DIR / f"h3_backtest_events_{git_sha}_{args.run_tag}.csv"
    summary_out = DATA_DIR / f"h3_backtest_summary_{git_sha}_{args.run_tag}.json"
    if result["per_event"]:
        # flatten dicts
        rows = []
        for e in result["per_event"]:
            flat = {k: v for k, v in e.items() if not isinstance(v, dict)}
            for k, v in e.get("returns", {}).items(): flat[k] = v
            for k, v in e.get("net_excess", {}).items(): flat[k] = v
            for k, v in e.get("bench_returns", {}).items(): flat[k] = v
            rows.append(flat)
        with open(events_out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
            w.writeheader(); w.writerows(rows)

    with open(summary_out, "w") as f:
        json.dump({"git_sha": git_sha, "seed": args.seed, **result["summary"]}, f, indent=2, ensure_ascii=False)

    print(f"\n== B97 백테스트 · {args.run_tag} ==")
    print(f"git_sha:            {git_sha}")
    print(f"events in:          {len(events)}")
    print(f"per_event out:      {result['summary']['per_event_count']}")
    print(f"excluded:           {result['summary']['excluded']}")
    for h in HORIZONS:
        s = result["summary"]["horizons"].get(f"h_{h}d", {})
        print(f"H+{h}d: n={s.get('n',0)} · mean_ne={s.get('mean_net_excess','?')}% · hr={s.get('hit_rate_pct','?')}% · CI[{s.get('ci_iid_95_lo','?')}, {s.get('ci_iid_95_hi','?')}]")
    print(f"events_csv:         {events_out}")
    print(f"summary_json:       {summary_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
