"""WP31 조건 1 · h3_events 제외 분해 (no_ticker_in_targets 119 등).

이벤트별 사유:
- (a) 비바이오 SIC: target_cik 이 h3_targets_v2 에 있으나 sic_biotech=False
- (b) 폐지·미가격: 원장 v5 status ∈ {B60_pending, unrecoverable}
- (c) 활성이나 티커 공백: targets_v2 존재 + biotech + listing_status=ACTIVE + ticker 공백
- (d) 기타
(c) 는 SEC company_tickers.json (WP29 캐시) 로 티커 복구 시도.
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import subprocess
from collections import defaultdict
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h3_excluded_breakdown")

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
    ledger = {}
    lp = DATA_DIR / f"h3_delisted_ledger_v5_{sha}.csv"
    if lp.exists():
        with lp.open() as f:
            for r in csv.DictReader(f):
                ledger[r.get("target_cik", "")] = r.get("status", "")
    # SEC company_tickers · cik → ticker
    sec_cik2tk = {}
    sp = DATA_DIR / "sec_company_tickers.json"
    if sp.exists():
        data = json.loads(sp.read_text())
        for _, e in data.items():
            cik = str(e.get("cik_str", "")).zfill(10)
            tk = str(e.get("ticker", "")).upper()
            if cik and tk:
                sec_cik2tk[cik] = tk

    breakdown = defaultdict(int)
    per_event = []
    recovered_tickers = []

    for ev in events:
        tcik = (ev.get("target_cik") or "").zfill(10)
        tgt = targets.get(tcik) or targets.get(tcik.lstrip("0"))
        ledger_status = ledger.get(tcik) or ledger.get(tcik.lstrip("0"))

        cause = "d_other"
        recovered = ""
        if not tgt:
            cause = "d_other_target_not_in_v2"
        else:
            ticker = (tgt.get("ticker") or "").strip()
            sic_bio = tgt.get("sic_biotech") == "True"
            listing = tgt.get("listing_status", "")
            if not sic_bio:
                cause = "a_non_biotech_sic"
            elif ledger_status in ("B60_pending", "unrecoverable"):
                cause = "b_delisted_no_price"
            elif listing == "ACTIVE" and not ticker:
                cause = "c_active_missing_ticker"
                # SEC company_tickers 로 복구
                recovered = sec_cik2tk.get(tcik) or sec_cik2tk.get(tcik.lstrip("0").zfill(10)) or ""
                if recovered:
                    recovered_tickers.append({"cik": tcik, "ticker": recovered, "name": tgt.get("target_name", "")})
            elif ticker:
                cause = "z_included_has_ticker"  # 사실 제외 아님 (dry-run 다른 필터에서 걸림)
            else:
                cause = "d_other_delisted_with_ticker"
        breakdown[cause] += 1
        per_event.append({
            "event_id": ev.get("event_id"),
            "target_cik": tcik,
            "cause": cause,
            "ticker_recovered": recovered,
        })

    out_path = DATA_DIR / f"h3_excluded_breakdown_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per_event[0].keys()))
        w.writeheader()
        w.writerows(per_event)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "cause_dist": dict(breakdown),
        "ticker_recovered_count": len(recovered_tickers),
        "recovered_sample": recovered_tickers[:10],
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
