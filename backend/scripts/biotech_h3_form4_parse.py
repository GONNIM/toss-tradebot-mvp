"""H3 Form 4 경로 교체 (B55+ · 2026-09-03).

기존 EFTS company name search 는 Form 4 를 filer 관점으로 색인하지 않아
정확 대사 실패 (523/1694). 이 스크립트는:
1) 각 filer CIK 의 submissions.filings 에서 기간 내 Form 4 accession 목록 수집
2) 각 Form 4 accession-index.json → primary XML 파싱
3) issuerCik · issuerTradingSymbol · transactionCode 추출
4) transactionCode == 'P' 만 이벤트 (B51 정의 · buy)
5) h3_targets_v2 의 form4 컬럼 → form4_buy 재산출
6) 대사 (기관 census 도 동일 경로로 재집계 · 기준 통일)

산출:
- backend/data/h3_form4_events_{git_sha}.csv (filer_cik, accession, date, issuer_cik, ticker, code, count)
- backend/data/h3_targets_v3_{git_sha}.csv (form4 컬럼 → form4_buy)

실행:
    python -m backend.scripts.biotech_h3_form4_parse
"""
from __future__ import annotations

from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING  # noqa: E402 · WP23

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging  # noqa: F401

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

from backend.scripts.biotech_h3_filing_census import INSTITUTIONS, load_seed_activists, resolve_cik

LOG = logging.getLogger("biotech_form4")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"
REQ_INTERVAL = 0.5

DATE_START = "2021-09-01"
DATE_END = "2026-09-01"


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=False,
            cwd=Path(__file__).resolve().parent.parent.parent,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _get(client: httpx.Client, url: str, params: dict | None = None, retries: int = 3) -> httpx.Response | None:
    delay = REQ_INTERVAL
    for _ in range(retries):
        time.sleep(delay)
        try:
            r = client.get(url, params=params, timeout=25.0)
            if r.status_code < 500:
                return r
        except Exception:
            pass
        delay = min(delay * 3, 5.0)
    return None


def fetch_submissions(client: httpx.Client, cik: str) -> dict | None:
    url = f"{SUBMISSIONS_BASE}/CIK{cik.zfill(10)}.json"
    r = _get(client, url)
    if r is None or r.status_code != 200:
        return None
    try:
        return r.json()
    except Exception:
        return None


def collect_form4_accessions(subs: dict) -> list[tuple[str, str]]:
    """filings.recent + files 페이지네이션에서 Form 4 accession + date 수집."""
    out: list[tuple[str, str]] = []
    recent = subs.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accs = recent.get("accessionNumber", [])
    for i, f in enumerate(forms):
        if f == "4" and i < len(dates) and i < len(accs):
            try:
                d = datetime.strptime(dates[i], "%Y-%m-%d")
                if datetime(2021, 9, 1) <= d <= datetime(2026, 9, 1):
                    out.append((accs[i], dates[i]))
            except ValueError:
                continue
    return out


def parse_form4_xml(client: httpx.Client, cik: str, accession: str) -> list[dict]:
    """Form 4 XML 에서 issuer + transactionCode 파싱.
    반환: [{issuer_cik, ticker, code, is_purchase}]
    """
    acc_no_dash = accession.replace("-", "")
    idx_url = f"{ARCHIVE_BASE}/{cik.lstrip('0')}/{acc_no_dash}/{accession}-index.json"
    r = _get(client, idx_url)
    if r is None or r.status_code != 200:
        return []
    try:
        idx = r.json()
    except Exception:
        return []
    items = idx.get("directory", {}).get("item", [])
    primary_xml = None
    for it in items:
        nm = it.get("name", "")
        if nm.endswith(".xml") and not nm.endswith("-index.xml"):
            primary_xml = nm
            break
    if not primary_xml:
        return []
    doc_url = f"{ARCHIVE_BASE}/{cik.lstrip('0')}/{acc_no_dash}/{primary_xml}"
    r2 = _get(client, doc_url)
    if r2 is None or r2.status_code != 200:
        return []
    text = r2.text
    # issuer 추출
    m_cik = re.search(r"<issuerCik>(\d+)</issuerCik>", text)
    m_sym = re.search(r"<issuerTradingSymbol>([^<]+)</issuerTradingSymbol>", text)
    issuer_cik = m_cik.group(1) if m_cik else ""
    ticker = m_sym.group(1).strip() if m_sym else ""
    # transaction codes (여러 개 가능 · Non-Derivative + Derivative)
    codes = re.findall(r"<transactionCode>([A-Z])</transactionCode>", text)
    # 각 code 별로 이벤트 · code=='P' (Open Market or Private Purchase)
    events = []
    for c in codes:
        events.append({
            "issuer_cik": issuer_cik,
            "ticker": ticker,
            "code": c,
            "is_purchase": c == "P",
        })
    return events


