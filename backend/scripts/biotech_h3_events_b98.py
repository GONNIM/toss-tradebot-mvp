"""WP1 · B98 · h3_events (13D/13G 신규만 · subject CIK 확정).

용도:
- h3_activist_cik_registry_v2 의 55 CIK 각각 submissions.json (+ filings.files 과거 페이지)
- 2021-09-01 ~ 2026-09-01 창 · SC 13D · SC 13G 신규 (/A 제외)
- subject CIK 는 filing index (Archives/edgar/data/{cik}/{acc}/) 의 subject company 필드로 확정
- 산출 h3_events_{sha}.csv: event_id · target_cik · ticker · event_type · event_date · accession · institution

원칙:
- SEC 지정 헤더 (biotech_sec_common) · 0.5s · 403 즉시 중단
- 체크포인트 (CIK 단위) · 재실행 이어받기
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_sec_common import (
    SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING,
    REQ_INTERVAL, SecBlockedError,
)

import csv
import json
import logging
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h3_events_b98")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
CHECKPOINT = DATA_DIR / "h3_events_b98_checkpoint.json"

SUBMISSIONS = "https://data.sec.gov/submissions"
ARCHIVES = "https://www.sec.gov/cgi-bin/browse-edgar"
ARCHIVES_DATA = "https://www.sec.gov/Archives/edgar/data"

START_DATE = "2021-09-01"
END_DATE = "2026-09-01"

WANTED_FORMS = {"SC 13D", "SC 13G"}  # 신규만 · /A 제외


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


def load_registry(sha: str) -> list[dict]:
    p = DATA_DIR / f"h3_activist_cik_registry_v2_{sha}.csv"
    with p.open() as f:
        return list(csv.DictReader(f))


def sec_get(client: httpx.Client, url: str) -> httpx.Response:
    time.sleep(REQ_INTERVAL)
    r = client.get(url, timeout=30.0)
    if r.status_code == 403:
        raise SecBlockedError(f"403 · {url[:80]}")
    return r


def fetch_all_filings(client: httpx.Client, cik10: str) -> list[dict]:
    """submissions.json recent + files (과거 페이지) 병합 → filings 목록."""
    url = f"{SUBMISSIONS}/CIK{cik10}.json"
    r = sec_get(client, url)
    if r.status_code != 200:
        LOG.warning("submissions %s → %d", cik10, r.status_code)
        return []
    data = r.json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accs = recent.get("accessionNumber", [])
    prims = recent.get("primaryDocument", [])
    out = []
    for i, f in enumerate(forms):
        out.append({
            "form": f,
            "date": dates[i] if i < len(dates) else "",
            "accession": accs[i] if i < len(accs) else "",
            "primary_doc": prims[i] if i < len(prims) else "",
        })
    # older files pagination
    for pg in data.get("filings", {}).get("files", []):
        pg_url = f"{SUBMISSIONS}/{pg.get('name')}"
        r2 = sec_get(client, pg_url)
        if r2.status_code != 200:
            continue
        try:
            d = r2.json()
        except Exception:
            continue
        forms2 = d.get("form", [])
        dates2 = d.get("filingDate", [])
        accs2 = d.get("accessionNumber", [])
        prims2 = d.get("primaryDocument", [])
        for i, f in enumerate(forms2):
            out.append({
                "form": f,
                "date": dates2[i] if i < len(dates2) else "",
                "accession": accs2[i] if i < len(accs2) else "",
                "primary_doc": prims2[i] if i < len(prims2) else "",
            })
    return out


def in_window(date_str: str) -> bool:
    return START_DATE <= date_str <= END_DATE


def fetch_subject_cik(client: httpx.Client, filer_cik: str, accession: str) -> tuple[str, str]:
    """Filing index JSON 에서 subject company (issuer) CIK·ticker 근사 반환."""
    acc_nodash = accession.replace("-", "")
    idx_url = f"{ARCHIVES_DATA}/{int(filer_cik)}/{acc_nodash}/index.json"
    try:
        r = sec_get(client, idx_url)
        if r.status_code != 200:
            return ("", "")
        idx = r.json()
        # index.json 은 file listing만 있음 · subject 정보 얻으려면 header 필요
        # Fallback: primary_doc 조회 → SUBJECT COMPANY block 추출 (SGML/HTML)
        # 간단화: primary_doc 이름 확인
        return ("", "")
    except SecBlockedError:
        raise
    except Exception:
        return ("", "")


def parse_subject_from_header(client: httpx.Client, filer_cik: str, accession: str) -> dict:
    """acc-nodash 폴더의 -index-headers.html or txt 헤더에서 SUBJECT COMPANY 블록 파싱."""
    acc_nodash = accession.replace("-", "")
    # Text index headers URL pattern
    hdr_url = f"{ARCHIVES_DATA}/{int(filer_cik)}/{acc_nodash}/{accession}-index-headers.html"
    try:
        r = sec_get(client, hdr_url)
        if r.status_code != 200:
            return {}
        text = r.text
        # SUBJECT COMPANY 블록 파싱
        subj_block = re.search(r"SUBJECT COMPANY:(.*?)(?:FILED BY:|</PRE>|$)", text, re.DOTALL)
        if not subj_block:
            return {}
        body = subj_block.group(1)
        # COMPANY DATA · CIK · TICKER 은 헤더에 없을 수 있음 · CENTRAL INDEX KEY 사용
        cik_m = re.search(r"CENTRAL INDEX KEY:\s*(\d+)", body)
        name_m = re.search(r"COMPANY CONFORMED NAME:\s*(.+)", body)
        return {
            "subject_cik": cik_m.group(1).zfill(10) if cik_m else "",
            "subject_name": name_m.group(1).strip() if name_m else "",
        }
    except SecBlockedError:
        raise
    except Exception:
        return {}


def load_checkpoint() -> dict:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"processed_ciks": [], "events": []}


def save_checkpoint(ck: dict):
    CHECKPOINT.write_text(json.dumps(ck, ensure_ascii=False, indent=2))


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    LOG.info("git_sha=%s", sha)

    registry = load_registry(sha)
    LOG.info("CIK count: %d", len(registry))

    ck = load_checkpoint()
    processed = set(ck.get("processed_ciks", []))
    events = ck.get("events", [])
    LOG.info("checkpoint: processed=%d · events=%d", len(processed), len(events))

    counts_by_form = {"SC 13D": 0, "SC 13G": 0}
    try:
        with httpx.Client(headers={"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}, timeout=30.0) as client:
            for row in registry:
                cik = row["cik"]
                if cik in processed:
                    continue
                cik10 = cik.zfill(10)
                inst = row.get("institution", "")
                LOG.info("processing %s (CIK %s)", inst, cik10)
                filings = fetch_all_filings(client, cik10)
                # 신규 13D / 13G 만 (/A 제외)
                new_ones = [f for f in filings if f["form"] in WANTED_FORMS and in_window(f["date"])]
                LOG.info("  total %d · new-13D/13G in window: %d", len(filings), len(new_ones))
                for f in new_ones:
                    counts_by_form[f["form"]] = counts_by_form.get(f["form"], 0) + 1
                    subj = parse_subject_from_header(client, cik10, f["accession"])
                    ev = {
                        "event_id": f"{cik10}_{f['accession']}",
                        "target_cik": subj.get("subject_cik", ""),
                        "target_name": subj.get("subject_name", ""),
                        "event_type": "13D_new" if f["form"] == "SC 13D" else "13G_new",
                        "event_date": f["date"],
                        "accession": f["accession"],
                        "institution": inst,
                        "filer_cik": cik10,
                    }
                    events.append(ev)
                processed.add(cik)
                ck["processed_ciks"] = sorted(processed)
                ck["events"] = events
                save_checkpoint(ck)
    except SecBlockedError as e:
        LOG.error("SEC BLOCKED · saving checkpoint · %s", e)
        save_checkpoint(ck)
        sys.exit(2)

    out_path = DATA_DIR / f"h3_events_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "event_id", "target_cik", "target_name", "event_type",
            "event_date", "accession", "institution", "filer_cik",
        ])
        w.writeheader()
        w.writerows(events)

    census = {"SC 13D": 50, "SC 13G": 296}  # B49·B50 시점 census
    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "processed_ciks": len(processed),
        "total_events": len(events),
        "by_form": counts_by_form,
        "census_target": census,
        "reconcile_diff": {
            "SC 13D": counts_by_form.get("SC 13D", 0) - census["SC 13D"],
            "SC 13G": counts_by_form.get("SC 13G", 0) - census["SC 13G"],
        },
        "subject_cik_recovered": sum(1 for e in events if e["target_cik"]),
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
