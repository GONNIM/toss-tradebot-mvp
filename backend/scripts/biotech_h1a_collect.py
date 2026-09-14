"""WP2 · H1a 이벤트 수집기 (Federal Register API).

용도:
- FDA Advisory Committee 공고 전량 수집 (SEC 불요 · 무인증)
- DATES 절 파싱 (회의일) + 위원회·대상 약물/신청사 추출
- biotech_ticker_set + 회사명 정규화 티커 매핑

원칙:
- Federal Register API `documents.json` · 무료 · 무인증
- publication_date = 공고일 (사전 공지 시각) · 회의일은 abstract/full_text 에서 파싱
- 티커 매핑 실패 시 mapped_ticker 공란 유지 · 표본 제외 아님 (매핑 성공률 계산용)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import re
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

LOG = logging.getLogger("biotech_h1a_collect")

BASE = "https://www.federalregister.gov/api/v1/documents.json"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

UA = "TossTradebot-BiotechRadar/1.0 (sung2011103@naver.com)"
REQ_INTERVAL = 0.5

# 회의일 파싱 정규식 (abstract·full_text 대상)
# 예: "The meeting will be held on October 15, 2024"
#     "public advisory committee meeting on November 3-4, 2025"
MONTH = r"(January|February|March|April|May|June|July|August|September|October|November|December)"
RE_MEETING_DATE = re.compile(
    rf"{MONTH}\s+(\d{{1,2}})(?:[-–]\d{{1,2}})?,\s*(\d{{4}})",
    re.IGNORECASE,
)

# 위원회명 (title/abstract 에서 first match)
COMMITTEE_KEYWORDS = [
    "Oncologic Drugs Advisory Committee",
    "Cardiovascular and Renal Drugs Advisory Committee",
    "Pediatric Advisory Committee",
    "Anti-Infective Drugs Advisory Committee",
    "Endocrinologic and Metabolic Drugs Advisory Committee",
    "Peripheral and Central Nervous System Drugs Advisory Committee",
    "Psychopharmacologic Drugs Advisory Committee",
    "Vaccines and Related Biological Products Advisory Committee",
    "Bone, Reproductive and Urologic Drugs Advisory Committee",
    "Nonprescription Drugs Advisory Committee",
    "Drug Safety and Risk Management Advisory Committee",
    "Cellular, Tissue, and Gene Therapies Advisory Committee",
    "Pulmonary-Allergy Drugs Advisory Committee",
    "Gastrointestinal Drugs Advisory Committee",
    "Arthritis Advisory Committee",
    "Blood Products Advisory Committee",
    "Dermatologic and Ophthalmic Drugs Advisory Committee",
    "Antimicrobial Drugs Advisory Committee",
    "Medical Imaging Drugs Advisory Committee",
]


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


def load_ticker_set(sha: str) -> dict[str, dict]:
    """biotech_ticker_set_{sha}.csv → name→ticker 사전 (정규화).

    key = 정규화 회사명 (소문자·구두점 제거·suffix Inc/Corp 제거)
    """
    path = DATA_DIR / f"biotech_ticker_set_{sha}.csv"
    if not path.exists():
        LOG.warning("ticker set not found: %s", path)
        return {}
    out = {}
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("name", "").strip()
            ticker = row.get("ticker", "").strip()
            if not name or not ticker or ticker == "-":
                continue
            norm = normalize_name(name)
            if norm and norm not in out:
                out[norm] = {"ticker": ticker, "name": name}
    LOG.info("loaded %d name→ticker mappings", len(out))
    return out


def normalize_name(name: str) -> str:
    """회사명 정규화 (매핑 키 산출)."""
    s = name.lower()
    # suffix 제거
    for suffix in [
        " incorporated",
        " inc",
        " corporation",
        " corp",
        " limited",
        " ltd",
        " plc",
        " holdings",
        " group",
        " company",
        " co",
        " pharmaceuticals",
        " pharmaceutical",
        " pharma",
        " therapeutics",
        " biosciences",
        " biotech",
    ]:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break  # 한 번만
    # 구두점 제거
    s = re.sub(r"[.,()\-/&]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_meeting_date(text: str, pub_date: str) -> str | None:
    """abstract/title 에서 회의일 파싱 (첫 매치).

    pub_date 이후 12개월 이내만 인정 (사후 공고 오류 배제).
    """
    if not text:
        return None
    matches = RE_MEETING_DATE.findall(text)
    try:
        pub = datetime.strptime(pub_date, "%Y-%m-%d").date()
    except Exception:
        return None
    for month_name, day, year in matches:
        try:
            dt = datetime.strptime(f"{month_name} {day} {year}", "%B %d %Y").date()
        except Exception:
            continue
        delta_days = (dt - pub).days
        if 0 <= delta_days <= 365:  # 공고→회의 사전 공지
            return dt.strftime("%Y-%m-%d")
    return None


def parse_committee(text: str) -> str | None:
    """title/abstract 에서 위원회명 첫 매치."""
    if not text:
        return None
    for kw in COMMITTEE_KEYWORDS:
        if kw.lower() in text.lower():
            return kw
    return None


def parse_sponsor(text: str) -> tuple[str | None, str | None]:
    """abstract 에서 신청사·약물명 추출 (best effort).

    패턴 예:
    - "sponsored by ABC Corporation"
    - "an application from XYZ Inc."
    - "submitted by DEF Ltd."
    - "review of drugname (product) sponsored by CorpName"
    """
    if not text:
        return None, None
    sponsor = None
    drug = None
    for pat in [
        r"(?:sponsored|submitted|manufactured)\s+by\s+([A-Z][A-Za-z0-9\-.,& ]{2,60}?)(?:[,.]|\s+for|\s+of|\s*\()",
        r"application\s+from\s+([A-Z][A-Za-z0-9\-.,& ]{2,60}?)(?:[,.]|\s+for|\s+of|\s*\()",
        r"filed\s+by\s+([A-Z][A-Za-z0-9\-.,& ]{2,60}?)(?:[,.]|\s+for|\s+of|\s*\()",
    ]:
        m = re.search(pat, text)
        if m:
            sponsor = m.group(1).strip()
            break
    # 약물명 (best effort · 대문자 + 소문자 조합 · 4~30 chars)
    m = re.search(r"\b([A-Z][a-z]{3,20}(?:\s+[a-z]{3,20})?)\s+\((\w[\w\-]{2,20})\)", text)
    if m:
        drug = m.group(1)
    return sponsor, drug


def fetch_page(client: httpx.Client, page: int, per_page: int = 100) -> dict:
    params = {
        "conditions[term]": "Advisory Committee",
        "conditions[agencies][]": "food-and-drug-administration",
        "conditions[publication_date][gte]": "2021-01-01",
        "conditions[publication_date][lte]": "2026-09-05",
        "per_page": per_page,
        "page": page,
        "order": "oldest",
        "fields[]": [
            "title",
            "publication_date",
            "type",
            "abstract",
            "agencies",
            "html_url",
            "document_number",
            "raw_text_url",
        ],
    }
    r = client.get(BASE, params=params, timeout=30.0)
    r.raise_for_status()
    return r.json()


def main():
    require_secure_logging()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    sha = git_sha()
    LOG.info("git_sha=%s", sha)
    name_map = load_ticker_set(sha)

    records = []
    with httpx.Client(headers={"User-Agent": UA}) as client:
        page = 1
        total = None
        while True:
            LOG.info("fetching page %d", page)
            data = fetch_page(client, page)
            if total is None:
                total = data.get("count", 0)
                LOG.info("total count=%d", total)
            results = data.get("results", [])
            if not results:
                break
            for r in results:
                records.append(r)
            if not data.get("next_page_url"):
                break
            page += 1
            time.sleep(REQ_INTERVAL)
    LOG.info("fetched %d documents", len(records))

    # 파싱·매핑
    out_rows = []
    mapping_hits = 0
    meeting_hits = 0
    committee_hits = 0
    sponsor_hits = 0
    lag_days = []
    for r in records:
        pub_date = r.get("publication_date", "")
        title = r.get("title", "") or ""
        abstract = r.get("abstract", "") or ""
        text = f"{title}\n{abstract}"

        meeting_date = parse_meeting_date(text, pub_date)
        committee = parse_committee(text)
        sponsor, drug = parse_sponsor(abstract)
        mapped_ticker = ""
        mapped_name = ""
        if sponsor:
            key = normalize_name(sponsor)
            if key in name_map:
                mapped_ticker = name_map[key]["ticker"]
                mapped_name = name_map[key]["name"]

        if meeting_date:
            meeting_hits += 1
            try:
                pub = datetime.strptime(pub_date, "%Y-%m-%d").date()
                mt = datetime.strptime(meeting_date, "%Y-%m-%d").date()
                lag_days.append((mt - pub).days)
            except Exception:
                pass
        if committee:
            committee_hits += 1
        if sponsor:
            sponsor_hits += 1
        if mapped_ticker:
            mapping_hits += 1

        out_rows.append(
            {
                "publication_date": pub_date,
                "meeting_date": meeting_date or "",
                "committee": committee or "",
                "sponsor_raw": sponsor or "",
                "drug_raw": drug or "",
                "mapped_ticker": mapped_ticker,
                "mapped_name": mapped_name,
                "type": r.get("type", ""),
                "document_number": r.get("document_number", ""),
                "html_url": r.get("html_url", ""),
                "title": title[:200],
            }
        )

    # 저장
    out_path = DATA_DIR / f"h1a_events_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "publication_date",
                "meeting_date",
                "committee",
                "sponsor_raw",
                "drug_raw",
                "mapped_ticker",
                "mapped_name",
                "type",
                "document_number",
                "html_url",
                "title",
            ],
        )
        w.writeheader()
        w.writerows(out_rows)

    # 요약
    lag_days_sorted = sorted(lag_days)
    lag_median = lag_days_sorted[len(lag_days_sorted) // 2] if lag_days_sorted else None
    summary = {
        "git_sha": sha,
        "total_events": len(out_rows),
        "meeting_date_parsed": meeting_hits,
        "meeting_date_parse_rate": round(meeting_hits / max(1, len(out_rows)), 3),
        "committee_parsed": committee_hits,
        "sponsor_parsed": sponsor_hits,
        "sponsor_parse_rate": round(sponsor_hits / max(1, len(out_rows)), 3),
        "ticker_mapped": mapping_hits,
        "ticker_mapping_rate_among_sponsors": round(
            mapping_hits / max(1, sponsor_hits), 3
        ),
        "lag_days_median": lag_median,
        "lag_days_min": lag_days_sorted[0] if lag_days_sorted else None,
        "lag_days_max": lag_days_sorted[-1] if lag_days_sorted else None,
        "csv_path": str(out_path),
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
