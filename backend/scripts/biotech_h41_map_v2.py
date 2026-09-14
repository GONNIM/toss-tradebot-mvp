"""WP41-3 · 13D 지도 v2 (커버율 61.6% · 제출자 4분류 · 인수 종료 제외 민감도).

용도:
- EFTS 643 events · WP41-1 가격 보충 · WP41-2 제출자 분류 반영
- 시총 3버킷 × 제출자 4분류 × 창 (30d/180d) · mean · date-cluster CI · hit · n
- shortened 예상 (인수 종료 · exit_date > form25_date+30d)
- 인수 종료 제외 민감도 병기 (인수 프리미엄 의존도)
- 가장 밝은 조건 top5 (n ≥ 30)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING, REQ_INTERVAL, SecBlockedError

import csv
import json
import logging
import random
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h41_map_v2")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

MCAP_BUCKETS = [
    ("50M_300M", 50e6, 300e6),
    ("300M_1B", 300e6, 1e9),
    ("1B_5B", 1e9, 5e9),
]
COST_BPS = 100
HORIZONS = [30, 180]
BOOT = 5000
SEED = 42


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def next_close(prices: dict, base: str, o_s: int, o_e: int):
    try:
        b = datetime.strptime(base, "%Y-%m-%d").date()
    except Exception:
        return None
    for off in range(o_s, o_e + 1):
        k = (b + timedelta(days=off)).strftime("%Y-%m-%d")
        if k in prices:
            return (k, prices[k])
    return None


def bootstrap_ci(vals: list[float], groups: list | None, boot=BOOT, seed=SEED):
    if not vals:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(vals)
    if groups is None:
        means = [sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(boot)]
    else:
        gid = defaultdict(list)
        for v, g in zip(vals, groups):
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
    return (round(means[int(0.025 * len(means))], 4), round(means[int(0.975 * len(means))], 4))


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    efts = list(csv.DictReader((DATA_DIR / f"h3_efts_sc13d_universe_{sha}.csv").open()))

    # 제출자 4분류
    filer_bucket = {}
    fp = DATA_DIR / "h41_filer_classification.json"
    if fp.exists():
        for cik, info in json.loads(fp.read_text()).items():
            filer_bucket[cik] = info.get("bucket", "other")

    # 티커 매핑
    tk_map = {}
    with (DATA_DIR / f"h3_targets_v2_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            c = (r.get("target_cik") or "").zfill(10)
            t = (r.get("ticker") or "").strip()
            listing = r.get("listing_status", "")
            form25 = r.get("form25_date", "")
            if c and t:
                tk_map[c] = {"ticker": t, "listing": listing, "form25": form25}
    sec_map = json.loads((DATA_DIR / "sec_company_tickers.json").read_text())
    sec_cik2tk = {}
    for _, e in sec_map.items():
        cik = str(e.get("cik_str", "")).zfill(10)
        tk = str(e.get("ticker", "")).upper()
        if cik and tk:
            sec_cik2tk[cik] = tk

    # 가격 · 시총 · 벤치
    prices: dict[str, dict] = defaultdict(dict)
    with (DATA_DIR / f"h3_prices_merged_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            try:
                prices[r["ticker"]][r["date"]] = float(r["close"])
            except Exception:
                continue
    bench = {}
    with (DATA_DIR / f"benchmarks_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            if r.get("ticker") == "XBI":
                try:
                    bench[r["date"]] = float(r["close"])
                except Exception:
                    continue
    mcap = {}
    with (DATA_DIR / f"h3_mcap_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            try:
                sh = float(r.get("shares", "") or 0)
            except Exception:
                sh = 0
            if sh > 0:
                mcap[r["cik"]] = sh

    # 부족한 CIK 는 companyfacts 즉시 조회 (SEC 지정 헤더)
    def fetch_shares(client, cik10, cache):
        if cik10 in cache:
            return cache[cik10]
        try:
            time.sleep(REQ_INTERVAL)
            r = client.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json", timeout=30.0)
            if r.status_code == 403:
                raise SecBlockedError("403 companyfacts")
            if r.status_code != 200:
                cache[cik10] = 0
                return 0
            data = r.json()
            facts = data.get("facts", {}) or {}
            candidates = []
            for ns, key in (("dei", "EntityCommonStockSharesOutstanding"), ("us-gaap", "CommonStockSharesOutstanding")):
                node = facts.get(ns, {}).get(key)
                if not node:
                    continue
                for u in node.get("units", {}).get("shares", []):
                    end = u.get("end", "")
                    val = u.get("val")
                    if end and val is not None:
                        try:
                            candidates.append((end, float(val)))
                        except Exception:
                            continue
            candidates.sort()
            cache[cik10] = candidates[-1][1] if candidates else 0
            return cache[cik10]
        except Exception:
            cache[cik10] = 0
            return 0

    dyn_shares = dict(mcap)
    events_scored = []

    with httpx.Client(headers={"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}, timeout=30.0) as client:
        for r in efts:
            cik = r["subject_cik"]
            edate = r["date"]
            info = tk_map.get(cik) or {"ticker": sec_cik2tk.get(cik, ""), "listing": "", "form25": ""}
            ticker = info.get("ticker", "")
            if not ticker:
                continue
            sp = prices.get(ticker) or prices.get(ticker.upper()) or {}
            if not sp:
                continue
            entry = next_close(sp, edate, 1, 7)
            if entry is None:
                continue
            shares = dyn_shares.get(cik)
            if not shares:
                shares = fetch_shares(client, cik, dyn_shares)
            mcap_val = entry[1] * shares if shares else 0
            bkt = "out"
            for name, lo, hi in MCAP_BUCKETS:
                if lo <= mcap_val < hi:
                    bkt = name; break
            if bkt == "out":
                continue

            fb = filer_bucket.get(r["filer_cik"], "other")
            per = {}
            shortened = False
            form25 = info.get("form25", "") or ""
            # shortened: form25_date+30d 가 창 안이면 shortened=True
            for h in HORIZONS:
                exit_ = next_close(sp, edate, h - 15, h + 15)
                b_e = next_close(bench, edate, 1, 7)
                b_x = next_close(bench, edate, h - 15, h + 15)
                if exit_ is None or b_e is None or b_x is None:
                    continue
                r_stock = exit_[1] / entry[1] - 1.0
                r_bench = b_x[1] / b_e[1] - 1.0
                per[h] = r_stock - r_bench - (COST_BPS / 10000.0)
                # shortened 판정 (h=180d 만 유의미 · form25 존재 시)
                if form25:
                    try:
                        f25 = datetime.strptime(form25, "%Y-%m-%d").date()
                        base = datetime.strptime(edate, "%Y-%m-%d").date()
                        if (f25 - base).days < h:  # 인수/폐지가 창 안에 발생
                            shortened = True
                    except Exception:
                        pass

            events_scored.append({
                "date": edate, "cik": cik, "ticker": ticker,
                "filer_cik": r["filer_cik"], "filer_bucket": fb,
                "mcap_bucket": bkt, "shortened": shortened,
                "net_30d": per.get(30), "net_180d": per.get(180),
            })

    LOG.info("events scored: %d / %d (coverage %.1f%%)", len(events_scored), len(efts), 100 * len(events_scored) / max(1, len(efts)))

    # Grid: (mcap_bucket, filer_bucket, horizon) · 전체 + 인수 제외 민감도
    def grid_stats(pool: list[dict], label: str):
        grid = defaultdict(list)
        gd = defaultdict(list)
        for e in pool:
            for h in HORIZONS:
                v = e.get(f"net_{h}d")
                if v is None:
                    continue
                k = (e["mcap_bucket"], e["filer_bucket"], h)
                grid[k].append(v); gd[k].append(e["date"])
        rows = []
        for k, vals in grid.items():
            bkt, fb, h = k
            m = mean(vals); hits = sum(1 for v in vals if v > 0)
            clu = bootstrap_ci(vals, gd[k])
            rows.append({
                "cohort": label, "mcap_bucket": bkt, "filer_bucket": fb, "horizon_days": h,
                "n": len(vals), "unique_dates": len(set(gd[k])),
                "mean_net_excess": round(m, 4), "hit_rate": round(hits/len(vals), 3),
                "cluster_ci_lo": clu[0], "cluster_ci_hi": clu[1],
                "sign": "+" if m > 0 else ("-" if m < 0 else "0"),
            })
        return rows

    all_rows = grid_stats(events_scored, "all")
    no_short = [e for e in events_scored if not e["shortened"]]
    ex_rows = grid_stats(no_short, "excl_shortened")
    LOG.info("all pool: %d · excl_shortened: %d", len(events_scored), len(no_short))

    map_rows = sorted(all_rows + ex_rows, key=lambda r: (r["horizon_days"], -r["mean_net_excess"]))

    out_dir = DATA_DIR / "biotech" / "seals"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"h41_map_v2_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(map_rows[0].keys()))
        w.writeheader()
        w.writerows(map_rows)

    bright_all = sorted([r for r in all_rows if r["n"] >= 30], key=lambda r: -r["mean_net_excess"])[:5]
    bright_ex = sorted([r for r in ex_rows if r["n"] >= 30], key=lambda r: -r["mean_net_excess"])[:5]

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "events_efts_total": len(efts),
        "events_scored_all": len(events_scored),
        "events_scored_excl_shortened": len(no_short),
        "coverage_rate_scored": round(len(events_scored) / max(1, len(efts)), 3),
        "brightest_top5_all": bright_all,
        "brightest_top5_excl_shortened": bright_ex,
        "note": "탐색 트랙 · 판정 없음 · 사전 등록 후에만 알파 주장",
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
