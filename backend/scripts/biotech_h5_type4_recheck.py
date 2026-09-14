"""WP19-유형4 · DART pblntf_ty=I (거래소공시) 로 유형 4 CDMO 확인.

용도:
- 15사 각각 pblntf_ty=I · 2019~2026 조회
- report_nm 에 "공급계약|위탁생산|기술이전|기술도입|CMO|CDMO" 매치
- 유형 4 배정 근거 rcept_no 저장
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h5_type4")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

DART_BASE = "https://opendart.fss.or.kr/api"
REQ_INTERVAL = 0.3

TYPE4_PATTERNS = ["공급계약", "판매계약", "유통계약", "위탁생산", "기술이전", "기술도입", "라이선스", "CMO", "CDMO", "수탁"]


def git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def load_mapping(sha: str) -> list[dict]:
    with (DATA_DIR / f"h5_kr_mapping_v2_{sha}.csv").open() as f:
        return list(csv.DictReader(f))


def fetch_i(client: httpx.Client, corp_code: str, key: str) -> list[dict]:
    all_rows = []
    for year in range(2019, 2027):
        for start_month, end_month in [("0101", "0630"), ("0701", "1231")]:
            r = client.get(
                f"{DART_BASE}/list.json",
                params={
                    "crtfc_key": key,
                    "corp_code": corp_code,
                    "bgn_de": f"{year}{start_month}",
                    "end_de": f"{year}{end_month}",
                    "pblntf_ty": "I",
                    "page_no": 1,
                    "page_count": 100,
                },
                timeout=30.0,
            )
            r.raise_for_status()
            j = r.json()
            if j.get("status") == "013":
                continue
            if j.get("status") != "000":
                continue
            all_rows.extend(j.get("list", []))
            time.sleep(REQ_INTERVAL)
    return all_rows


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    key = os.getenv("DART_API_KEY", "")
    if not key:
        LOG.error("DART_API_KEY missing")
        sys.exit(1)
    sha = git_sha()

    mapping = load_mapping(sha)
    LOG.info("mapping companies: %d", len(mapping))

    per_company = defaultdict(list)
    with httpx.Client(headers={"User-Agent": "TossTradebot-BiotechRadar/1.0"}) as client:
        for m in mapping:
            name = m["candidate_name"]
            corp = m["corp_code"]
            rows = fetch_i(client, corp, key)
            LOG.info("  %s · pblntf_ty=I total=%d", name, len(rows))
            for row in rows:
                rn = row.get("report_nm", "")
                if any(pat in rn for pat in TYPE4_PATTERNS):
                    per_company[name].append(row)

    # 저장
    out_rows = []
    type4_companies = 0
    for name, rows in per_company.items():
        if not rows:
            continue
        type4_companies += 1
        for r in sorted(rows, key=lambda x: x["rcept_dt"])[:3]:
            out_rows.append({
                "candidate_name": name,
                "rcept_no": r.get("rcept_no"),
                "rcept_dt": r.get("rcept_dt"),
                "report_nm": r.get("report_nm"),
                "flr_nm": r.get("flr_nm"),
            })

    out_path = DATA_DIR / f"h5_type4_evidence_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["candidate_name", "rcept_no", "rcept_dt", "report_nm", "flr_nm"])
        w.writeheader()
        w.writerows(out_rows)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "companies_checked": len(mapping),
        "companies_with_type4_evidence": type4_companies,
        "total_evidence_rows": len(out_rows),
        "companies_with_hits": sorted(per_company.keys()),
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
