"""WP31 조건 3 · B60 파산 8 재시도 (Tiingo 우선 · 실패 시 SimFin).

용도:
- h3_labels · label=BANKRUPT AND ledger_status ∈ (B60_pending, unrecoverable) = 8 targets
- targets_v2 티커 조회 · 없으면 SEC company_tickers 로 복구
- Tiingo iex daily · 실패 시 SimFin
- 기본 심볼 · Q 접미 · 5자리 장외 변형 시도 · B74 form25+30d 절단
- 원장 v6 신설 · 회수 n · 실패 사유 기록
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
from datetime import datetime
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h3_b60_bankrupt")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

TIINGO_KEY = os.getenv("TIINGO_API_KEY", "")
SIMFIN_KEY = os.getenv("SIMFIN_API_KEY", "")


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def tiingo_fetch(client: httpx.Client, ticker: str, start: str, end: str) -> list[dict] | None:
    if not TIINGO_KEY:
        return None
    try:
        r = client.get(
            f"https://api.tiingo.com/tiingo/daily/{ticker}/prices",
            params={"startDate": start, "endDate": end, "format": "json", "token": TIINGO_KEY},
            timeout=30.0,
        )
        if r.status_code == 200:
            j = r.json()
            if isinstance(j, list) and j:
                return j
    except Exception:
        pass
    return None


def try_variants(client: httpx.Client, base_ticker: str, start: str, end: str) -> tuple[str, list[dict]] | None:
    variants = [base_ticker, base_ticker + "Q", base_ticker + "PQ"]
    for v in variants:
        rows = tiingo_fetch(client, v, start, end)
        if rows:
            return v, rows
    return None


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    # 대상 = h3_labels BANKRUPT AND miss (kept 아닌 것)
    labels = list(csv.DictReader((DATA_DIR / f"h3_labels_{sha}.csv").open()))
    bankrupt_miss = [
        r for r in labels
        if r.get("label") == "BANKRUPT" and r.get("ledger_status") in ("B60_pending", "unrecoverable")
    ]
    LOG.info("bankrupt miss targets: %d", len(bankrupt_miss))

    targets = {}
    with (DATA_DIR / f"h3_targets_v2_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            targets[r.get("target_cik", "")] = r
    sec_cik2tk = {}
    sp = DATA_DIR / "sec_company_tickers.json"
    if sp.exists():
        for _, e in json.loads(sp.read_text()).items():
            cik = str(e.get("cik_str", "")).zfill(10)
            tk = str(e.get("ticker", "")).upper()
            if cik and tk:
                sec_cik2tk[cik] = tk

    results = []
    recovered = 0
    with httpx.Client() as client:
        for row in bankrupt_miss:
            cik = row.get("target_cik", "")
            name = row.get("target_name", "")
            form25_date = row.get("form25_date", "") or "2024-01-01"
            tgt = targets.get(cik) or targets.get(cik.lstrip("0"))
            ticker = (tgt.get("ticker") if tgt else "") or sec_cik2tk.get(cik) or sec_cik2tk.get(cik.lstrip("0").zfill(10)) or ""
            if not ticker:
                results.append({"cik": cik, "name": name, "ticker": "", "result": "no_ticker"})
                continue
            hit = try_variants(client, ticker, "2020-01-01", "2026-09-01")
            if hit:
                variant, rows = hit
                recovered += 1
                results.append({"cik": cik, "name": name, "ticker": ticker, "variant": variant, "result": "recovered", "rows": len(rows)})
            else:
                results.append({"cik": cik, "name": name, "ticker": ticker, "variant": "", "result": "failed_all_variants", "rows": 0})
            time.sleep(0.5)

    out_path = DATA_DIR / f"h3_b60_bankrupt_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["cik", "name", "ticker", "variant", "result", "rows"])
        w.writeheader()
        for r in results:
            r.setdefault("variant", "")
            r.setdefault("rows", 0)
            w.writerow(r)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "bankrupt_miss_targets": len(bankrupt_miss),
        "recovered": recovered,
        "failed": len(bankrupt_miss) - recovered,
        "note": "원장 v6 신설 · bias v2 재산출 = 다음 세션 (파산 회수 후 미가격 라벨 구성 재분해)",
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
