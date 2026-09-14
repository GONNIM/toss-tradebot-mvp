"""WP21-2 · H5 매핑 v4 (v3 · 유형 4 근거 26건 전건 철회 · 전 종목 유형 3).

전건 철회 사유: evidence 26건 report_nm 스캔 결과 · 대부분 "단일판매ㆍ공급계약체결" 자율공시로
성분·품목 명시 부재 · GLP-1 성분/원개발사 (NOVO/LILLY 등) 키워드 매치 0건.
→ 사전 커밋 규칙 "유형 4 = 공시 본문에 GLP-1 성분·제품명 또는 원개발사 포함 시만" 위반 없음
→ 전건 철회 · 전 종목 유형 3 (class_effect_only).

사업보고서 본문 파싱은 별건 (문서 원문 취득 · 스캔 규모 대) · 이후 재부여 가능.
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import subprocess
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h5_mapping_v4")

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

    v3 = list(csv.DictReader((DATA_DIR / f"h5_kr_mapping_v3_{sha}.csv").open()))
    rows = []
    for row in v3:
        rows.append({
            "candidate_name": row["candidate_name"],
            "stock_code": row["stock_code"],
            "corp_code": row["corp_code"],
            "pit_entry_quarter": row["pit_entry_quarter"],
            "first_rcept_dt": row["first_rcept_dt"],
            "last_rcept_dt": row["last_rcept_dt"],
            "n_annual_reports_matched": row["n_annual_reports_matched"],
            "h5_type_v4": "3_class_effect_only",
            "type4_status": "withdrawn_no_glp1_evidence",
            "note_v4": "evidence 26건 전건 철회 (report_nm GLP-1 KW 0건 · 사업보고서 본문 파싱 별건)",
        })

    out_path = DATA_DIR / f"h5_kr_mapping_v4_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "companies": len(rows),
        "type_dist_v4": {"3_class_effect_only": len(rows), "4_cdmo": 0},
        "type4_withdrawn": 26,
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
