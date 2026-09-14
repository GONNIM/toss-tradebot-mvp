"""WP17-1 · H5 매핑 확정 (h5_dart_scan → h5_kr_mapping v2).

용도:
- WP12 h5_dart_scan_{sha}.csv (사업보고서 GLP-1 언급 raw · 15사 · 63 rows) →
  회사별 유형 배정 + point-in-time 편입 시점 (최초 언급 연도) + 근거 rcept_no.
- 유형 = 3 (동일 클래스 · GLP-1 개발) 또는 4 (CDMO · report_nm 에 CMO/수탁 매치)
- 현대약품 = 연계 확인 (5건) 유형 3 기재
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import subprocess
from collections import defaultdict
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h5_mapping")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

CDMO_KEYWORDS = ["CMO", "CDMO", "수탁", "위탁제조", "위수탁"]


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


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    src = DATA_DIR / f"h5_dart_scan_{sha}.csv"
    if not src.exists():
        LOG.error("source missing: %s", src)
        return

    per_company = defaultdict(list)
    with src.open() as f:
        for row in csv.DictReader(f):
            per_company[row["candidate_name"]].append(row)

    out_rows = []
    type_dist = {"3_class_effect": 0, "4_cdmo": 0}

    for name, rows in per_company.items():
        rows_sorted = sorted(rows, key=lambda r: r["rcept_dt"])
        first = rows_sorted[0]
        last = rows_sorted[-1]

        # 유형 배정: report_nm 에 CDMO 키워드 있으면 4 · 아니면 3
        h5_type = "3_class_effect"
        for r in rows:
            if any(kw in r.get("report_nm", "") for kw in CDMO_KEYWORDS):
                h5_type = "4_cdmo"
                break
        type_dist[h5_type] += 1

        # 최초 편입 시점 = 최초 rcept_dt 의 연-월 (분기 계산용)
        first_dt = first["rcept_dt"]  # YYYYMMDD
        first_year = first_dt[:4]
        first_month = int(first_dt[4:6])
        first_quarter = (first_month - 1) // 3 + 1
        pit_quarter = f"{first_year}Q{first_quarter}"

        # 근거 rcept_no 는 최초 매치 우선
        evidence_rcepts = "|".join(r["rcept_no"] for r in rows_sorted[:3])

        # 특별 주석
        note = ""
        if name == "현대약품":
            note = "License-in/out 후보 미확인 · Class effect 로 임시 배정 · 별건 사업보고서 본문 상세 파싱 필요"

        out_rows.append({
            "candidate_name": name,
            "stock_code": first["stock_code"],
            "corp_code": first["corp_code"],
            "h5_type": h5_type,
            "pit_entry_quarter": pit_quarter,
            "first_rcept_dt": first_dt,
            "last_rcept_dt": last["rcept_dt"],
            "evidence_rcept_no_top3": evidence_rcepts,
            "n_annual_reports_matched": len(rows),
            "note": note,
        })

    out_path = DATA_DIR / f"h5_kr_mapping_v2_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "candidate_name", "stock_code", "corp_code", "h5_type",
            "pit_entry_quarter", "first_rcept_dt", "last_rcept_dt",
            "evidence_rcept_no_top3", "n_annual_reports_matched", "note",
        ])
        w.writeheader()
        w.writerows(out_rows)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "companies": len(out_rows),
        "type_dist": type_dist,
        "pit_entry_distribution": {
            row["candidate_name"]: row["pit_entry_quarter"] for row in out_rows
        },
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
