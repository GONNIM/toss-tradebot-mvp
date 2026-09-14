"""WP9 · H1a full_text_xml_url 다운로드 + DATES/Agenda 절 파싱.

용도:
- WP2 v1 abstract 파싱은 신청사 1.5% · 회의일 4.6% 로 실질 불가
- Federal Register 공고 본문 XML/HTML 은 표준 `DATES:` · `AGENDA:` · `Contact Person:` 절 포함
- 457건 raw_text_url 순차 다운로드 → 캐시 → 파싱

원칙:
- 무인증 · Federal Register 공식 · 간격 0.5s
- 캐시: backend/data/h1a_fulltext_cache/{document_number}.txt (재실행 시 재다운로드 방지)
- 파싱 실패 시 raw_text 필드 별도 저장 (사후 분석 대비)
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
from datetime import datetime
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

LOG = logging.getLogger("biotech_h1a_fulltext")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
CACHE_DIR = DATA_DIR / "h1a_fulltext_cache"
CACHE_DIR.mkdir(exist_ok=True)

UA = "TossTradebot-BiotechRadar/1.0 (sung2011103@naver.com)"
REQ_INTERVAL = 0.5

MONTH = r"(January|February|March|April|May|June|July|August|September|October|November|December)"
RE_DATES_LINE = re.compile(
    rf"\b{MONTH}\s+(\d{{1,2}})(?:[-–]\s*\d{{1,2}})?,\s*(\d{{4}})",
    re.IGNORECASE,
)


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


def parse_dates_section(text: str, pub_date: str) -> str | None:
    """DATES: 절에서 회의일 추출 (pub_date 이후 12개월 이내 첫 매치)."""
    if not text:
        return None
    # DATES: 절 추출 (다음 대문자 헤더까지)
    m = re.search(
        r"DATES\s*:(.*?)(?=\n[A-Z][A-Z ]+:|\nADDRESSES\s*:|\nFOR FURTHER|\nAGENDA\s*:|\Z)",
        text,
        re.DOTALL,
    )
    dates_body = m.group(1) if m else text[:4000]
    return _first_date_after(dates_body, pub_date)


def _first_date_after(body: str, pub_date: str) -> str | None:
    try:
        pub = datetime.strptime(pub_date, "%Y-%m-%d").date()
    except Exception:
        return None
    for month_name, day, year in RE_DATES_LINE.findall(body):
        try:
            dt = datetime.strptime(f"{month_name} {day} {year}", "%B %d %Y").date()
        except Exception:
            continue
        lag = (dt - pub).days
        if 0 <= lag <= 365:
            return dt.strftime("%Y-%m-%d")
    return None


def parse_agenda_section(text: str) -> dict:
    """AGENDA/Agenda 절에서 신청사·약물명·위원회 추출 (best effort)."""
    out = {"sponsor": "", "drug": "", "committee": ""}
    if not text:
        return out
    m = re.search(
        r"(?:AGENDA|Agenda)\s*:(.*?)(?=\n[A-Z][A-Z ]+:|\nADDRESSES\s*:|\nFOR FURTHER|\nSUPPLEMENTARY|\Z)",
        text,
        re.DOTALL,
    )
    body = m.group(1) if m else text[:6000]

    # 신청사: "applicant", "sponsor", "manufacturer"
    for pat in [
        r"(?:sponsor|applicant|manufacturer|marketed by|proposed by)\s*[:\-]?\s*([A-Z][A-Za-z0-9\-.,& ]{2,80}?)(?:[,.]|\s+for\s+|\s+of\s+|\s*\(|\n)",
        r"application\s+(?:from|by)\s+([A-Z][A-Za-z0-9\-.,& ]{2,80}?)(?:[,.]|\s+for\s+|\s+of\s+|\s*\()",
        r"NDA\s+\d+\s+.*?by\s+([A-Z][A-Za-z0-9\-.,& ]{2,80}?)(?:[,.]|\s+for\s+|\s+of\s+|\s*\()",
    ]:
        mm = re.search(pat, body)
        if mm:
            out["sponsor"] = mm.group(1).strip()
            break

    # 약물명 = 대문자 시작 단어 + (성분) 형태 또는 NDA/BLA 뒤 명명
    for pat in [
        r"\b([A-Z][a-z]{3,25})\s*\(([a-z][a-z\- ]{2,30})\)",
        r"(?:NDA|BLA|sNDA)\s+\d+\s+for\s+([A-Za-z][A-Za-z0-9\-]{3,30})",
    ]:
        mm = re.search(pat, body)
        if mm:
            out["drug"] = mm.group(1)
            break

    for kw in [
        "Oncologic Drugs Advisory Committee",
        "Cardiovascular and Renal Drugs Advisory Committee",
        "Endocrinologic and Metabolic Drugs Advisory Committee",
        "Peripheral and Central Nervous System Drugs Advisory Committee",
        "Psychopharmacologic Drugs Advisory Committee",
        "Vaccines and Related Biological Products Advisory Committee",
        "Anti-Infective Drugs Advisory Committee",
        "Cellular, Tissue, and Gene Therapies Advisory Committee",
        "Pulmonary-Allergy Drugs Advisory Committee",
        "Gastrointestinal Drugs Advisory Committee",
        "Dermatologic and Ophthalmic Drugs Advisory Committee",
        "Nonprescription Drugs Advisory Committee",
        "Pediatric Advisory Committee",
    ]:
        if kw.lower() in text.lower():
            out["committee"] = kw
            break
    return out


def normalize_name(name: str) -> str:
    s = name.lower()
    for suffix in [
        " incorporated", " inc", " corporation", " corp", " limited",
        " ltd", " plc", " holdings", " group", " company", " co",
        " pharmaceuticals", " pharmaceutical", " pharma",
        " therapeutics", " biosciences", " biotech",
    ]:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    s = re.sub(r"[.,()\-/&]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_ticker_map(sha: str) -> dict:
    path = DATA_DIR / f"biotech_ticker_set_{sha}.csv"
    if not path.exists():
        return {}
    out = {}
    with path.open() as f:
        for row in csv.DictReader(f):
            n = (row.get("name") or "").strip()
            t = (row.get("ticker") or "").strip()
            if not n or not t or t == "-":
                continue
            k = normalize_name(n)
            if k and k not in out:
                out[k] = {"ticker": t, "name": n}
    return out


def download_fulltext(client: httpx.Client, doc_num: str, raw_url: str) -> str | None:
    cache = CACHE_DIR / f"{doc_num}.txt"
    if cache.exists():
        return cache.read_text(errors="ignore")
    if not raw_url:
        return None
    try:
        r = client.get(raw_url, timeout=60.0)
        if r.status_code == 200:
            cache.write_text(r.text)
            return r.text
    except Exception as e:
        LOG.debug("download fail %s: %s", doc_num, e)
    return None


def fetch_events_index(client: httpx.Client) -> list[dict]:
    """WP2 수집기와 동일 조건 · 457건 index."""
    BASE = "https://www.federalregister.gov/api/v1/documents.json"
    records = []
    page = 1
    while True:
        r = client.get(
            BASE,
            params={
                "conditions[term]": "Advisory Committee",
                "conditions[agencies][]": "food-and-drug-administration",
                "conditions[publication_date][gte]": "2021-01-01",
                "conditions[publication_date][lte]": "2026-09-05",
                "per_page": 100,
                "page": page,
                "order": "oldest",
                "fields[]": [
                    "title", "publication_date", "type",
                    "html_url", "document_number", "raw_text_url",
                ],
            },
            timeout=30.0,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        if not results:
            break
        records.extend(results)
        if not data.get("next_page_url"):
            break
        page += 1
        time.sleep(REQ_INTERVAL)
    return records


def event_eligible(pub_date: str, meeting_date: str) -> tuple[bool, str]:
    """공고일+1 > D-5 (사전 5영업일 미만) 이벤트 제외."""
    try:
        pub = datetime.strptime(pub_date, "%Y-%m-%d").date()
        meet = datetime.strptime(meeting_date, "%Y-%m-%d").date()
    except Exception:
        return False, "bad_date"
    lag = (meet - pub).days
    if lag < 6:  # 공고+1일 부터 D-5 확보 위해 최소 6일 필요
        return False, "short_lead"
    return True, ""


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    LOG.info("git_sha=%s", sha)
    ticker_map = load_ticker_map(sha)

    with httpx.Client(headers={"User-Agent": UA}) as client:
        events = fetch_events_index(client)
        LOG.info("index fetched: %d", len(events))

        stats = {
            "total": 0,
            "fulltext_downloaded": 0,
            "meeting_date_parsed": 0,
            "sponsor_parsed": 0,
            "drug_parsed": 0,
            "committee_parsed": 0,
            "ticker_mapped": 0,
            "eligible": 0,
            "excluded_short_lead": 0,
            "excluded_no_meeting_date": 0,
        }
        rows = []
        for idx, ev in enumerate(events):
            stats["total"] += 1
            doc_num = ev.get("document_number", "")
            pub_date = ev.get("publication_date", "")
            raw_url = ev.get("raw_text_url", "")
            title = ev.get("title", "")

            text = download_fulltext(client, doc_num, raw_url)
            if text:
                stats["fulltext_downloaded"] += 1
                time.sleep(REQ_INTERVAL)
            else:
                text = title  # fallback

            meeting_date = parse_dates_section(text, pub_date) if text else None
            agenda = parse_agenda_section(text) if text else {"sponsor": "", "drug": "", "committee": ""}

            if meeting_date:
                stats["meeting_date_parsed"] += 1
            if agenda["sponsor"]:
                stats["sponsor_parsed"] += 1
            if agenda["drug"]:
                stats["drug_parsed"] += 1
            if agenda["committee"]:
                stats["committee_parsed"] += 1

            mapped_ticker = ""
            mapped_name = ""
            if agenda["sponsor"]:
                key = normalize_name(agenda["sponsor"])
                if key in ticker_map:
                    mapped_ticker = ticker_map[key]["ticker"]
                    mapped_name = ticker_map[key]["name"]
                    stats["ticker_mapped"] += 1

            eligible = False
            exclusion = ""
            if meeting_date:
                ok, reason = event_eligible(pub_date, meeting_date)
                eligible = ok
                exclusion = reason
                if ok:
                    stats["eligible"] += 1
                elif reason == "short_lead":
                    stats["excluded_short_lead"] += 1
            else:
                stats["excluded_no_meeting_date"] += 1
                exclusion = "no_meeting_date"

            rows.append(
                {
                    "publication_date": pub_date,
                    "meeting_date": meeting_date or "",
                    "committee": agenda["committee"],
                    "sponsor_raw": agenda["sponsor"],
                    "drug_raw": agenda["drug"],
                    "mapped_ticker": mapped_ticker,
                    "mapped_name": mapped_name,
                    "eligible": eligible,
                    "exclusion_reason": exclusion,
                    "document_number": doc_num,
                    "html_url": ev.get("html_url", ""),
                    "title": title[:200],
                }
            )
            if (idx + 1) % 50 == 0:
                LOG.info("progress %d/%d · ft %d · meeting %d · sponsor %d",
                         idx + 1, len(events),
                         stats["fulltext_downloaded"],
                         stats["meeting_date_parsed"],
                         stats["sponsor_parsed"])

    out_path = DATA_DIR / f"h1a_events_v2_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "publication_date", "meeting_date", "committee",
                "sponsor_raw", "drug_raw",
                "mapped_ticker", "mapped_name",
                "eligible", "exclusion_reason",
                "document_number", "html_url", "title",
            ],
        )
        w.writeheader()
        w.writerows(rows)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        **stats,
        "meeting_parse_rate": round(stats["meeting_date_parsed"] / max(1, stats["total"]), 3),
        "sponsor_parse_rate": round(stats["sponsor_parsed"] / max(1, stats["total"]), 3),
        "mapping_rate_among_sponsors": round(
            stats["ticker_mapped"] / max(1, stats["sponsor_parsed"]), 3
        ),
        "eligible_rate": round(stats["eligible"] / max(1, stats["total"]), 3),
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