def main() -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from backend.services import config as _config  # noqa: F401
    git_sha = _git_sha()

    seed = load_seed_activists()

    with httpx.Client(
        headers={"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}
    ) as client:
        # 기관 CIK 확정 (기존 census 재사용)
        for inst in INSTITUTIONS:
            resolve_cik(client, inst, seed)

        # 각 CIK 의 Form 4 accession 수집
        all_form4: list[dict] = []  # {filer_cik, institution, accession, date}
        for inst in INSTITUTIONS:
            for c in inst.ciks:
                cik = c["cik"]
                LOG.info("  Form 4 accessions · %s CIK %s", inst.name, cik)
                subs = fetch_submissions(client, cik)
                if subs is None:
                    continue
                accs = collect_form4_accessions(subs)
                for acc, dt in accs:
                    all_form4.append({
                        "filer_cik": cik,
                        "institution": inst.name,
                        "accession": acc,
                        "date": dt,
                    })
        LOG.info("총 Form 4 accession: %d", len(all_form4))

        # XML 파싱
        parsed_rows: list[dict] = []
        buy_count = 0
        for i, ff in enumerate(all_form4, 1):
            if i % 100 == 0:
                LOG.info("Form 4 parse %d/%d · buy=%d", i, len(all_form4), buy_count)
            events = parse_form4_xml(client, ff["filer_cik"], ff["accession"])
            for e in events:
                if e["is_purchase"]:
                    buy_count += 1
                parsed_rows.append({
                    "filer_cik": ff["filer_cik"],
                    "institution": ff["institution"],
                    "accession": ff["accession"],
                    "date": ff["date"],
                    "issuer_cik": e["issuer_cik"],
                    "ticker": e["ticker"],
                    "code": e["code"],
                    "is_purchase": e["is_purchase"],
                })

        events_path = DATA_DIR / f"h3_form4_events_{git_sha}.csv"
        with open(events_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(parsed_rows[0].keys()) if parsed_rows else
                               ["filer_cik", "institution", "accession", "date", "issuer_cik", "ticker", "code", "is_purchase"])
            w.writeheader()
            w.writerows(parsed_rows)

        # 대사 요약
        total_form4_accessions = len(all_form4)
        total_events_parsed = len(parsed_rows)
        purchase_events = sum(1 for r in parsed_rows if r["is_purchase"])
        unique_issuer_ciks = len({r["issuer_cik"] for r in parsed_rows if r["issuer_cik"]})
        unique_purchase_issuers = len({r["issuer_cik"] for r in parsed_rows if r["is_purchase"] and r["issuer_cik"]})

        print("\n== B55+ Form 4 경로 교체 (issuer + code P) ==")
        print(f"git_sha:                        {git_sha}")
        print(f"기간:                            {DATE_START}..{DATE_END}")
        print(f"Form 4 accession 수:             {total_form4_accessions}")
        print(f"파싱된 transaction events:       {total_events_parsed}")
        print(f"code P (buy) events:             {purchase_events}")
        print(f"unique issuer CIKs (전 events):  {unique_issuer_ciks}")
        print(f"unique purchase issuer CIKs:     {unique_purchase_issuers}")
        print(f"events_csv:                      {events_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
