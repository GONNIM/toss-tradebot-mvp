"""WP30 · H3 관문 1 dry-run (13D/13G 346 · 원장 v5 · h3_mcap · 시총 필터).

용도:
- h3_events (13D_new 50 + 13G_new 296 = 346)
- 원장 v5 (kept 50 + simfin_kept 42 = 가격 확보 92 · 미가격 48)
- h3_mcap (companyfacts 발행주식수 이벤트일 최근접)
- h3_prices_merged (가격 시계열)
- 시총 = shares × 원시 종가 · $50M ~ $5B 필터
- 창 D+1~D+30 · D+1~D+180
- 표본 n · 제외 분해 (no_prices · not_in_ledger_kept · mcap_out_of_range · entry_lag)
- 버킷 (mcap 3구간 × subsector SIC 2834/2836/other)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h3_dry_run_v2")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

MCAP_BUCKETS = [
    ("50M_300M", 50e6, 300e6),
    ("300M_1B", 300e6, 1e9),
    ("1B_5B", 1e9, 5e9),
]
HORIZONS = [30, 180]


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_events(sha: str) -> list[dict]:
    p = DATA_DIR / f"h3_events_{sha}.csv"
    with p.open() as f:
        return list(csv.DictReader(f))


def load_ledger(sha: str) -> dict[str, dict]:
    p = DATA_DIR / f"h3_delisted_ledger_v5_{sha}.csv"
    out = {}
    if p.exists():
        with p.open() as f:
            for r in csv.DictReader(f):
                out[r.get("target_cik", "")] = r
    return out


def load_targets(sha: str) -> dict[str, dict]:
    p = DATA_DIR / f"h3_targets_v2_{sha}.csv"
    out = {}
    with p.open() as f:
        for r in csv.DictReader(f):
            out[r.get("target_cik", "")] = r
    return out


def load_mcap(sha: str) -> dict[str, float]:
    p = DATA_DIR / f"h3_mcap_{sha}.csv"
    out = {}
    with p.open() as f:
        for r in csv.DictReader(f):
            try:
                shares = float(r.get("shares", "") or 0)
            except Exception:
                shares = 0.0
            if shares > 0:
                out[r["cik"]] = shares
    return out


def load_prices(sha: str) -> dict[str, dict[str, float]]:
    p = DATA_DIR / f"h3_prices_merged_{sha}.csv"
    out: dict[str, dict[str, float]] = defaultdict(dict)
    with p.open() as f:
        for r in csv.DictReader(f):
            try:
                out[r["ticker"]][r["date"]] = float(r.get("close", "") or 0)
            except Exception:
                continue
    return out


def has_bar_within(prices: dict[str, float], base: str, delta_days_from: int, delta_days_to: int) -> bool:
    try:
        b = datetime.strptime(base, "%Y-%m-%d").date()
    except Exception:
        return False
    for offset in range(delta_days_from, delta_days_to + 1):
        k = (b + timedelta(days=offset)).strftime("%Y-%m-%d")
        if k in prices:
            return True
    return False


def entry_price_close(prices: dict[str, float], event_date: str) -> tuple[str, float] | None:
    """D+1 종가 (첫 거래일 · +1 부터 +7)."""
    try:
        b = datetime.strptime(event_date, "%Y-%m-%d").date()
    except Exception:
        return None
    for offset in range(1, 8):
        k = (b + timedelta(days=offset)).strftime("%Y-%m-%d")
        if k in prices:
            return (k, prices[k])
    return None


def mcap_bucket(mcap: float) -> str:
    for name, lo, hi in MCAP_BUCKETS:
        if lo <= mcap < hi:
            return name
    return "out_of_range"


def subsector(sic: str) -> str:
    if sic == "2834":
        return "2834_pharma"
    if sic == "2836":
        return "2836_biologics"
    return "other"


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    events = load_events(sha)
    ledger = load_ledger(sha)
    targets = load_targets(sha)
    mcap = load_mcap(sha)
    prices = load_prices(sha)
    LOG.info("events=%d · ledger=%d · targets=%d · mcap=%d · prices tickers=%d",
             len(events), len(ledger), len(targets), len(mcap), len(prices))

    per_horizon = {h: {"eligible": 0, "shortened_expected": 0} for h in HORIZONS}
    excluded = defaultdict(int)
    buckets = defaultdict(lambda: defaultdict(int))  # {(mcap_bkt, subsector): {horizon: count}}
    excluded_examples = defaultdict(list)

    for ev in events:
        tcik = (ev.get("target_cik") or "").zfill(10)
        etype = ev.get("event_type", "")
        edate = ev.get("event_date", "")
        tgt = targets.get(tcik) or targets.get(tcik.lstrip("0"))
        # ticker · sic · form25_date
        ticker = ""
        sic = ""
        form25_date = None
        if tgt:
            ticker = (tgt.get("ticker") or "").strip()
            sic = (tgt.get("sic") or "").strip()
            form25_date = tgt.get("form25_date") or None

        if not ticker:
            excluded["no_ticker_in_targets"] += 1
            continue
        stock_prices = prices.get(ticker) or prices.get(ticker.upper()) or {}
        if not stock_prices:
            excluded["no_prices_merged"] += 1
            if len(excluded_examples["no_prices_merged"]) < 5:
                excluded_examples["no_prices_merged"].append(f"{tcik}·{ticker}·{etype}·{edate}")
            continue

        entry = entry_price_close(stock_prices, edate)
        if entry is None:
            excluded["no_entry_within_7d"] += 1
            continue

        # mcap 필터
        m_shares = mcap.get(tcik) or mcap.get(tcik.lstrip("0"))
        if not m_shares:
            excluded["no_mcap_shares"] += 1
            continue
        mcap_val = entry[1] * m_shares
        bkt = mcap_bucket(mcap_val)
        if bkt == "out_of_range":
            excluded["mcap_out_of_range_50M_5B"] += 1
            continue

        sub = subsector(sic)

        # 각 horizon 별 shortened 예상 (마지막 바 < 목표일)
        for h in HORIZONS:
            per_horizon[h]["eligible"] += 1
            # shortened: 창 안에 마지막 바가 있는지
            has_end = has_bar_within(stock_prices, edate, h - 15, h + 15)
            if not has_end:
                per_horizon[h]["shortened_expected"] += 1
            buckets[(bkt, sub)][h] += 1

    # 버킷 표
    bucket_summary = {
        f"{b[0]}__{b[1]}": {f"h_{h}d": v.get(h, 0) for h in HORIZONS}
        for b, v in buckets.items()
    }

    summary = {
        "git_sha": sha,
        "events_total": len(events),
        "per_horizon": per_horizon,
        "excluded_breakdown": dict(excluded),
        "buckets_mcap_x_subsector": bucket_summary,
        "excluded_examples_sample": {k: v[:5] for k, v in excluded_examples.items()},
        "gate_status": "관문 1 (H3) 검수 요청 · 백테스트 본 실행 금지",
    }

    out_path = DATA_DIR / f"h3_dry_run_summary_{sha}.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
