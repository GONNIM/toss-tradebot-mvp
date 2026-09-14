"""WP31 조건 2 · no_prices 활성 티커 yfinance 보충.

용도:
- h3_events target 중 targets_v2 sic_biotech=True · listing_status=ACTIVE · 티커 존재 · h3_prices_merged 부재 → yfinance 수집
- adj_close · 2020-01-01 ~ 오늘
- 별도 run 파일 저장 · 통합기 재실행 대신 add-on 병합
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yfinance as yf

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("yfinance").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h3_active_fill")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    events = list(csv.DictReader((DATA_DIR / f"h3_events_{sha}.csv").open()))
    targets = {}
    with (DATA_DIR / f"h3_targets_v2_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            targets[r.get("target_cik", "")] = r

    # 기존 h3_prices_merged 티커 집합
    existing = set()
    with (DATA_DIR / f"h3_prices_merged_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            existing.add(r["ticker"])
    LOG.info("existing tickers in merged: %d", len(existing))

    # 이벤트가 있는 activeㆍbiotechㆍ티커존재ㆍ가격부재 티커
    needed: dict[str, dict] = {}
    for ev in events:
        tcik = (ev.get("target_cik") or "").zfill(10)
        tgt = targets.get(tcik) or targets.get(tcik.lstrip("0"))
        if not tgt:
            continue
        if tgt.get("sic_biotech") != "True":
            continue
        if tgt.get("listing_status") != "ACTIVE":
            continue
        ticker = (tgt.get("ticker") or "").strip()
        if not ticker or ticker in existing:
            continue
        needed.setdefault(ticker, tgt)
    LOG.info("tickers to fill: %d", len(needed))

    rows_out = []
    ok = 0
    fail = 0
    for tk in needed:
        try:
            df = yf.Ticker(tk).history(start="2020-01-01", auto_adjust=True)
            if df is None or df.empty:
                fail += 1
                continue
            ok += 1
            for idx, row in df.iterrows():
                rows_out.append({
                    "ticker": tk,
                    "date": idx.strftime("%Y-%m-%d"),
                    "close": float(row.get("Close", 0)),
                    "source": "yfinance_wp31_fill",
                })
        except Exception as e:
            LOG.warning("fail %s: %s", tk, e)
            fail += 1

    run_path = DATA_DIR / f"h3_prices_wp31_fill_{sha}.csv"
    with run_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "date", "close", "source"])
        w.writeheader()
        w.writerows(rows_out)

    # h3_prices_merged 에 append (concat) · dedupe (ticker,date) 최신 우선
    merged_path = DATA_DIR / f"h3_prices_merged_{sha}.csv"
    with merged_path.open("a", newline="") as f:
        w = csv.writer(f)
        for r in rows_out:
            w.writerow([r["ticker"], r["date"], r["close"], r["source"]])

    summary = {
        "git_sha": sha,
        "run_path": str(run_path),
        "tickers_needed": len(needed),
        "success": ok,
        "fail": fail,
        "rows_written": len(rows_out),
        "merged_appended": True,
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
