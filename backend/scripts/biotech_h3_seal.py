"""WP31 · H3 본 실행 봉인 보고 (자동 GO 5/5 PASS 후에만 · 유형별 · 창별).

용도:
- h3_events (13D_new 50 + 13G_new 296 = 346) · 유형별 + 합산 분리 판정
- 창 30d · 180d
- bootstrap 1차 date-cluster · 2차 종목 블록 · 3차 iid
- 시총 필터 $50M~$5B · 버킷 mcap×subsector
- 봉인 리포트 h3_seal_report
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import random
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h3_seal")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

HORIZONS = [30, 180]
THRESHOLDS = {30: 0.05, 180: 0.15}  # H3 §2 커밋
HIT_THRESHOLD = 0.35
COST_BPS = 100  # 왕복 1.0%
BOOT = 10_000
SEED = 42

MCAP_BUCKETS = [
    ("50M_300M", 50e6, 300e6),
    ("300M_1B", 300e6, 1e9),
    ("1B_5B", 1e9, 5e9),
]


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_events():
    return list(csv.DictReader((DATA_DIR / "h3_events_add7af7.csv").open()))


def load_targets():
    out = {}
    with (DATA_DIR / "h3_targets_v2_add7af7.csv").open() as f:
        for r in csv.DictReader(f):
            out[r["target_cik"]] = r
    return out


def load_mcap():
    out = {}
    with (DATA_DIR / "h3_mcap_add7af7.csv").open() as f:
        for r in csv.DictReader(f):
            try:
                sh = float(r.get("shares", "") or 0)
            except Exception:
                sh = 0
            if sh > 0:
                out[r["cik"]] = sh
    return out


def load_prices():
    out = defaultdict(dict)
    with (DATA_DIR / "h3_prices_merged_add7af7.csv").open() as f:
        for r in csv.DictReader(f):
            try:
                out[r["ticker"]][r["date"]] = float(r["close"])
            except Exception:
                continue
    return out


def load_bench():
    """XBI · benchmarks_add7af7.csv 있을 경우."""
    p = DATA_DIR / "benchmarks_add7af7.csv"
    out = {}
    if not p.exists():
        return out
    with p.open() as f:
        for r in csv.DictReader(f):
            tk = r.get("ticker", "")
            try:
                out.setdefault(tk, {})[r["date"]] = float(r["close"])
            except Exception:
                continue
    return out


def next_trading_close(prices: dict, event_date: str, offset_start: int, offset_end: int) -> tuple[str, float] | None:
    try:
        b = datetime.strptime(event_date, "%Y-%m-%d").date()
    except Exception:
        return None
    for offset in range(offset_start, offset_end + 1):
        k = (b + timedelta(days=offset)).strftime("%Y-%m-%d")
        if k in prices:
            return (k, prices[k])
    return None


def compute_net_excess(sp: dict, bp: dict, edate: str, horizon: int) -> float | None:
    entry = next_trading_close(sp, edate, 1, 7)
    if entry is None:
        return None
    exit_ = next_trading_close(sp, edate, horizon - 15, horizon + 15)
    if exit_ is None:
        return None
    r_stock = exit_[1] / entry[1] - 1.0
    b_entry = next_trading_close(bp, edate, 1, 7)
    b_exit = next_trading_close(bp, edate, horizon - 15, horizon + 15)
    if b_entry is None or b_exit is None:
        return None
    r_bench = b_exit[1] / b_entry[1] - 1.0
    return r_stock - r_bench - (COST_BPS / 10000.0)


def bootstrap_ci(values: list[float], groups: list | None, boot: int, seed: int) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(values)
    if groups is None:
        means = [sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(boot)]
    else:
        gid = defaultdict(list)
        for v, g in zip(values, groups):
            gid[g].append(v)
        keys = list(gid.keys())
        nc = len(keys)
        means = []
        for _ in range(boot):
            pool = []
            for _ in range(nc):
                pool.extend(gid[keys[rng.randrange(nc)]])
            if pool:
                means.append(sum(pool) / len(pool))
    means.sort()
    return (means[int(0.025 * len(means))], means[int(0.975 * len(means))])


def mcap_bucket(mcap: float) -> str:
    for name, lo, hi in MCAP_BUCKETS:
        if lo <= mcap < hi:
            return name
    return "out_of_range"


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    events = load_events()
    targets = load_targets()
    mcap = load_mcap()
    prices = load_prices()
    bench_map = load_bench()
    bp_xbi = bench_map.get("XBI", {})
    LOG.info("events=%d · targets=%d · mcap=%d · prices=%d · XBI bench=%d",
             len(events), len(targets), len(mcap), len(prices), len(bp_xbi))

    if not bp_xbi:
        LOG.error("XBI bench missing")
        return

    per_evt = []
    for ev in events:
        tcik = (ev.get("target_cik") or "").zfill(10)
        tgt = targets.get(tcik) or targets.get(tcik.lstrip("0"))
        if not tgt or tgt.get("sic_biotech") != "True":
            continue
        ticker = (tgt.get("ticker") or "").strip()
        if not ticker:
            continue
        sp = prices.get(ticker) or prices.get(ticker.upper()) or {}
        if not sp:
            continue
        entry = next_trading_close(sp, ev["event_date"], 1, 7)
        if entry is None:
            continue
        # mcap
        m_shares = mcap.get(tcik) or mcap.get(tcik.lstrip("0"))
        if not m_shares:
            continue
        mcap_val = entry[1] * m_shares
        bkt = mcap_bucket(mcap_val)
        if bkt == "out_of_range":
            continue
        sic = tgt.get("sic", "")
        sub = "2834_pharma" if sic == "2834" else ("2836_biologics" if sic == "2836" else "other")

        row = {
            "event_id": ev["event_id"],
            "target_cik": tcik,
            "ticker": ticker,
            "event_type": ev["event_type"],
            "event_date": ev["event_date"],
            "mcap_bkt": bkt,
            "subsector": sub,
        }
        for h in HORIZONS:
            r = compute_net_excess(sp, bp_xbi, ev["event_date"], h)
            row[f"net_{h}d"] = r
        per_evt.append(row)

    LOG.info("eligible after all filters: %d", len(per_evt))

    seal = {
        "git_sha": sha,
        "gate_status": "관문 1 (H3) 본 실행 봉인 · Fable 검수 대기",
        "auto_go": True,
        "seed": SEED,
        "bootstrap_iter": BOOT,
        "cost_bps_round_trip": COST_BPS,
        "windows_by_type": {},
    }
    for etype_key, evt_filter in [
        ("13D_new", lambda e: e["event_type"] == "13D_new"),
        ("13G_new", lambda e: e["event_type"] == "13G_new"),
        ("ALL_combined", lambda e: True),
    ]:
        seal["windows_by_type"][etype_key] = {}
        subset = [r for r in per_evt if evt_filter(r)]
        for h in HORIZONS:
            vals = [r[f"net_{h}d"] for r in subset if r[f"net_{h}d"] is not None]
            if not vals:
                seal["windows_by_type"][etype_key][f"h_{h}d"] = {"n": 0}
                continue
            groups_date = [r["event_date"] for r in subset if r[f"net_{h}d"] is not None]
            groups_ticker = [r["ticker"] for r in subset if r[f"net_{h}d"] is not None]
            m = mean(vals)
            hits = sum(1 for v in vals if v > 0)
            date_lo, date_hi = bootstrap_ci(vals, groups_date, BOOT, SEED)
            ticker_lo, ticker_hi = bootstrap_ci(vals, groups_ticker, BOOT, SEED)
            iid_lo, iid_hi = bootstrap_ci(vals, None, BOOT, SEED)
            thr = THRESHOLDS[h]
            alpha = (m >= thr) and (date_lo > 0) and (hits / len(vals) >= HIT_THRESHOLD)
            seal["windows_by_type"][etype_key][f"h_{h}d"] = {
                "n": len(vals),
                "unique_dates": len(set(groups_date)),
                "unique_tickers": len(set(groups_ticker)),
                "mean_net_excess": round(m, 4),
                "date_cluster_ci95_lo": round(date_lo, 4),
                "date_cluster_ci95_hi": round(date_hi, 4),
                "ticker_block_ci95_lo": round(ticker_lo, 4),
                "ticker_block_ci95_hi": round(ticker_hi, 4),
                "iid_ci95_lo": round(iid_lo, 4),
                "iid_ci95_hi": round(iid_hi, 4),
                "hit_rate": round(hits / len(vals), 3),
                "threshold_mean": thr,
                "threshold_hit": HIT_THRESHOLD,
                "alpha_pass_machine": alpha,
                "sign": "+" if m > 0 else ("-" if m < 0 else "0"),
            }

    # 버킷별 (전 유형 합산)
    bucket_stats = defaultdict(lambda: defaultdict(list))
    for r in per_evt:
        for h in HORIZONS:
            if r[f"net_{h}d"] is not None:
                bucket_stats[(r["mcap_bkt"], r["subsector"])][h].append(r[f"net_{h}d"])
    seal["buckets"] = {}
    for (bkt, sub), by_h in bucket_stats.items():
        entry = {}
        for h in HORIZONS:
            vals = by_h[h]
            if vals:
                entry[f"h_{h}d"] = {"n": len(vals), "mean_net_excess": round(mean(vals), 4)}
        seal["buckets"][f"{bkt}__{sub}"] = entry

    seal["fable_review"] = "pending"
    seal["survivorship_bias_ref"] = "h3_bias_analysis_add7af7.csv · h3_labels_add7af7.csv · h3_excluded_breakdown_add7af7.csv"

    out_path = DATA_DIR / f"h3_seal_report_{sha}.json"
    out_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2))
    LOG.info("seal saved: %s", out_path)
    print(json.dumps(seal, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
