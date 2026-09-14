"""WP29 · H1a sponsor 26 재매핑 (name_match 사용 · SEC + Tiingo 병합)."""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts import biotech_name_match as nm

import csv
import json
import logging
import subprocess
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h1a_v4_remap")

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

    idx = nm.load_sec_company_index()
    LOG.info("SEC company index entries: %d", len(idx))

    events = list(csv.DictReader((DATA_DIR / f"h1a_events_v3_2_{sha}.csv").open()))
    stats = {
        "total": 0, "sponsor_recovered": 0,
        "exact_match": 0, "jaccard_candidate": 0,
        "unmatched": 0, "eligible_v4": 0,
    }
    rows = []
    unmatched_samples = []
    for ev in events:
        stats["total"] += 1
        sponsor = ev.get("openfda_sponsor", "")
        if not sponsor:
            rows.append({**ev, "mapped_ticker_v4": "", "match_kind": "no_sponsor"})
            continue
        stats["sponsor_recovered"] += 1
        hit = nm.match_exact(sponsor, idx)
        kind = ""
        ticker = ""
        candidates_str = ""
        if hit:
            ticker = hit["ticker"]
            kind = "exact"
            stats["exact_match"] += 1
        else:
            cands = nm.match_jaccard(sponsor, idx, threshold=0.8)
            if cands:
                candidates_str = "|".join(f"{c[1]['ticker']}:{round(c[0],3)}" for c in cands[:3])
                kind = "jaccard_candidate"
                stats["jaccard_candidate"] += 1
            else:
                kind = "unmatched"
                stats["unmatched"] += 1
                if len(unmatched_samples) < 10:
                    unmatched_samples.append(sponsor)
        v2_eligible = (str(ev.get("eligible", "")) or "").strip().lower() == "true"
        is_drug = (str(ev.get("is_drug_adcom", "")) or "").strip().lower() == "true"
        elig_v4 = v2_eligible and is_drug and bool(ticker)
        if elig_v4:
            stats["eligible_v4"] += 1
        rows.append({
            **ev,
            "mapped_ticker_v4": ticker,
            "match_kind": kind,
            "jaccard_candidates_top3": candidates_str,
            "eligible_v4": elig_v4,
        })

    out_path = DATA_DIR / f"h1a_events_v4_{sha}.csv"
    # 모든 rows 의 fieldnames 합집합 사용 (일부 rows 에 optional 컬럼 부재 시)
    fields = []
    seen = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                fields.append(k)
                seen.add(k)
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            for k in fields:
                r.setdefault(k, "")
            w.writerow(r)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        **stats,
        "eligible_v4_rate": round(stats["eligible_v4"] / max(1, stats["total"]), 4),
        "unmatched_sample": unmatched_samples,
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
