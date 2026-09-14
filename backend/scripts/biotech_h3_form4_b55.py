"""WP1-B bg1 · B55+ Form 4 파싱 → F4_buy 이벤트 h3_events 추가.

용도:
- 55 CIK submissions.json (recent + files) → Form 4 accession 목록 (2021-09-01~2026-09-01)
- 각 accession XML → issuerCik · issuerTradingSymbol · transactionCode
- 코드 P (Purchase) 만 F4_buy 이벤트로 h3_events_form4_{sha}.csv 저장

원칙:
- SEC 지정 헤더 · 0.5s · 403 즉시 중단
- 체크포인트 (CIK+accession) · 재실행 이어받기
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_sec_common import (
    SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING, REQ_INTERVAL, SecBlockedError,
)

import csv
import json
import logging
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h3_form4_b55")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
CHECKPOINT = DATA_DIR / "h3_form4_b55_checkpoint.json"

SUBMISSIONS = "https://data.sec.gov/submissions"
ARCHIVES_DATA = "https://www.sec.gov/Archives/edgar/data"

START_DATE = "2021-09-01"
END_DATE = "2026-09-01"


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


def fetch_form4_accessions(client: httpx.Client, cik10: str) -> list[dict]:
    """Form 4 accession 만 반환 (recent + files pagination)."""
    r = sec_get(client, f"{SUBMISSIONS}/CIK{cik10}.json")
    if r.status_code != 200:
        return []
    data = r.json()
    def collect(recent: dict) -> list[dict]:
        out = []
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accs = recent.get("accessionNumber", [])
        prims = recent.get("primaryDocument", [])
        for i, f in enumerate(forms):
            if f != "4":
                continue
            d = dates[i] if i < len(dates) else ""
            if not (START_DATE <= d <= END_DATE):
                continue
            out.append({
                "accession": accs[i] if i < len(accs) else "",
                "date": d,
                "primary_doc": prims[i] if i < len(prims) else "",
            })
        return out
    out = collect(data.get("filings", {}).get("recent", {}))
    for pg in data.get("filings", {}).get("files", []):
        r2 = sec_get(client, f"{SUBMISSIONS}/{pg.get('name')}")
        if r2.status_code != 200:
            continue
        try:
            j = r2.json()
        except Exception:
            continue
        out.extend(collect(j))
    return out


def parse_form4_xml(client: httpx.Client, filer_cik10: str, accession: str, primary_doc: str) -> list[dict]:
    """Form 4 XML 파싱 · nonDerivativeTransaction 의 transactionCode 만 P 인 것 반환.

    primary_doc 이 xml 이면 그것 사용 · html 이면 acc 폴더에서 xml 검색.
    """
    acc_nodash = accession.replace("-", "")
    base = f"{ARCHIVES_DATA}/{int(filer_cik10)}/{acc_nodash}"
    urls = []
    if primary_doc and primary_doc.endswith(".xml"):
        urls.append(f"{base}/{primary_doc}")
    # Fallback: /wf-form4_*.xml or index 조회
    urls.append(f"{base}/{accession}-index.json")

    xml_text = None
    xml_url = None
    for u in urls[:1]:  # primary_doc 우선
        try:
            r = sec_get(client, u)
            if r.status_code == 200 and "<" in r.text[:200]:
                xml_text = r.text
                xml_url = u
                break
        except SecBlockedError:
            raise
        except Exception:
            continue

    # index.json fallback
    if xml_text is None:
        try:
            r = sec_get(client, f"{base}/{accession}-index.json")
            if r.status_code == 200:
                items = r.json().get("directory", {}).get("item", [])
                xmls = [it["name"] for it in items if it.get("name", "").endswith(".xml")]
                for name in xmls:
                    r2 = sec_get(client, f"{base}/{name}")
                    if r2.status_code == 200 and "<ownershipDocument" in r2.text:
                        xml_text = r2.text
                        xml_url = f"{base}/{name}"
                        break
        except SecBlockedError:
            raise
        except Exception:
            pass

    if xml_text is None:
        return []

    events = []
    try:
        root = ET.fromstring(xml_text)
        issuer = root.find("issuer")
        issuer_cik = (issuer.findtext("issuerCik") or "").strip().zfill(10) if issuer is not None else ""
        issuer_ticker = (issuer.findtext("issuerTradingSymbol") or "").strip() if issuer is not None else ""
        periodOfReport = (root.findtext("periodOfReport") or "").strip()
        # nonDerivativeTable / nonDerivativeTransaction
        for table in ("nonDerivativeTable", "derivativeTable"):
            tb = root.find(table)
            if tb is None:
                continue
            for tx in tb.findall(f"{'nonDerivativeTransaction' if table == 'nonDerivativeTable' else 'derivativeTransaction'}"):
                code = ""
                code_el = tx.find(".//transactionCode")
                if code_el is not None:
                    code = (code_el.text or "").strip()
                if code != "P":
                    continue
                # transactionDate
                dt = ""
                dt_el = tx.find(".//transactionDate/value")
                if dt_el is not None:
                    dt = (dt_el.text or "").strip()
                if not dt:
                    dt = periodOfReport
                events.append({
                    "issuer_cik": issuer_cik,
                    "issuer_ticker": issuer_ticker,
                    "transaction_date": dt,
                    "transaction_code": code,
                    "accession": accession,
                    "xml_url": xml_url,
                })
    except ET.ParseError as e:
        return []
    return events


def load_checkpoint() -> dict:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"processed_ciks": [], "processed_accessions": [], "events": [], "stats": {"accessions_seen": 0, "parse_fail": 0, "not_purchase": 0}}


def save_ck(ck: dict):
    CHECKPOINT.write_text(json.dumps(ck, ensure_ascii=False, indent=2))


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    registry = load_registry(sha)
    LOG.info("CIKs: %d", len(registry))

    ck = load_checkpoint()
    processed_ciks = set(ck.get("processed_ciks", []))
    processed_accs = set(ck.get("processed_accessions", []))
    events = ck.get("events", [])
    stats = ck.get("stats", {"accessions_seen": 0, "parse_fail": 0, "not_purchase": 0})

    try:
        with httpx.Client(headers={"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}, timeout=30.0) as client:
            for row in registry:
                cik = row["cik"]
                if cik in processed_ciks:
                    continue
                cik10 = cik.zfill(10)
                inst = row.get("institution", "")
                LOG.info("processing %s CIK=%s", inst, cik10)
                accs = fetch_form4_accessions(client, cik10)
                LOG.info("  Form 4 accessions (in window): %d", len(accs))
                for a in accs:
                    if a["accession"] in processed_accs:
                        continue
                    stats["accessions_seen"] += 1
                    try:
                        purchases = parse_form4_xml(client, cik10, a["accession"], a["primary_doc"])
                    except SecBlockedError:
                        raise
                    if not purchases:
                        stats["parse_fail"] = stats.get("parse_fail", 0) + 1
                    for e in purchases:
                        e["filer_cik"] = cik10
                        e["institution"] = inst
                        e["event_type"] = "F4_buy"
                        events.append(e)
                    processed_accs.add(a["accession"])
                    if stats["accessions_seen"] % 50 == 0:
                        ck["processed_accessions"] = sorted(processed_accs)
                        ck["events"] = events
                        ck["stats"] = stats
                        save_ck(ck)
                processed_ciks.add(cik)
                ck["processed_ciks"] = sorted(processed_ciks)
                ck["events"] = events
                ck["stats"] = stats
                save_ck(ck)
    except SecBlockedError as e:
        LOG.error("SEC BLOCKED · %s · checkpoint saved", e)
        save_ck(ck)
        sys.exit(2)

    # 저장 (append 형태로 h3_events_form4 별도 저장 · h3_events 는 B98 결과 유지)
    out_path = DATA_DIR / f"h3_events_form4_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "issuer_cik", "issuer_ticker", "transaction_date", "transaction_code",
            "accession", "filer_cik", "institution", "event_type", "xml_url",
        ])
        w.writeheader()
        w.writerows(events)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "processed_ciks": len(processed_ciks),
        "accessions_seen": stats["accessions_seen"],
        "parse_fail": stats.get("parse_fail", 0),
        "f4_buy_events": len(events),
        "unique_issuers": len({e["issuer_cik"] for e in events if e["issuer_cik"]}),
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
