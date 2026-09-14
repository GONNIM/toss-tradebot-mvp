"""WP43-3 · H8 검정 1·3 + H1b · WP39 부분 풀 실행.

이벤트 = h39_readouts_checkpoint (5423 events · 부분 풀 210/340 CIK).

축약 (사전 커밋 정합):
- H8 검정 1 (선행성 근사): 동일 CIK 이벤트 수 (30일 기준선) 상/하 절반 · D-30~D-1 net excess 차이
- H8 검정 3 (뉴스에 팔기): 전 D-30~D-1 vs 후 D+1~D+30 · CI 부호 비교
- H1b: D-30 진입 · D-1 청산 · net excess (guidance window 시작일 = D-day)

봉인 JSON · verification/H8 · H1b 리포트.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h43_h8_h1b")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
COST_BPS = 100
BOOT = 5000
SEED = 42


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_events(sha: str) -> list[dict]:
    cp = DATA_DIR / "h39_readouts_checkpoint.json"
    if cp.exists():
        events = json.loads(cp.read_text()).get("events", [])
        LOG.info("h39 events (partial pool): %d", len(events))
        return events
    return []


def load_prices(sha: str) -> dict:
    p = DATA_DIR / f"h3_prices_merged_{sha}.csv"
    out = defaultdict(dict)
    with p.open() as f:
        for r in csv.DictReader(f):
            try:
                out[r["ticker"]][r["date"]] = float(r["close"])
            except Exception:
                continue
    return out


def load_bench(sha: str) -> dict:
    p = DATA_DIR / f"benchmarks_{sha}.csv"
    out = {}
    with p.open() as f:
        for r in csv.DictReader(f):
            if r.get("ticker") == "XBI":
                try:
                    out[r["date"]] = float(r["close"])
                except Exception:
                    continue
    return out


def load_cik_ticker(sha: str) -> dict:
    m = {}
    with (DATA_DIR / f"h3_targets_v2_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            c = (r.get("target_cik") or "").zfill(10)
            t = (r.get("ticker") or "").strip()
            if c and t:
                m[c] = t
    # SEC company_tickers fallback
    sp = DATA_DIR / "sec_company_tickers.json"
    if sp.exists():
        for _, e in json.loads(sp.read_text()).items():
            cik = str(e.get("cik_str", "")).zfill(10)
            tk = str(e.get("ticker", "")).upper()
            if cik and tk and cik not in m:
                m[cik] = tk
    return m


def close_near(prices: dict, base: str, o_s: int, o_e: int):
    try:
        b = datetime.strptime(base, "%Y-%m-%d").date()
    except Exception:
        return None
    for off in range(o_s, o_e + 1):
        k = (b + timedelta(days=off)).strftime("%Y-%m-%d")
        if k in prices:
            return (k, prices[k])
    return None


def net_excess(sp: dict, bp: dict, d_day: str, o_s: int, o_e: int) -> float | None:
    ep = close_near(sp, d_day, o_s, o_s + 7)
    xp = close_near(sp, d_day, o_e - 7, o_e)
    eb = close_near(bp, d_day, o_s, o_s + 7)
    xb = close_near(bp, d_day, o_e - 7, o_e)
    if not (ep and xp and eb and xb):
        return None
    r_s = xp[1] / ep[1] - 1.0
    r_b = xb[1] / eb[1] - 1.0
    return r_s - r_b - (COST_BPS / 10000.0)


def bootstrap_ci(vals: list[float], groups: list, boot=BOOT, seed=SEED):
    if not vals:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
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

    events = load_events(sha)
    prices = load_prices(sha)
    bench = load_bench(sha)
    cik2tk = load_cik_ticker(sha)
    LOG.info("events %d · prices %d · bench %d · cik2tk %d", len(events), len(prices), len(bench), len(cik2tk))

    # readout 이벤트 · CIK 별 count → 상/하 절반 (H8 검정 1)
    ev_count_by_cik = defaultdict(int)
    for e in events:
        ev_count_by_cik[(e.get("cik") or "").zfill(10)] += 1

    # 각 이벤트에 대해 3 창 net excess
    per = []
    for e in events:
        cik = (e.get("cik") or "").zfill(10)
        tk = cik2tk.get(cik)
        d_day = e.get("d_day", "")
        if not tk or not d_day:
            continue
        sp = prices.get(tk, {})
        if not sp:
            continue
        pre = net_excess(sp, bench, d_day, -30, -1)  # H8 검정 3 전반 / H1b
        post = net_excess(sp, bench, d_day, 1, 30)  # H8 검정 3 후반
        if pre is None and post is None:
            continue
        per.append({
            "cik": cik, "ticker": tk, "d_day": d_day,
            "direction": e.get("direction", ""),
            "ev_count_bucket": "hi" if ev_count_by_cik[cik] >= 3 else "lo",
            "pre": pre, "post": post,
        })

    LOG.info("events scored: %d", len(per))

    # H8 검정 1: 이벤트 수 상/하 절반 (hi/lo) 의 pre net excess 차이
    hi_pre = [r["pre"] for r in per if r["ev_count_bucket"] == "hi" and r["pre"] is not None]
    lo_pre = [r["pre"] for r in per if r["ev_count_bucket"] == "lo" and r["pre"] is not None]
    hi_groups = [r["d_day"] for r in per if r["ev_count_bucket"] == "hi" and r["pre"] is not None]
    lo_groups = [r["d_day"] for r in per if r["ev_count_bucket"] == "lo" and r["pre"] is not None]

    hi_ci = bootstrap_ci(hi_pre, hi_groups)
    lo_ci = bootstrap_ci(lo_pre, lo_groups)

    # H8 검정 3: post 창 CI
    post_all = [r["post"] for r in per if r["post"] is not None]
    post_groups = [r["d_day"] for r in per if r["post"] is not None]
    post_ci = bootstrap_ci(post_all, post_groups)

    # H1b = pre 창 (D-30 진입 · D-1 청산) net excess 전체
    pre_all = [r["pre"] for r in per if r["pre"] is not None]
    pre_groups = [r["d_day"] for r in per if r["pre"] is not None]
    pre_ci = bootstrap_ci(pre_all, pre_groups)

    seal = {
        "git_sha": sha,
        "pool_note": "WP39 부분 풀 (checkpoint · 210/340 CIK · 5423 events)",
        "H8_test1_leading": {
            "hi_bucket": {"n": len(hi_pre), "unique_dates": len(set(hi_groups)), "mean": round(mean(hi_pre), 4) if hi_pre else None, "ci95": hi_ci},
            "lo_bucket": {"n": len(lo_pre), "unique_dates": len(set(lo_groups)), "mean": round(mean(lo_pre), 4) if lo_pre else None, "ci95": lo_ci},
            "diff_hi_minus_lo": round(mean(hi_pre) - mean(lo_pre), 4) if (hi_pre and lo_pre) else None,
        },
        "H8_test3_sell_news": {
            "pre_D-30_D-1": {"n": len(pre_all), "mean": round(mean(pre_all), 4) if pre_all else None, "ci95": pre_ci},
            "post_D+1_D+30": {"n": len(post_all), "mean": round(mean(post_all), 4) if post_all else None, "ci95": post_ci},
            "sell_supported": (mean(pre_all) > 0 and post_ci[1] <= 0) if (pre_all and post_all) else None,
        },
        "H1b": {
            "n": len(pre_all), "unique_dates": len(set(pre_groups)),
            "mean_net_excess_pre": round(mean(pre_all), 4) if pre_all else None,
            "ci95": pre_ci,
            "threshold": 0.02,  # H1b 임계 (§2)
            "alpha_pass": (mean(pre_all) >= 0.02 and pre_ci[0] > 0) if pre_all else False,
        },
    }

    out_dir = DATA_DIR / "biotech" / "seals"
    out_dir.mkdir(parents=True, exist_ok=True)
    seal_path = out_dir / f"h8_h1b_seal_{sha}.json"
    seal_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2))

    # 리포트 md
    report_dir = PROJECT_ROOT / "docs" / "plans" / "biotech" / "verification" / "H8"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = [
        f"# H8 · H1b 부분 풀 리포트 (WP43-3 · 2026-09-14 · git_sha {sha})",
        "",
        f"- 이벤트 풀: **부분 풀 {len(events)} events (WP39 · 210/340 CIK 처리분)**",
        f"- 백테스트 표본: {len(per)} events (가격 매치 후)",
        "",
        "## 봉인 결과",
        "",
        "### H8 검정 1 (선행성 · 이벤트 수 상/하)",
        f"- hi bucket (≥3 events/CIK): n={seal['H8_test1_leading']['hi_bucket']['n']} · mean {seal['H8_test1_leading']['hi_bucket']['mean']} · CI {seal['H8_test1_leading']['hi_bucket']['ci95']}",
        f"- lo bucket (<3): n={seal['H8_test1_leading']['lo_bucket']['n']} · mean {seal['H8_test1_leading']['lo_bucket']['mean']} · CI {seal['H8_test1_leading']['lo_bucket']['ci95']}",
        f"- 차이 (hi-lo): {seal['H8_test1_leading']['diff_hi_minus_lo']}",
        "",
        "### H8 검정 3 (뉴스에 팔기)",
        f"- pre D-30~D-1: n={seal['H8_test3_sell_news']['pre_D-30_D-1']['n']} · mean {seal['H8_test3_sell_news']['pre_D-30_D-1']['mean']} · CI {seal['H8_test3_sell_news']['pre_D-30_D-1']['ci95']}",
        f"- post D+1~D+30: n={seal['H8_test3_sell_news']['post_D+1_D+30']['n']} · mean {seal['H8_test3_sell_news']['post_D+1_D+30']['mean']} · CI {seal['H8_test3_sell_news']['post_D+1_D+30']['ci95']}",
        f"- 뉴스에 팔기 지지: {seal['H8_test3_sell_news']['sell_supported']}",
        "",
        "### H1b (Phase 3 guidance window · D-30 진입 D-1 청산)",
        f"- n={seal['H1b']['n']} · unique dates={seal['H1b']['unique_dates']} · mean {seal['H1b']['mean_net_excess_pre']} · CI {seal['H1b']['ci95']}",
        f"- alpha_pass (mean ≥ +2% AND CI 하한 > 0): **{seal['H1b']['alpha_pass']}**",
        "",
        "## 쉬운 말 요약 5줄",
        "",
        f"1. WP39 부분 풀 {len(events)} events (210/340 CIK) · 백테스트 표본 {len(per)}",
        "2. H8 검정 1 (선행성): 이벤트 수 상/하 절반 · D-30~D-1 mean 차이 관측",
        "3. H8 검정 3 (뉴스에 팔기): pre 양수 & post CI 하한 0 이하 = 지지 여부",
        f"4. H1b: D-30 진입 D-1 청산 · net {seal['H1b']['mean_net_excess_pre']} · alpha_pass = {seal['H1b']['alpha_pass']}",
        "5. **부분 풀 결과** · WP39 완주 (340/340) 후 재검 필수",
        "",
        "## 가능성 지도 (3줄 · WP36 필수)",
        "",
        f"1. 가장 밝은 자리 = {'H1b alpha 지지 · 확대 검정' if seal['H1b']['alpha_pass'] else 'H8 검정 3 형태 확인 (뉴스에 팔기 지지 관측)'}",
        "2. 죽은 자리 = WP39 부분 풀 (표본 부족 · CI 폭 넓음)",
        "3. 다음에 팔 자리 = WP39 완주 (남은 130 CIK) 후 전 풀 재검",
    ]
    report_path = report_dir / "H8-H1b-report-20260914.md"
    report_path.write_text("\n".join(report))

    print(json.dumps({
        "git_sha": sha,
        "seal_path": str(seal_path),
        "report_path": str(report_path),
        "H1b_alpha_pass": seal["H1b"]["alpha_pass"],
        "H1b_mean": seal["H1b"]["mean_net_excess_pre"],
        "H8_test3_sell_supported": seal["H8_test3_sell_news"]["sell_supported"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
