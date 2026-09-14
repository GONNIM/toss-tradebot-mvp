"""WP28-3 · Form 4 F4_buy 을 h3_events 에 병합.

WP28-2 캐시 (h28v2_form4_issuer_buys_{sha}.json) 로부터 · 발행사 CIK 별 F4_buy
이벤트를 h3_events_{sha}.csv 에 event_type=F4_buy 로 append.

**원칙 (사후 합산 금지)**:
- H3 리포트 (verification/H3/*.md) 는 불변 · 봉인 결과 그대로 유지
- F4 별도 리포트 예약 (h3_events 에는 이벤트만 태깅 · 백테스트 재실행 없음)
- 채널 e (Form 4 P) 는 WP54-3 에서만 사용 · 사전 커밋 규칙 준수
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging, data_sha

import csv
import json
import logging
import subprocess
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h28v3_form4_merge")

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
    if not (DATA_DIR / f"h3_events_{sha}.csv").exists():
        fb = data_sha(DATA_DIR)
        if fb:
            LOG.info("git_sha %s 데이터 부재 · data_sha fallback → %s", sha, fb)
            sha = fb

    cache_path = DATA_DIR / f"h28v2_form4_issuer_buys_{sha}.json"
    if not cache_path.exists():
        LOG.error("WP28-2 캐시 부재: %s", cache_path)
        return
    cache = json.loads(cache_path.read_text())

    events_path = DATA_DIR / f"h3_events_{sha}.csv"
    events = list(csv.DictReader(events_path.open()))
    existing_keys = set()
    for r in events:
        key = (r.get("target_cik", ""), r.get("event_date", ""), r.get("event_type", ""))
        existing_keys.add(key)

    # 원본 컬럼
    fieldnames = list(csv.DictReader(events_path.open()).fieldnames or [])

    # F4_buy 추가 (dedup by issuer_cik + tx_date)
    added = 0
    seen = set()
    for filer_cik, info in cache.items():
        for buy in info.get("buys", []):
            issuer_cik = buy.get("issuer_cik", "").zfill(10)
            tx_date = buy.get("tx_date", "")
            if not issuer_cik or not tx_date:
                continue
            key = (issuer_cik, tx_date, "F4_buy")
            if key in existing_keys or key in seen:
                continue
            seen.add(key)
            row = {c: "" for c in fieldnames}
            row["target_cik"] = issuer_cik
            row["event_date"] = tx_date
            row["event_type"] = "F4_buy"
            row["filer_cik"] = filer_cik
            row["accession"] = buy.get("accession", "")
            row["target_name"] = buy.get("issuer_name", "")
            events.append(row)
            added += 1

    # 백업 후 저장
    backup_path = events_path.with_suffix(".csv.bak_pre_wp28-3")
    if not backup_path.exists():
        events_path.rename(backup_path)
    else:
        events_path.unlink()

    with events_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(events)

    summary = {
        "git_sha": sha,
        "cache_filers": len(cache),
        "existing_events": len(events) - added,
        "added_F4_buy": added,
        "final_events": len(events),
        "backup_path": str(backup_path),
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
