"""WP4 · H8 채널 수집기 (bioRxiv/PubMed/AACT 실측).

용도:
- 채널 2 (bioRxiv/medRxiv) · 채널 3 (PubMed) 게재일 시계열 수집기 (테마 키워드 입력)
- 채널 1 (AACT 스냅샷) 접근 실측 (다운로드 가능 여부 · 용량 · point-in-time 필드)

원칙:
- 무인증 · 무료 · 결제 금지
- 신호 시각 = 게재일 (bioRxiv `date` · PubMed `pdat`)
- 티커/약물명 매핑은 후속 (본 수집기는 raw 저장까지)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import csv
import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

LOG = logging.getLogger("biotech_h8_channels")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

BIORXIV_BASE = "https://api.biorxiv.org"
PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
AACT_HEAD_URL = "https://aact.ctti-clinicaltrials.org/pipe_files"
AACT_SNAPSHOT_URL = "https://aact.ctti-clinicaltrials.org/static/exported_files/monthly"

UA = "TossTradebot-BiotechRadar/1.0 (sung2011103@naver.com)"


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


def probe_aact() -> dict:
    """AACT 스냅샷 페이지 HEAD 확인.

    실 다운로드는 수백MB · 스코프 밖 · 접근 가능 여부만.
    """
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True) as client:
        r = client.get(AACT_HEAD_URL, timeout=30.0)
        return {
            "aact_head_url": AACT_HEAD_URL,
            "http_status": r.status_code,
            "content_type": r.headers.get("Content-Type", ""),
            "content_length": r.headers.get("Content-Length", ""),
            "snapshot_page_accessible": r.status_code == 200,
            "notes": (
                "AACT 스냅샷 = Duke CTTI · 매월 pipe-delimited zip 배포 · 예상 400MB+ · "
                "실 다운로드는 별건 · point-in-time 필드 = studies.study_first_posted_date · "
                "studies.last_update_posted_date · study_verified_date"
            ),
        }


def fetch_pubmed(term: str, mindate: str, maxdate: str) -> dict:
    """PubMed esearch · count + first PMID 5개."""
    with httpx.Client(headers={"User-Agent": UA}) as client:
        r = client.get(
            PUBMED_ESEARCH,
            params={
                "db": "pubmed",
                "term": term,
                "mindate": mindate,
                "maxdate": maxdate,
                "datetype": "pdat",
                "retmode": "json",
                "retmax": 5,
                "tool": "TossTradebot-BiotechRadar",
                "email": "sung2011103@naver.com",
            },
            timeout=30.0,
        )
        r.raise_for_status()
        j = r.json().get("esearchresult", {})
        return {
            "count": int(j.get("count", 0)),
            "sample_pmids": j.get("idlist", []),
        }


def fetch_biorxiv(server: str, from_date: str, to_date: str, limit: int = 20) -> dict:
    """bioRxiv/medRxiv details endpoint. server='biorxiv' or 'medrxiv'.

    Note: bioRxiv 는 개별 DOI 조회는 되지만 date range 검색은 상세 endpoint 부재 ·
    /details/{server}/{yyyy-mm-dd}/{yyyy-mm-dd}/0 pagination 사용.
    """
    url = f"{BIORXIV_BASE}/details/{server}/{from_date}/{to_date}/0"
    with httpx.Client(headers={"User-Agent": UA}) as client:
        r = client.get(url, timeout=30.0)
        r.raise_for_status()
        j = r.json()
        collection = j.get("collection", [])
        return {
            "server": server,
            "from_date": from_date,
            "to_date": to_date,
            "messages_count": j.get("messages", [{}])[0].get("count", 0) if j.get("messages") else 0,
            "returned_records": len(collection),
            "sample_titles": [c.get("title", "")[:120] for c in collection[:5]],
        }


def main():
    require_secure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-only", action="store_true", help="AACT/bioRxiv/PubMed 접근성 실측만")
    parser.add_argument("--keyword", default="GLP-1")
    parser.add_argument("--from-date", default="2024-01-01")
    parser.add_argument("--to-date", default="2024-03-31")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    sha = git_sha()
    LOG.info("git_sha=%s", sha)

    result = {
        "git_sha": sha,
        "aact": probe_aact(),
        "pubmed": fetch_pubmed(args.keyword, args.from_date.replace("-", "/"), args.to_date.replace("-", "/")),
        "biorxiv": fetch_biorxiv("biorxiv", args.from_date, args.to_date),
        "medrxiv": fetch_biorxiv("medrxiv", args.from_date, args.to_date),
    }

    out_path = DATA_DIR / f"h8_channels_probe_{sha}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    LOG.info("probe result saved: %s", out_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
