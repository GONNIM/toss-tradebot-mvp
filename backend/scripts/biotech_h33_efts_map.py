"""WP33-3 · EFTS SC 13D 전수 → 시총·제출자 유형·조건별 효과 크기 지도.

용도:
- h3_efts_sc13d_universe_{sha}.csv (WP37b 산출) 각 이벤트에 대해:
  - 시총 (companyfacts shares × D+1 종가) · 3버킷 [50M-300M / 300M-1B / 1B-5B]
  - 제출자 유형: seed_activist (55 CIK) / out_of_seed_fund (filer 이름 fund/capital/partners) / out_of_seed_other
  - 30d · 180d net excess (XBI 벤치 · 왕복 1.0%)
- 조건별 (시총 × 유형) mean · 클러스터 CI · hit · n · 판정 없음 (탐색)
- 가장 밝은 조건 = (n ≥ 30 AND mean 상위 3 · CI 하한 최대) 표기

원칙:
- SEC 접근 없음 (h3_efts_sc13d 이미 로드 · companyfacts 캐시 h3_mcap 재사용)
- 부족 시 필요한 새 CIK 만 companyfacts 조회 (SEC 지정 헤더)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING, REQ_INTERVAL, SecBlockedError

import csv
import json
import logging
import random
import re
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h33_efts_map")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

MCAP_BUCKETS = [
    ("50M_300M", 50e6, 300e6),
    ("300M_1B", 300e6, 1e9),
    ("1B_5B", 1e9, 5e9),
]
COST_BPS = 100  # 1.0% 왕복
HORIZONS = [30, 180]
BOOT = 5_000
SEED = 42


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_efts(sha: str) -> list[dict]:
    p = DATA_DIR / f"h3_efts_sc13d_universe_{sha}.csv"
    with p.open() as f:
        return list(csv.DictReader(f))


def load_seed_ciks(sha: str) -> set[str]:
    p = DATA_DIR / f"h3_activist_cik_registry_v2_{sha}.csv"
    out = set()
    with p.open() as f:
        for r in csv.DictReader(f):
            out.add((r.get("cik") or "").zfill(10))
    return out


def load_mcap_cache(sha: str) -> dict[str, float]:
    """h3_mcap · CIK → shares (asof 별 최근 값 대체)."""
    p = DATA_DIR / f"h3_mcap_{sha}.csv"
    out = {}
    if not p.exists():
        return out
    with p.open() as f:
        for r in csv.DictReader(f):
            try:
                sh = float(r.get("shares", "") or 0)
            except Exception:
                sh = 0
            if sh > 0:
                out[r["cik"]] = sh
    return out


def load_sec_company_map(sha: str) -> dict[str, str]:
    """SEC company_tickers · cik10 → title (filer 유형 분류용)."""
    p = DATA_DIR / "sec_company_tickers.json"
    out = {}
    if p.exists():
        for _, e in json.loads(p.read_text()).items():
            cik = str(e.get("cik_str", "")).zfill(10)
            title = str(e.get("title", ""))
            if cik and title:
                out[cik] = title
    return out


def load_prices_merged(sha: str) -> dict[str, dict[str, float]]:
    p = DATA_DIR / f"h3_prices_merged_{sha}.csv"
    out: dict[str, dict[str, float]] = defaultdict(dict)
    with p.open() as f:
        for r in csv.DictReader(f):
            try:
                out[r["ticker"]][r["date"]] = float(r["close"])
            except Exception:
                continue
    return out


def load_bench(sha: str) -> dict[str, float]:
    p = DATA_DIR / f"benchmarks_{sha}.csv"
    out: dict[str, float] = {}
    if not p.exists():
        return out
    with p.open() as f:
        for r in csv.DictReader(f):
            if r.get("ticker") == "XBI":
                try:
                    out[r["date"]] = float(r["close"])
                except Exception:
                    continue
    return out


def load_targets(sha: str) -> dict[str, dict]:
    p = DATA_DIR / f"h3_targets_v2_{sha}.csv"
    out = {}
    with p.open() as f:
        for r in csv.DictReader(f):
            out[r.get("target_cik", "")] = r
    return out


def next_close(prices: dict, base: str, o_s: int, o_e: int) -> tuple[str, float] | None:
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


FUND_KW = ("FUND", "CAPITAL", "PARTNERS", "ADVISORS", "MANAGEMENT", "LP", "L.P.", "LLC", "HEALTHCARE", "BIOTECH")


def filer_type(filer_cik: str, name: str, seed: set[str]) -> str:
    if filer_cik in seed:
        return "seed_activist"
    upper = (name or "").upper()
    if any(k in upper for k in FUND_KW):
        return "out_of_seed_fund"
    if not name:
        return "out_of_seed_unknown"
    return "out_of_seed_other"


def fetch_shares(client: httpx.Client, cik10: str, asof: str, cache: dict) -> float:
    if cik10 in cache:
        return cache[cik10]
    try:
        time.sleep(REQ_INTERVAL)
        r = client.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json", timeout=30.0)
        if r.status_code == 403:
            raise SecBlockedError(f"403 · companyfacts {cik10}")
        if r.status_code != 200:
            cache[cik10] = 0.0
            return 0.0
        data = r.json()
        facts = data.get("facts", {}) or {}
        candidates = []
        for ns, key in (
            ("dei", "EntityCommonStockSharesOutstanding"),
            ("us-gaap", "CommonStockSharesOutstanding"),
        ):
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
        best = None
        for e, v in candidates:
            if e <= asof:
                best = (e, v)
            else:
                break
        cache[cik10] = best[1] if best else 0.0
        return cache[cik10]
    except SecBlockedError:
        raise
    except Exception:
        cache[cik10] = 0.0
        return 0.0


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    efts = load_efts(sha)
    seed = load_seed_ciks(sha)
    mcap_cache = load_mcap_cache(sha)
    sec_name = load_sec_company_map(sha)
    prices = load_prices_merged(sha)
    bench = load_bench(sha)
    targets = load_targets(sha)
    LOG.info("efts=%d · seed=%d · mcap_cache=%d · sec_name=%d · bench=%d",
             len(efts), len(seed), len(mcap_cache), len(sec_name), len(bench))

    if not bench:
        LOG.error("XBI bench missing")
        return

    dyn_shares_cache = dict(mcap_cache)  # 확장 시 채움
    events_scored = []

    with httpx.Client(headers={"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}, timeout=30.0) as client:
        try:
            for row in efts:
                cik = row["subject_cik"]
                edate = row["date"]
                tgt = targets.get(cik) or targets.get(cik.lstrip("0"))
                ticker = ""
                if tgt:
                    ticker = (tgt.get("ticker") or "").strip()
                if not ticker:
                    # SEC company_tickers 로 복구
                    name = sec_name.get(cik, "")
                if not ticker:
                    continue
                sp = prices.get(ticker) or prices.get(ticker.upper()) or {}
                if not sp:
                    continue
                entry = next_close(sp, edate, 1, 7)
                if entry is None:
                    continue

                shares = dyn_shares_cache.get(cik)
                if not shares:
                    shares = fetch_shares(client, cik, edate, dyn_shares_cache)
                mcap_val = entry[1] * shares if shares else 0
                bkt = "out"
                for name, lo, hi in MCAP_BUCKETS:
                    if lo <= mcap_val < hi:
                        bkt = name
                        break
                if bkt == "out":
                    continue

                per_h = {}
                for h in HORIZONS:
                    exit_ = next_close(sp, edate, h - 15, h + 15)
                    b_e = next_close(bench, edate, 1, 7)
                    b_x = next_close(bench, edate, h - 15, h + 15)
                    if exit_ is None or b_e is None or b_x is None:
                        continue
                    r_stock = exit_[1] / entry[1] - 1.0
                    r_bench = b_x[1] / b_e[1] - 1.0
                    per_h[h] = r_stock - r_bench - (COST_BPS / 10000.0)

                filer_name = sec_name.get(row["filer_cik"], "")
                ftype = filer_type(row["filer_cik"], filer_name, seed)
                events_scored.append({
                    "date": edate,
                    "subject_cik": cik,
                    "ticker": ticker,
                    "filer_cik": row["filer_cik"],
                    "filer_type": ftype,
                    "mcap_bucket": bkt,
                    "sic": row.get("sic", ""),
                    "net_30d": per_h.get(30),
                    "net_180d": per_h.get(180),
                })
        except SecBlockedError as e:
            LOG.error("BLOCKED · %s · partial results kept", e)

    LOG.info("events scored: %d", len(events_scored))

    # 지도: (mcap_bucket · filer_type · horizon) → stats
    grid = defaultdict(list)
    grid_dates = defaultdict(list)
    for e in events_scored:
        for h in HORIZONS:
            v = e.get(f"net_{h}d")
            if v is None:
                continue
            key = (e["mcap_bucket"], e["filer_type"], h)
            grid[key].append(v)
            grid_dates[key].append(e["date"])

    map_rows = []
    for key, vals in grid.items():
        bkt, ftype, h = key
        m = mean(vals)
        hits = sum(1 for v in vals if v > 0)
        clu = bootstrap_ci(vals, grid_dates[key])
        iid = bootstrap_ci(vals, None)
        map_rows.append({
            "mcap_bucket": bkt,
            "filer_type": ftype,
            "horizon_days": h,
            "n": len(vals),
            "unique_dates": len(set(grid_dates[key])),
            "mean_net_excess": round(m, 4),
            "hit_rate": round(hits / len(vals), 3),
            "cluster_ci_lo": clu[0],
            "cluster_ci_hi": clu[1],
            "iid_ci_lo": iid[0],
            "iid_ci_hi": iid[1],
            "sign": "+" if m > 0 else ("-" if m < 0 else "0"),
        })
    map_rows.sort(key=lambda r: (r["horizon_days"], -r["mean_net_excess"]))

    out_dir = DATA_DIR / "biotech" / "seals"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"h33_efts_map_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(map_rows[0].keys()))
        w.writeheader()
        w.writerows(map_rows)

    # 가장 밝은 조건 (n ≥ 30 · mean 상위 3 · CI 하한 정렬)
    bright = [r for r in map_rows if r["n"] >= 30]
    bright.sort(key=lambda r: (-r["mean_net_excess"], -r["cluster_ci_lo"]))
    brightest = bright[:5]

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "events_scored": len(events_scored),
        "grid_cells": len(map_rows),
        "brightest_top5": brightest,
        "note": "탐색 트랙 · 판정 없음 · 사전 등록 후에만 알파 주장",
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
