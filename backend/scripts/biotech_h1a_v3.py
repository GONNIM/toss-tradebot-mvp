"""WP14 · H1a v3 · NDA 번호 조인.

용도:
- WP9 fulltext 캐시에서 (NDA|BLA|sNDA|sBLA) 번호 추출
- openFDA drugsfda 로 sponsor_name 조회 · 회사명 정규화
- Tiingo universe_skeleton_v2 티커 매핑

원칙:
- 의약품 자문위 목록 (ODAC·CRDAC·PADAC·EMDAC·AMDAC·GIDAC·DSaRM·NDAC 등) 사전 커밋 필터
- 무인증 openFDA · 240/min
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import re
import subprocess
import time
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h1a_v3")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
FULLTEXT_CACHE = DATA_DIR / "h1a_fulltext_cache"

OPENFDA = "https://api.fda.gov/drug/drugsfda.json"
UA = "TossTradebot-BiotechRadar/1.0 (sung2011103@naver.com)"

# 사전 커밋 의약품 AdCom 목록 (v2 committee 파싱과 병용)
DRUG_ADCOM_KEYWORDS = [
    "ODAC", "Oncologic Drugs Advisory Committee",
    "CRDAC", "Cardiovascular and Renal Drugs Advisory Committee",
    "PADAC", "Pulmonary-Allergy Drugs Advisory Committee",
    "EMDAC", "Endocrinologic and Metabolic Drugs Advisory Committee",
    "AMDAC", "Antimicrobial Drugs Advisory Committee",
    "GIDAC", "Gastrointestinal Drugs Advisory Committee",
    "DSaRM", "Drug Safety and Risk Management Advisory Committee",
    "NDAC", "Nonprescription Drugs Advisory Committee",
    "PsDAC", "Psychopharmacologic Drugs Advisory Committee",
    "PNSDAC", "Peripheral and Central Nervous System Drugs Advisory Committee",
    "AIDAC", "Anti-Infective Drugs Advisory Committee",
    "CTGTAC", "Cellular, Tissue, and Gene Therapies Advisory Committee",
    "VRBPAC", "Vaccines and Related Biological Products Advisory Committee",
    "DODAC", "Dermatologic and Ophthalmic Drugs Advisory Committee",
    "MIDAC", "Medical Imaging Drugs Advisory Committee",
    "BRUDAC", "Bone, Reproductive and Urologic Drugs Advisory Committee",
]

RE_APP_NUMBER = re.compile(r"\b(NDA|BLA|sNDA|sBLA|ANDA)\s*[Nn]?[Oo]?\.?\s*(\d{5,6})", re.IGNORECASE)


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


def load_universe(sha: str) -> dict[str, dict]:
    """Tiingo universe_skeleton_v2 → normalized_name → ticker (best effort · Tiingo 는 회사명 필드 없음).

    Tiingo supported_tickers 는 ticker+exchange만 있음 · 회사명 매핑 필요.
    → biotech_ticker_set 를 rescue 로 사용.
    """
    ticker_map = {}
    src = DATA_DIR / f"biotech_ticker_set_{sha}.csv"
    if src.exists():
        with src.open() as f:
            for row in csv.DictReader(f):
                n = (row.get("name") or "").strip()
                t = (row.get("ticker") or "").strip()
                if not n or not t or t == "-":
                    continue
                k = normalize_name(n)
                if k and k not in ticker_map:
                    ticker_map[k] = {"ticker": t, "name": n}
    # Tiingo universe list of tickers (Tiingo 만) for eligible-ticker check
    tiingo = set()
    tp = DATA_DIR / f"universe_skeleton_v2_{sha}.csv"
    if tp.exists():
        with tp.open() as f:
            for row in csv.DictReader(f):
                if row.get("asset_type") == "Stock":
                    tiingo.add(row.get("ticker", ""))
    return {"name_map": ticker_map, "tiingo_set": tiingo}


def load_v2_events(sha: str) -> list[dict]:
    p = DATA_DIR / f"h1a_events_v2_{sha}.csv"
    with p.open() as f:
        return list(csv.DictReader(f))


def extract_app_numbers_from_cache(doc_num: str) -> list[tuple[str, str]]:
    p = FULLTEXT_CACHE / f"{doc_num}.txt"
    if not p.exists():
        return []
    text = p.read_text(errors="ignore")
    hits = []
    seen = set()
    for m in RE_APP_NUMBER.finditer(text):
        typ = m.group(1).upper()
        num = m.group(2).zfill(6)
        k = (typ, num)
        if k in seen:
            continue
        seen.add(k)
        hits.append(k)
    return hits


def fetch_sponsor(client: httpx.Client, app_no_6digit: str, cache: dict) -> str | None:
    """openFDA drugsfda application_number 조회 → sponsor_name."""
    if app_no_6digit in cache:
        return cache[app_no_6digit]
    try:
        r = client.get(
            OPENFDA,
            params={
                "search": f"application_number:{app_no_6digit}",
                "limit": 1,
            },
            timeout=30.0,
        )
        if r.status_code == 404:
            cache[app_no_6digit] = None
            return None
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            cache[app_no_6digit] = None
            return None
        s = results[0].get("sponsor_name", "").strip()
        cache[app_no_6digit] = s
        return s
    except Exception as e:
        LOG.debug("openFDA fail %s: %s", app_no_6digit, e)
        cache[app_no_6digit] = None
        return None


def has_drug_adcom(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    return any(kw.lower() in lower for kw in DRUG_ADCOM_KEYWORDS)


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    LOG.info("git_sha=%s", sha)

    events = load_v2_events(sha)
    universe = load_universe(sha)
    LOG.info("events=%d · biotech name-map=%d · Tiingo=%d",
             len(events), len(universe["name_map"]), len(universe["tiingo_set"]))

    sponsor_cache: dict[str, str | None] = {}
    stats = {
        "total": 0,
        "drug_adcom": 0,
        "app_num_extracted": 0,
        "app_num_joined_openfda": 0,
        "sponsor_recovered": 0,
        "ticker_mapped_biotech_set": 0,
        "ticker_in_tiingo_universe": 0,
        "eligible_v3": 0,  # 공고+1 > D-5 조건 + committee 제약 + ticker 매핑 성공
    }

    rows_out = []
    with httpx.Client(headers={"User-Agent": UA}) as client:
        for ev in events:
            stats["total"] += 1
            doc = ev.get("document_number", "")
            title = ev.get("title", "")
            fulltext_p = FULLTEXT_CACHE / f"{doc}.txt"
            body = fulltext_p.read_text(errors="ignore") if fulltext_p.exists() else title

            # 필터 1: 의약품 AdCom 여부
            is_drug = has_drug_adcom(body)
            if is_drug:
                stats["drug_adcom"] += 1

            # 번호 추출
            app_hits = extract_app_numbers_from_cache(doc)
            if app_hits:
                stats["app_num_extracted"] += 1

            joined = None
            sponsor = ""
            for typ, num in app_hits:
                s = fetch_sponsor(client, num, sponsor_cache)
                time.sleep(0.25)
                if s:
                    joined = (typ, num)
                    sponsor = s
                    break

            if joined:
                stats["app_num_joined_openfda"] += 1
            if sponsor:
                stats["sponsor_recovered"] += 1

            mapped_ticker = ""
            mapped_name = ""
            if sponsor:
                k = normalize_name(sponsor)
                if k in universe["name_map"]:
                    mapped_ticker = universe["name_map"][k]["ticker"]
                    mapped_name = universe["name_map"][k]["name"]
                    stats["ticker_mapped_biotech_set"] += 1
                    if mapped_ticker in universe["tiingo_set"]:
                        stats["ticker_in_tiingo_universe"] += 1

            v2_eligible = (str(ev.get("eligible", "")) or "").strip().lower() == "true"

            v3_eligible = v2_eligible and is_drug and bool(mapped_ticker)
            if v3_eligible:
                stats["eligible_v3"] += 1

            rows_out.append({
                **ev,
                "is_drug_adcom": is_drug,
                "app_type": joined[0] if joined else "",
                "app_number": joined[1] if joined else "",
                "openfda_sponsor": sponsor,
                "mapped_ticker_v3": mapped_ticker,
                "mapped_name_v3": mapped_name,
                "eligible_v3": v3_eligible,
            })

    out_path = DATA_DIR / f"h1a_events_v3_{sha}.csv"
    fieldnames = list(rows_out[0].keys()) if rows_out else []
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        **stats,
        "app_number_extraction_rate": round(stats["app_num_extracted"] / max(1, stats["total"]), 3),
        "openfda_join_rate_among_extracted": round(
            stats["app_num_joined_openfda"] / max(1, stats["app_num_extracted"]), 3
        ),
        "ticker_map_rate_among_sponsors": round(
            stats["ticker_mapped_biotech_set"] / max(1, stats["sponsor_recovered"]), 3
        ),
        "eligible_v3_rate": round(stats["eligible_v3"] / max(1, stats["total"]), 3),
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
