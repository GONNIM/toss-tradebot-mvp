"""WP1-B bg3 · B95 라벨 (140 폐지 target · label_from_filings) → h3_bias_analysis.

용도:
- h3_targets_v2 listing_status=DELISTED 140 각각 submissions 로드
- 8-K item_codes · DEFM14A · SC 14D9 목록 추출
- label_from_filings (form25_date 제공) → BANKRUPT/ACQUIRED/OTHER_DELISTED
- h3_bias_analysis · 원장 v5 참조 · 가격 92 vs 미가격 48 구성 비교
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_sec_common import (
    SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING, REQ_INTERVAL, SecBlockedError,
    label_from_filings,
)

import csv
import json
import logging
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h3_labels_b95")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
CHECKPOINT = DATA_DIR / "h3_labels_b95_checkpoint.json"

SUBMISSIONS = "https://data.sec.gov/submissions"


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


def load_delisted_targets(sha: str) -> list[dict]:
    p = DATA_DIR / f"h3_targets_v2_{sha}.csv"
    with p.open() as f:
        return [r for r in csv.DictReader(f) if r.get("sic_biotech") == "True" and r.get("listing_status") == "DELISTED"]


def load_ledger_status(sha: str) -> dict[str, str]:
    """h3_delisted_ledger_v5 target_cik → status."""
    p = DATA_DIR / f"h3_delisted_ledger_v5_{sha}.csv"
    if not p.exists():
        return {}
    out = {}
    with p.open() as f:
        for r in csv.DictReader(f):
            out[r.get("target_cik", "")] = r.get("status", "")
    return out


def sec_get(client: httpx.Client, url: str) -> httpx.Response:
    time.sleep(REQ_INTERVAL)
    r = client.get(url, timeout=30.0)
    if r.status_code == 403:
        raise SecBlockedError(f"403 · {url[:80]}")
    return r


def collect_filings_for_label(subs: dict) -> list[dict]:
    recent = subs.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    items = recent.get("items", [])
    out = []
    for i, f in enumerate(forms):
        it_str = items[i] if i < len(items) else ""
        item_codes = [x.strip() for x in it_str.split(",")] if it_str else []
        out.append({"form": f, "date": dates[i] if i < len(dates) else "", "item_codes": item_codes})
    return out


def load_ck() -> dict:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"processed": [], "labels": []}


def save_ck(ck: dict):
    CHECKPOINT.write_text(json.dumps(ck, ensure_ascii=False, indent=2))


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    LOG.info("git_sha=%s", sha)

    targets = load_delisted_targets(sha)
    ledger = load_ledger_status(sha)
    LOG.info("delisted targets: %d · ledger entries: %d", len(targets), len(ledger))

    ck = load_ck()
    processed = set(ck.get("processed", []))
    labels = ck.get("labels", [])

    label_dist = defaultdict(int)

    try:
        with httpx.Client(headers={"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}, timeout=30.0) as client:
            for t in targets:
                cik = (t.get("target_cik") or "").zfill(10)
                if cik in processed or not cik or cik == "0000000000":
                    continue
                r = sec_get(client, f"{SUBMISSIONS}/CIK{cik}.json")
                if r.status_code != 200:
                    labels.append({"target_cik": cik, "label": "OTHER_DELISTED", "reason": f"submissions HTTP {r.status_code}"})
                    label_dist["OTHER_DELISTED"] += 1
                    processed.add(cik)
                    continue
                try:
                    subs = r.json()
                except Exception:
                    labels.append({"target_cik": cik, "label": "OTHER_DELISTED", "reason": "submissions parse fail"})
                    label_dist["OTHER_DELISTED"] += 1
                    processed.add(cik)
                    continue
                filings = collect_filings_for_label(subs)
                form25_date = t.get("form25_date") or None
                label = label_from_filings(filings, form25_date=form25_date)
                labels.append({
                    "target_cik": cik,
                    "target_name": t.get("target_name", ""),
                    "form25_date": form25_date or "",
                    "label": label,
                    "ledger_status": ledger.get(cik, ""),
                })
                label_dist[label] += 1
                processed.add(cik)
                if len(processed) % 20 == 0:
                    ck["processed"] = sorted(processed)
                    ck["labels"] = labels
                    save_ck(ck)
                    LOG.info("progress %d/%d · %s", len(processed), len(targets), dict(label_dist))
    except SecBlockedError as e:
        LOG.error("SEC BLOCKED · %s", e)
        save_ck(ck)
        sys.exit(2)

    out_path = DATA_DIR / f"h3_labels_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["target_cik", "target_name", "form25_date", "label", "ledger_status"])
        w.writeheader()
        w.writerows(labels)

    # bias 분석: 가격 확보 (ledger status ∈ {kept, simfin_kept}) vs 미가격 (B60_pending, unrecoverable)
    KEPT = {"kept", "simfin_kept"}
    MISS = {"B60_pending", "unrecoverable"}
    kept_labels = defaultdict(int)
    miss_labels = defaultdict(int)
    for lab in labels:
        st = lab.get("ledger_status", "")
        if st in KEPT:
            kept_labels[lab["label"]] += 1
        elif st in MISS:
            miss_labels[lab["label"]] += 1
    bias_path = DATA_DIR / f"h3_bias_analysis_{sha}.csv"
    with bias_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cohort", "label", "count"])
        for label in ("BANKRUPT", "ACQUIRED", "OTHER_DELISTED"):
            w.writerow(["kept_92", label, kept_labels.get(label, 0)])
            w.writerow(["miss_48", label, miss_labels.get(label, 0)])

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "bias_csv": str(bias_path),
        "targets": len(targets),
        "processed": len(processed),
        "label_dist": dict(label_dist),
        "kept_labels": dict(kept_labels),
        "miss_labels": dict(miss_labels),
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
