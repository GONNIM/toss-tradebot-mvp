"""WP37b/WP33-3 · EFTS 전수 · SC 13D 신규 · SIC 2834/2836 · 최근 12개월+.

용도:
- EFTS forms=SC 13D · dateRange 2021-09-01~2026-09-01
- 각 filing 의 ciks[0] (subject CIK) 로 submissions.json 조회 → SIC 확인
- SIC 2834/2836 필터 · 제출자 (filer CIK) 불문
- 기존 55 CIK 표기
- 산출: h3_efts_sc13d_universe_{sha}.csv (subject_cik · sic · date · accession · filer_cik · in_seed_55)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING, REQ_INTERVAL, SecBlockedError

import csv
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h3_efts_sc13d")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
CHECKPOINT = DATA_DIR / "h3_efts_sc13d_checkpoint.json"

EFTS = "https://efts.sec.gov/LATEST/search-index"
SUBMISSIONS = "https://data.sec.gov/submissions"


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_seed_ciks(sha: str) -> set[str]:
    p = DATA_DIR / f"h3_activist_cik_registry_v2_{sha}.csv"
    out = set()
    with p.open() as f:
        for r in csv.DictReader(f):
            out.add((r.get("cik") or "").zfill(10))
    return out


def sec_get(client: httpx.Client, url: str, params=None) -> httpx.Response:
    time.sleep(REQ_INTERVAL)
    r = client.get(url, params=params, timeout=30.0)
    if r.status_code == 403:
        raise SecBlockedError(f"403 · {url[:80]}")
    return r


def efts_page(client: httpx.Client, dateFrom: str, dateTo: str, page_from: int = 0) -> dict:
    r = sec_get(client, EFTS, params={
        "forms": "SC 13D",
        "dateRange": "custom",
        "startdt": dateFrom,
        "enddt": dateTo,
        "from": page_from,
        "size": 100,
    })
    if r.status_code != 200:
        return {}
    return r.json()


def get_sic(client: httpx.Client, cik10: str, cache: dict) -> str:
    if cik10 in cache:
        return cache[cik10]
    try:
        r = sec_get(client, f"{SUBMISSIONS}/CIK{cik10}.json")
        if r.status_code != 200:
            cache[cik10] = ""
            return ""
        sic = str(r.json().get("sic", ""))
        cache[cik10] = sic
        return sic
    except SecBlockedError:
        raise
    except Exception:
        cache[cik10] = ""
        return ""


def load_ck() -> dict:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"rows": [], "sic_cache": {}, "processed_ranges": []}


def save_ck(ck: dict):
    CHECKPOINT.write_text(json.dumps(ck, ensure_ascii=False, indent=2))


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    seed = load_seed_ciks(sha)
    ck = load_ck()
    sic_cache = ck.get("sic_cache", {})
    rows = ck.get("rows", [])
    processed = set(tuple(x) for x in ck.get("processed_ranges", []))

    # 월 단위 분할 (전건 fetch 부담 감소)
    months = []
    for yy in range(2021, 2027):
        for mm in range(1, 13):
            months.append((yy, mm))
    # 2021-09~2026-09
    months = [(y, m) for (y, m) in months if (y > 2021 or (y == 2021 and m >= 9)) and (y < 2026 or (y == 2026 and m <= 9))]

    try:
        with httpx.Client(headers={"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}, timeout=30.0) as client:
            for (yy, mm) in months:
                key = (yy, mm)
                if key in processed:
                    continue
                dfrom = f"{yy:04d}-{mm:02d}-01"
                if mm == 12:
                    dto = f"{yy:04d}-12-31"
                else:
                    dto = f"{yy:04d}-{mm:02d}-28"  # 안전 · 완전 커버 위해 다음 월 -1 대신 28 (부분)
                    from calendar import monthrange
                    dto = f"{yy:04d}-{mm:02d}-{monthrange(yy, mm)[1]:02d}"
                LOG.info("month %d-%02d · %s ~ %s", yy, mm, dfrom, dto)
                page_from = 0
                while True:
                    j = efts_page(client, dfrom, dto, page_from)
                    hits = j.get("hits", {}).get("hits", [])
                    if not hits:
                        break
                    for h in hits:
                        src = h.get("_source", {})
                        form = src.get("form", "")
                        if form != "SC 13D":  # 신규만 · /A 제외
                            continue
                        ciks = src.get("ciks", []) or []
                        if not ciks:
                            continue
                        subject_cik = str(ciks[0]).zfill(10)
                        filer_cik = str(ciks[-1]).zfill(10) if len(ciks) > 1 else subject_cik
                        acc = src.get("adsh", "")
                        fdate = src.get("file_date", "")
                        sic = get_sic(client, subject_cik, sic_cache)
                        if sic not in ("2834", "2836"):
                            continue
                        rows.append({
                            "date": fdate,
                            "subject_cik": subject_cik,
                            "filer_cik": filer_cik,
                            "accession": acc,
                            "sic": sic,
                            "in_seed_55": filer_cik in seed or subject_cik in seed,
                        })
                    total = j.get("hits", {}).get("total", {}).get("value", 0)
                    page_from += len(hits)
                    if page_from >= total or len(hits) < 100:
                        break
                    ck["rows"] = rows
                    ck["sic_cache"] = sic_cache
                    save_ck(ck)
                processed.add(key)
                ck["processed_ranges"] = sorted(list(processed))
                ck["rows"] = rows
                ck["sic_cache"] = sic_cache
                save_ck(ck)
                LOG.info("month %d-%02d done · rows so far: %d", yy, mm, len(rows))
    except SecBlockedError as e:
        LOG.error("SEC BLOCKED · %s · checkpoint saved", e)
        save_ck(ck)
        sys.exit(2)

    out_path = DATA_DIR / f"h3_efts_sc13d_universe_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "subject_cik", "filer_cik", "accession", "sic", "in_seed_55"])
        w.writeheader()
        w.writerows(rows)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "total_sc13d_biotech": len(rows),
        "in_seed_55_count": sum(1 for r in rows if r["in_seed_55"]),
        "out_of_seed_count": sum(1 for r in rows if not r["in_seed_55"]),
        "sic_dist": {sic: sum(1 for r in rows if r["sic"] == sic) for sic in ("2834", "2836")},
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
