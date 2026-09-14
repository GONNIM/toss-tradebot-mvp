"""WP19 · H5 매핑 v3 (v2 + 유형 4 근거 병기)."""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import subprocess
from collections import defaultdict
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h5_mapping_v3")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"


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

    v2 = list(csv.DictReader((DATA_DIR / f"h5_kr_mapping_v2_{sha}.csv").open()))
    ev = list(csv.DictReader((DATA_DIR / f"h5_type4_evidence_{sha}.csv").open()))

    ev_by_company = defaultdict(list)
    for row in ev:
        ev_by_company[row["candidate_name"]].append(row)

    out_rows = []
    type_dist = {"3_class_effect_only": 0, "3_plus_4_evidence": 0}
    for m in v2:
        name = m["candidate_name"]
        evs = ev_by_company.get(name, [])
        type4_flag = bool(evs)
        type4_top3_rcept = "|".join(sorted({e["rcept_no"] for e in evs[:3]}))
        h5_type_v3 = "3_class_effect + 4_supply/license_evidence" if type4_flag else "3_class_effect_only"
        if type4_flag:
            type_dist["3_plus_4_evidence"] += 1
        else:
            type_dist["3_class_effect_only"] += 1
        out_rows.append({
            **m,
            "h5_type_v3": h5_type_v3,
            "type4_evidence_count": len(evs),
            "type4_top3_rcept": type4_top3_rcept,
        })

    out_path = DATA_DIR / f"h5_kr_mapping_v3_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "companies": len(out_rows),
        "type_dist_v3": type_dist,
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
