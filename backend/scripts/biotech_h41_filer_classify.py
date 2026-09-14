"""WP41-2 · 제출자 4분류 (fund / strategic_corporate / individual / other).

용도:
- EFTS 643 events 의 filer_cik 518개 각각 submissions API 조회
- name · sic · entityType 확보
- 사전 커밋 규칙으로 4분류 (fund / strategic_corporate / individual / other)
- 캐시: h41_filer_classification.json (SEC 부담 감소)

규칙 (사전 커밋):
(a) fund: entityType 이 "investment company" 포함 OR 이름에 FUND/CAPITAL/PARTNERS/
  MANAGEMENT/L.P./LP/LLC/ADVISORS/INVESTORS/HOLDINGS/GROUP OR SIC 6xxx
(b) strategic_corporate: SIC in {2834, 2836, 2835, 8731} (제약·바이오·연구서비스)
  AND (a) 규칙 미해당
(c) individual: entityType == 'individual' OR 이름이 인명 패턴 (LAST, FIRST · 콤마 구분)
(d) other: 그 외
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING, REQ_INTERVAL, SecBlockedError

import csv
import json
import logging
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h41_filer_classify")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
CACHE = DATA_DIR / "h41_filer_classification.json"

FUND_KW = re.compile(r"\b(?:FUND|CAPITAL|PARTNERS|MANAGEMENT|L\.?P\.?|LLC|ADVISORS|INVESTORS|HOLDINGS?|GROUP|VENTURES?)\b", re.IGNORECASE)
INDIV_RE = re.compile(r"^[A-Z][A-Z' -]+,\s*[A-Z][A-Z '.-]+$")


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def sec_get(client: httpx.Client, url: str) -> httpx.Response:
    time.sleep(REQ_INTERVAL)
    r = client.get(url, timeout=30.0)
    if r.status_code == 403:
        raise SecBlockedError(f"403 · {url[:80]}")
    return r


def classify(name: str, sic: str, entity_type: str) -> tuple[str, str]:
    """반환 (bucket, reason)."""
    n = (name or "").strip()
    et = (entity_type or "").strip().lower()

    # individual 먼저 (엄격)
    if "individual" in et or INDIV_RE.match(n):
        return ("individual", f"entityType={et} · name pattern")

    # fund
    if "investment company" in et or FUND_KW.search(n):
        return ("fund", f"entityType={et} · name={n[:40]}")
    if sic and sic.startswith("6"):
        return ("fund", f"SIC {sic} (financial)")

    # strategic_corporate (제약·바이오·연구)
    if sic in ("2834", "2836", "2835", "8731"):
        return ("strategic_corporate", f"SIC {sic}")

    return ("other", f"SIC {sic} · entity={et} · name={n[:40]}")


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    efts = list(csv.DictReader((DATA_DIR / f"h3_efts_sc13d_universe_{sha}.csv").open()))
    filers = sorted({r["filer_cik"] for r in efts})
    LOG.info("unique filers: %d", len(filers))

    cache = {}
    if CACHE.exists():
        cache = json.loads(CACHE.read_text())
    processed = set(cache.keys())

    try:
        with httpx.Client(headers={"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}, timeout=30.0) as client:
            for i, cik in enumerate(filers, 1):
                if cik in processed:
                    continue
                r = sec_get(client, f"https://data.sec.gov/submissions/CIK{cik}.json")
                if r.status_code != 200:
                    cache[cik] = {"name": "", "sic": "", "entityType": "", "bucket": "other", "reason": f"http {r.status_code}"}
                    continue
                try:
                    data = r.json()
                except Exception:
                    cache[cik] = {"name": "", "sic": "", "entityType": "", "bucket": "other", "reason": "json fail"}
                    continue
                name = data.get("name", "")
                sic = str(data.get("sic", ""))
                et = data.get("entityType", "")
                bucket, reason = classify(name, sic, et)
                cache[cik] = {"name": name, "sic": sic, "entityType": et, "bucket": bucket, "reason": reason}
                if i % 25 == 0:
                    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
                    LOG.info("progress %d/%d", i, len(filers))
    except SecBlockedError as e:
        LOG.error("BLOCKED · %s", e)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
        sys.exit(2)

    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

    # 저장 CSV
    out = DATA_DIR / f"h41_filer_classification_{sha}.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["filer_cik", "name", "sic", "entityType", "bucket", "reason"])
        for cik, info in sorted(cache.items()):
            w.writerow([cik, info.get("name", ""), info.get("sic", ""), info.get("entityType", ""), info.get("bucket", ""), info.get("reason", "")])

    dist = Counter(info["bucket"] for info in cache.values())
    summary = {
        "git_sha": sha,
        "csv_path": str(out),
        "cache_path": str(CACHE),
        "total_filers": len(cache),
        "distribution": dict(dist),
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
