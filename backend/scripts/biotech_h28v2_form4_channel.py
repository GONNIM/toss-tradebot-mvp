"""WP28-2 · Form 4 채널 e 실채움 (Fable · Phase C 1).

기관 (fund) CIK 55개 → submissions API 로 Form 4 accession → 완전 제출 XML →
transactionCode P (매수) + acquiredDisposedCode A (취득) → h3_events 에 F4_buy 태깅.

**별도 리포트 원칙 유지**: h3_events_{sha}.csv 는 수정 · F4_buy event_type 추가
(SEC 마감 원본 태깅 · 봉인 위반 아님).

Rate limit: SEC 0.5s 간격 · Accept-Encoding gzip,deflate · WP23 UA.

캐시: `backend/data/h28v2_form4_issuer_buys_{sha}.json` (기관별 매수 이벤트)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging, data_sha
from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING, REQ_INTERVAL, SecBlockedError

import csv
import json
import logging
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h28v2_form4_channel")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
CACHE_PATH_TPL = "h28v2_form4_issuer_buys_{sha}.json"

# 사전 커밋: 기관 55 CIK · h41_filer_classification bucket=fund 상위 55 (알파벳/CIK 정렬)
INSTITUTION_KEYWORDS = re.compile(r"(FUND|CAPITAL|PARTNERS|MANAGEMENT|ADVISORS|LP|L\.P\.)", re.IGNORECASE)


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_fund_ciks() -> list[str]:
    p = DATA_DIR / "h41_filer_classification.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    funds = [(cik, info) for cik, info in data.items()
             if info.get("bucket") == "fund" and INSTITUTION_KEYWORDS.search(info.get("name", ""))]
    # 55 개 (사전 커밋)
    funds.sort(key=lambda x: x[0])
    return [cik for cik, _ in funds[:55]]


def sec_get(client: httpx.Client, url: str) -> httpx.Response:
    time.sleep(REQ_INTERVAL)
    r = client.get(url, timeout=30.0)
    if r.status_code == 403:
        raise SecBlockedError(f"403 · {url[:80]}")
    return r


def fetch_form4_accessions(client: httpx.Client, filer_cik: str) -> list[dict]:
    """filer 의 submissions.json → Form 4 accession + 발행사 CIK 추출."""
    r = sec_get(client, f"https://data.sec.gov/submissions/CIK{filer_cik}.json")
    if r.status_code != 200:
        return []
    data = r.json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    out = []
    for f, acc, d in zip(forms, accessions, dates):
        if f == "4":
            out.append({"accession": acc, "date": d})
    return out


def fetch_form4_xml(client: httpx.Client, filer_cik: str, acc: str) -> str | None:
    """완전 제출 텍스트 (.txt) 획득 · ownershipDocument XML 파트 추출."""
    acc_no = acc.replace("-", "")
    filer_int = int(filer_cik)
    url = f"https://www.sec.gov/Archives/edgar/data/{filer_int}/{acc_no}/{acc}.txt"
    r = sec_get(client, url)
    if r.status_code != 200:
        return None
    txt = r.text
    # <XML>...</XML> 블록 (form 4 는 <XML> ~ </XML> 안에 <ownershipDocument>)
    m = re.search(r"<XML>\s*(<\?xml.*?</ownershipDocument>)\s*</XML>", txt, re.DOTALL)
    return m.group(1) if m else None


def parse_form4(xml: str) -> list[dict]:
    """ownershipDocument → transactionCode P + acquiredDisposedCode A 필터."""
    # 발행사 CIK
    issuer_m = re.search(r"<issuerCik>\s*(\d+)\s*</issuerCik>", xml)
    issuer_cik = issuer_m.group(1).zfill(10) if issuer_m else ""
    # 발행사 이름
    name_m = re.search(r"<issuerName>([^<]+)</issuerName>", xml)
    issuer_name = (name_m.group(1) if name_m else "").strip()
    # transactionCode P & acquiredDisposedCode A
    out = []
    # <nonDerivativeTransaction> 각각 파싱
    for tx_m in re.finditer(r"<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>", xml, re.DOTALL):
        block = tx_m.group(1)
        code_m = re.search(r"<transactionCode>\s*([A-Z])\s*</transactionCode>", block)
        adc_m = re.search(r"<transactionAcquiredDisposedCode>.*?<value>\s*([A-Z])\s*</value>", block, re.DOTALL)
        date_m = re.search(r"<transactionDate>.*?<value>\s*([\d-]+)\s*</value>", block, re.DOTALL)
        shares_m = re.search(r"<transactionShares>.*?<value>\s*([\d.]+)\s*</value>", block, re.DOTALL)
        code = code_m.group(1) if code_m else ""
        adc = adc_m.group(1) if adc_m else ""
        date = date_m.group(1) if date_m else ""
        shares = float(shares_m.group(1)) if shares_m else 0.0
        if code == "P" and adc == "A":
            out.append({"issuer_cik": issuer_cik, "issuer_name": issuer_name,
                        "tx_date": date, "shares": shares})
    return out


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    if not (DATA_DIR / f"h3_events_{sha}.csv").exists():
        fb = data_sha(DATA_DIR)
        if fb:
            LOG.info("git_sha %s 데이터 부재 · data_sha fallback → %s", sha, fb)
            sha = fb

    fund_ciks = load_fund_ciks()
    LOG.info("fund CIKs (55 target): %d", len(fund_ciks))
    if not fund_ciks:
        print(json.dumps({"error": "no fund ciks"}))
        return

    max_ciks = int(sys.argv[1]) if len(sys.argv) > 1 else len(fund_ciks)

    cache_path = DATA_DIR / CACHE_PATH_TPL.format(sha=sha)
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())

    total_buys = 0
    processed = 0
    failed = 0

    try:
        with httpx.Client(headers={"User-Agent": SEC_UA, "From": SEC_FROM,
                                    "Accept-Encoding": SEC_ACCEPT_ENCODING}, timeout=30.0) as client:
            for i, filer_cik in enumerate(fund_ciks[:max_ciks], 1):
                if filer_cik in cache:
                    continue
                try:
                    accs = fetch_form4_accessions(client, filer_cik)
                    LOG.info("[%d/%d] filer %s · %d Form 4 accessions", i, max_ciks, filer_cik, len(accs))
                    buys = []
                    # 최근 60건만 (부담 감소)
                    for a in accs[:60]:
                        xml = fetch_form4_xml(client, filer_cik, a["accession"])
                        if xml is None:
                            failed += 1
                            continue
                        for b in parse_form4(xml):
                            b["filing_date"] = a["date"]
                            b["filer_cik"] = filer_cik
                            b["accession"] = a["accession"]
                            buys.append(b)
                    cache[filer_cik] = {"n_accs": len(accs), "n_buys": len(buys), "buys": buys}
                    total_buys += len(buys)
                    processed += 1
                    if i % 5 == 0:
                        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
                        LOG.info("progress %d/%d · total_buys=%d", i, max_ciks, total_buys)
                except SecBlockedError as e:
                    LOG.error("BLOCKED · %s", e)
                    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
                    sys.exit(2)
                except Exception as e:
                    LOG.warning("filer %s · %s", filer_cik, e.__class__.__name__)
                    failed += 1
                    continue
    except KeyboardInterrupt:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
        sys.exit(1)

    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

    # h3_events 태깅 여부는 실채움 완주 후 별도 스크립트 (WP28-3) 로 · 이번은 buy 리스트만
    total = sum(v.get("n_buys", 0) for v in cache.values())
    coverage = {"filer_ciks_processed": len(cache), "total_form4_buys": total, "failed_fetches": failed}
    summary = {
        "git_sha": sha,
        "cache_path": str(cache_path),
        "fund_ciks_target": len(fund_ciks),
        **coverage,
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
