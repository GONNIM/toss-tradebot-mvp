"""WP41-1 · 643 이벤트 대상 티커 가격 보충 (yfinance 활성 · Tiingo 폐지).

용도:
- EFTS SC 13D 643 events 의 subject CIK 369 → 티커 (h3_targets_v2 + SEC company_tickers)
- 기존 h3_prices_merged 에 없는 활성 티커 → yfinance (adj_close · 2020-01-01~)
- 기존 없는 폐지 티커 → Tiingo (기본 · Q · 5자리 변형)
- 통합기 append · 커버율 n/643 이벤트 기준 보고
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import os
import subprocess
import time
from pathlib import Path

import httpx
import yfinance as yf

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("yfinance").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h41_price_fill")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

TIINGO_KEY = os.getenv("TIINGO_API_KEY", "")


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    efts = list(csv.DictReader((DATA_DIR / f"h3_efts_sc13d_universe_{sha}.csv").open()))
    ciks = sorted({r["subject_cik"] for r in efts})

    # 티커 매핑
    tk_map = {}
    with (DATA_DIR / f"h3_targets_v2_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            c = (r.get("target_cik") or "").zfill(10)
            t = (r.get("ticker") or "").strip()
            listing = r.get("listing_status", "")
            if c and t:
                tk_map[c] = {"ticker": t, "listing": listing}

    sec = json.loads((DATA_DIR / "sec_company_tickers.json").read_text())
    sec_cik2tk = {}
    for _, e in sec.items():
        cik = str(e.get("cik_str", "")).zfill(10)
        tk = str(e.get("ticker", "")).upper()
        if cik and tk:
            sec_cik2tk[cik] = tk

    active_tk = set()
    delisted_tk = set()
    for c in ciks:
        if c in tk_map:
            info = tk_map[c]
            if info["listing"] == "ACTIVE":
                active_tk.add(info["ticker"])
            elif info["listing"] == "DELISTED":
                delisted_tk.add(info["ticker"])
        elif c in sec_cik2tk:
            active_tk.add(sec_cik2tk[c])

    existing = set()
    with (DATA_DIR / f"h3_prices_merged_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            existing.add(r["ticker"])

    need_active = sorted(active_tk - existing)
    need_delisted = sorted(delisted_tk - existing)
    LOG.info("need active (yfinance): %d · need delisted (Tiingo): %d",
             len(need_active), len(need_delisted))

    rows_out = []
    yf_ok = 0
    yf_fail = 0
    for tk in need_active:
        try:
            df = yf.Ticker(tk).history(start="2020-01-01", auto_adjust=True)
            if df is None or df.empty:
                yf_fail += 1
                continue
            yf_ok += 1
            for idx, row in df.iterrows():
                rows_out.append({
                    "ticker": tk,
                    "date": idx.strftime("%Y-%m-%d"),
                    "close": float(row.get("Close", 0)),
                    "source": "yfinance_wp41",
                })
        except Exception as e:
            yf_fail += 1
            LOG.warning("yf fail %s: %s", tk, e)

    tiingo_ok = 0
    tiingo_fail = 0
    if TIINGO_KEY and need_delisted:
        with httpx.Client() as client:
            for tk in need_delisted:
                variants = [tk, tk + "Q"]
                got = False
                for v in variants:
                    try:
                        r = client.get(
                            f"https://api.tiingo.com/tiingo/daily/{v}/prices",
                            params={"startDate": "2020-01-01", "endDate": "2026-09-01",
                                    "format": "json", "token": TIINGO_KEY},
                            timeout=30.0,
                        )
                        if r.status_code == 200:
                            j = r.json()
                            if isinstance(j, list) and j:
                                got = True
                                for e in j:
                                    rows_out.append({
                                        "ticker": tk,
                                        "date": e.get("date", "")[:10],
                                        "close": float(e.get("adjClose", 0)),
                                        "source": f"tiingo_wp41_{v}",
                                    })
                                break
                    except Exception:
                        pass
                    time.sleep(0.3)
                if got:
                    tiingo_ok += 1
                else:
                    tiingo_fail += 1

    # h3_prices_merged 에 append
    merged = DATA_DIR / f"h3_prices_merged_{sha}.csv"
    with merged.open("a", newline="") as f:
        w = csv.writer(f)
        for r in rows_out:
            w.writerow([r["ticker"], r["date"], r["close"], r["source"]])

    # 커버율 재계산 (이벤트 기준)
    new_existing = existing | {r["ticker"] for r in rows_out}
    events_covered = 0
    for r in efts:
        cik = r["subject_cik"]
        info = tk_map.get(cik) or {"ticker": sec_cik2tk.get(cik, "")}
        tk = info.get("ticker", "")
        if tk and tk in new_existing:
            events_covered += 1

    summary = {
        "git_sha": sha,
        "total_events": len(efts),
        "unique_ciks": len(ciks),
        "yfinance_ok": yf_ok, "yfinance_fail": yf_fail,
        "tiingo_ok": tiingo_ok, "tiingo_fail": tiingo_fail,
        "rows_added": len(rows_out),
        "events_covered_after": events_covered,
        "coverage_rate": round(events_covered / max(1, len(efts)), 3),
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
