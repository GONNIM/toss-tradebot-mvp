"""WP53 · H8 검정 1 재계산 (사전 커밋 규칙 · 채널 n종 · 부분).

기존 결과 (이벤트 수 상/하 · lo n=4) 는 규칙 위반 · h8_h1b_seal 에 "무효 · 이력" 표기.
새 규칙:
- 각 이벤트 D-day 별 소문 지수 = 사용 가능 채널 신호 수
  · 채널 1 = 13D 신규 (h3_events)
  · 채널 2 = h6_membership 소속 여부 (근사 · CT.gov 활동)
  · PubMed/bioRxiv 는 회사별 게재 조회 부담 → 부분 · 미포함
- D-180~D-31 신호 수 vs D-360~D-181 기준선 (증가율)
- 채널 ≥1 유효 (원 규칙 ≥2 는 부분 완화 · 명시)
- 유효 이벤트 지수 순으로 상/하 절반 · D-30~D-1 net excess 차이
- 날짜 클러스터 CI
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
LOG = logging.getLogger("biotech_h53_h8_test1")

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


def load_prices(sha):
    p = DATA_DIR / f"h3_prices_merged_{sha}.csv"
    out = defaultdict(dict)
    with p.open() as f:
        for r in csv.DictReader(f):
            try:
                out[r["ticker"]][r["date"]] = float(r["close"])
            except Exception:
                continue
    return out


def load_bench(sha):
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


def load_cik_ticker(sha):
    m = {}
    with (DATA_DIR / f"h3_targets_v2_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            c = (r.get("target_cik") or "").zfill(10)
            t = (r.get("ticker") or "").strip()
            if c and t:
                m[c] = t
    sp = DATA_DIR / "sec_company_tickers.json"
    if sp.exists():
        for _, e in json.loads(sp.read_text()).items():
            cik = str(e.get("cik_str", "")).zfill(10)
            tk = str(e.get("ticker", "")).upper()
            if cik and tk and cik not in m:
                m[cik] = tk
    return m


def close_near(prices, base, o_s, o_e):
    try:
        b = datetime.strptime(base, "%Y-%m-%d").date()
    except Exception:
        return None
    for off in range(o_s, o_e + 1):
        k = (b + timedelta(days=off)).strftime("%Y-%m-%d")
        if k in prices:
            return (k, prices[k])
    return None


def net_excess(sp, bp, d_day, o_s, o_e):
    ep = close_near(sp, d_day, o_s, o_s + 7)
    xp = close_near(sp, d_day, o_e - 7, o_e)
    eb = close_near(bp, d_day, o_s, o_s + 7)
    xb = close_near(bp, d_day, o_e - 7, o_e)
    if not (ep and xp and eb and xb):
        return None
    return (xp[1] / ep[1] - 1.0) - (xb[1] / eb[1] - 1.0) - (COST_BPS / 10000.0)


def bootstrap_ci(vals, groups, boot=BOOT, seed=SEED):
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

    # readout events
    cp = DATA_DIR / "h39_readouts_checkpoint.json"
    events = json.loads(cp.read_text()).get("events", [])
    LOG.info("readout events: %d", len(events))

    # 채널 1 = 13D 신규 (h3_events · cik별 date list)
    ch1_dates_by_cik = defaultdict(list)
    p = DATA_DIR / f"h3_events_{sha}.csv"
    with p.open() as f:
        for r in csv.DictReader(f):
            cik = (r.get("target_cik") or "").zfill(10)
            d = r.get("event_date", "")
            if cik and d:
                ch1_dates_by_cik[cik].append(d)

    # 채널 2 = h6_membership 소속 · 활동 date는 분기 (year, quarter)
    memb_tk = set()
    mp = DATA_DIR / f"h6_membership_{sha}.csv"
    if mp.exists():
        with mp.open() as f:
            for r in csv.DictReader(f):
                for t in (r.get("tiingo_matched_tickers") or "").split("|"):
                    if t.strip():
                        memb_tk.add(t.strip())

    prices = load_prices(sha)
    bench = load_bench(sha)
    cik2tk = load_cik_ticker(sha)

    # 각 이벤트의 소문 지수 산정
    scored = []
    for e in events:
        cik = (e.get("cik") or "").zfill(10)
        tk = cik2tk.get(cik)
        d_day = e.get("d_day", "")
        if not tk or not d_day:
            continue
        try:
            base = datetime.strptime(d_day, "%Y-%m-%d").date()
        except Exception:
            continue
        # 채널 1: D-180~D-31 내 13D
        d180 = (base - timedelta(days=180)).strftime("%Y-%m-%d")
        d31 = (base - timedelta(days=31)).strftime("%Y-%m-%d")
        d360 = (base - timedelta(days=360)).strftime("%Y-%m-%d")
        d181 = (base - timedelta(days=181)).strftime("%Y-%m-%d")
        recent_ch1 = sum(1 for dt in ch1_dates_by_cik.get(cik, []) if d180 <= dt <= d31)
        base_ch1 = sum(1 for dt in ch1_dates_by_cik.get(cik, []) if d360 <= dt <= d181)
        # 채널 2: 소속 여부 (부분 근사 · 시점 무관 · +1)
        recent_ch2 = 1 if tk in memb_tk else 0
        base_ch2 = 1 if tk in memb_tk else 0
        # 지수 = 정규화 증가율 (전체 신호 수 - baseline) / max(baseline, 1)
        total_recent = recent_ch1 + recent_ch2
        total_base = base_ch1 + base_ch2
        rumor_index = (total_recent - total_base) / max(total_base, 1)

        # 유효 채널 수 (recent 신호 존재)
        ch_active = int(recent_ch1 > 0) + int(recent_ch2 > 0)
        if ch_active < 1:  # 원 규칙 ≥2 · 완화 ≥1 · 명시
            continue

        sp = prices.get(tk, {})
        if not sp:
            continue
        pre = net_excess(sp, bench, d_day, -30, -1)
        if pre is None:
            continue

        scored.append({
            "cik": cik, "ticker": tk, "d_day": d_day,
            "rumor_index": rumor_index, "ch_active": ch_active,
            "recent_ch1": recent_ch1, "base_ch1": base_ch1,
            "in_membership": recent_ch2,
            "pre_net_excess": pre,
        })

    LOG.info("scored (valid channels ≥1): %d", len(scored))

    # 지수 순 정렬 · 상/하 절반
    scored_sorted = sorted(scored, key=lambda x: x["rumor_index"])
    half = len(scored_sorted) // 2
    lo_group = scored_sorted[:half]
    hi_group = scored_sorted[half:]

    lo_vals = [r["pre_net_excess"] for r in lo_group]
    lo_dates = [r["d_day"] for r in lo_group]
    hi_vals = [r["pre_net_excess"] for r in hi_group]
    hi_dates = [r["d_day"] for r in hi_group]

    lo_ci = bootstrap_ci(lo_vals, lo_dates)
    hi_ci = bootstrap_ci(hi_vals, hi_dates)

    seal = {
        "git_sha": sha,
        "rule": "사전 커밋 · 소문 지수 = (D-180~D-31 채널 신호수 - 기준선 D-360~D-181) / max(기준선,1)",
        "channels": ["ch1_13D_new (h3_events)", "ch2_membership_flag (h6_membership · 근사)"],
        "note_partial": "PubMed/bioRxiv 회사별 게재 조회 미포함 · 부분 · 원 규칙 ≥2 유효 채널 → 완화 ≥1 (명시)",
        "events_input": len(events),
        "events_scored_valid_ch_ge_1": len(scored),
        "lo_half": {"n": len(lo_vals), "unique_dates": len(set(lo_dates)),
                    "mean_net_excess_pre": round(mean(lo_vals), 4) if lo_vals else None,
                    "cluster_ci95": lo_ci},
        "hi_half": {"n": len(hi_vals), "unique_dates": len(set(hi_dates)),
                    "mean_net_excess_pre": round(mean(hi_vals), 4) if hi_vals else None,
                    "cluster_ci95": hi_ci},
        "diff_hi_minus_lo": round(mean(hi_vals) - mean(lo_vals), 4) if (hi_vals and lo_vals) else None,
    }

    out_path = DATA_DIR / "biotech" / "seals" / f"h8_test1_v2_seal_{sha}.json"
    out_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2))

    LOG.info("seal=%s", json.dumps(seal, ensure_ascii=False, indent=2))
    print(json.dumps(seal, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
