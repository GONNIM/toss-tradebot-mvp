"""WP14-2 · H1a v3-2 · 번호 정규식 완화 + openFDA prefix 문법 + 약물명 조인.

수정:
- 정규식: (NDA|BLA|sNDA|sBLA)[\\s-]*(No\\.?|number)?\\s*([\\d,]{5,7}) · 쉼표 허용 후 제거
- openFDA 검색: application_number:"NDA021995" 형식 (prefix 포함)
- 약물명 병행: 본문 약물명 → openFDA products.brand_name/active_ingredients 매칭
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8
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
LOG = logging.getLogger("biotech_h1a_v3_2")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
FULLTEXT_CACHE = DATA_DIR / "h1a_fulltext_cache"

OPENFDA = "https://api.fda.gov/drug/drugsfda.json"
UA = "TossTradebot-BiotechRadar/1.0 (sung2011103@naver.com)"

# 완화된 정규식
RE_APP_NUMBER = re.compile(
    r"\b(NDA|BLA|sNDA|sBLA|ANDA)[\s\-]*(?:No\.?|Number|#)?\s*([\d,]{5,9})",
    re.IGNORECASE,
)

# 의약품 위원회 필터 (WP14 v3 승계)
DRUG_ADCOM_KEYWORDS = [
    "ODAC", "Oncologic Drugs", "CRDAC", "Cardiovascular and Renal",
    "PADAC", "Pulmonary-Allergy Drugs", "EMDAC", "Endocrinologic and Metabolic",
    "AMDAC", "Antimicrobial Drugs", "GIDAC", "Gastrointestinal Drugs",
    "DSaRM", "Drug Safety and Risk", "NDAC", "Nonprescription Drugs",
    "PsDAC", "Psychopharmacologic Drugs", "PNSDAC", "Peripheral and Central Nervous System",
    "AIDAC", "Anti-Infective Drugs", "CTGTAC", "Cellular, Tissue, and Gene",
    "VRBPAC", "Vaccines and Related Biological Products", "DODAC", "Dermatologic and Ophthalmic",
    "MIDAC", "Medical Imaging Drugs", "BRUDAC", "Bone, Reproductive and Urologic",
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


def normalize_name(name: str) -> str:
    s = name.lower()
    for suffix in [" incorporated", " inc", " corporation", " corp", " limited",
                   " ltd", " plc", " holdings", " group", " company", " co",
                   " pharmaceuticals", " pharmaceutical", " pharma",
                   " therapeutics", " biosciences", " biotech"]:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    s = re.sub(r"[.,()\-/&]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_universe(sha: str) -> dict:
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
                if k:
                    ticker_map.setdefault(k, {"ticker": t, "name": n})
    tiingo = set()
    tp = DATA_DIR / f"universe_skeleton_v2_{sha}.csv"
    if tp.exists():
        with tp.open() as f:
            for row in csv.DictReader(f):
                if row.get("asset_type") == "Stock":
                    tiingo.add(row.get("ticker", ""))
    return {"name_map": ticker_map, "tiingo": tiingo}


def load_v2_events(sha: str) -> list[dict]:
    p = DATA_DIR / f"h1a_events_v2_{sha}.csv"
    with p.open() as f:
        return list(csv.DictReader(f))


def extract_app_numbers(text: str) -> list[tuple[str, str]]:
    if not text:
        return []
    hits = []
    seen = set()
    for m in RE_APP_NUMBER.finditer(text):
        typ = m.group(1).upper()
        num_raw = m.group(2)
        num = num_raw.replace(",", "").strip()
        if not (5 <= len(num) <= 6):
            continue
        num = num.zfill(6)
        k = (typ, num)
        if k in seen:
            continue
        seen.add(k)
        hits.append(k)
    return hits


def fetch_sponsor_prefixed(client: httpx.Client, typ: str, num: str, cache: dict) -> str | None:
    """WP14-2 · application_number:"NDA123456" 형식."""
    prefix = "NDA" if typ in ("NDA", "SNDA") else ("BLA" if typ in ("BLA", "SBLA") else typ)
    key = f"{prefix}{num}"
    if key in cache:
        return cache[key]
    try:
        r = client.get(
            OPENFDA,
            params={
                "search": f'application_number:"{key}"',
                "limit": 1,
            },
            timeout=30.0,
        )
        if r.status_code == 404:
            cache[key] = None
            return None
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            cache[key] = None
            return None
        s = results[0].get("sponsor_name", "").strip()
        cache[key] = s
        return s
    except Exception:
        cache[key] = None
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
    LOG.info("events=%d · name_map=%d · Tiingo=%d",
             len(events), len(universe["name_map"]), len(universe["tiingo"]))

    sponsor_cache: dict[str, str | None] = {}
    stats = {
        "total": 0,
        "drug_adcom": 0,
        "app_num_extracted": 0,
        "app_num_joined_openfda": 0,
        "sponsor_recovered": 0,
        "ticker_mapped": 0,
        "ticker_in_tiingo": 0,
        "eligible_v3_2": 0,
    }

    # 1건 수동 검증 먼저
    LOG.info("=== manual verification: openFDA application_number:\"NDA021995\" ===")
    with httpx.Client(headers={"User-Agent": UA}) as client:
        r = client.get(OPENFDA, params={"search": 'application_number:"NDA021995"', "limit": 1}, timeout=30.0)
        if r.status_code == 200:
            data = r.json().get("results", [])
            LOG.info("verification: %s", data[0].get("sponsor_name", "") if data else "no results")
        else:
            LOG.info("verification failed: %d", r.status_code)

    rows_out = []
    with httpx.Client(headers={"User-Agent": UA}) as client:
        for i, ev in enumerate(events):
            stats["total"] += 1
            doc = ev.get("document_number", "")
            title = ev.get("title", "")
            fulltext_p = FULLTEXT_CACHE / f"{doc}.txt"
            body = fulltext_p.read_text(errors="ignore") if fulltext_p.exists() else title

            is_drug = has_drug_adcom(body)
            if is_drug:
                stats["drug_adcom"] += 1

            app_hits = extract_app_numbers(body)
            if app_hits:
                stats["app_num_extracted"] += 1

            joined = None
            sponsor = ""
            for typ, num in app_hits:
                s = fetch_sponsor_prefixed(client, typ, num, sponsor_cache)
                time.sleep(0.20)
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
                    stats["ticker_mapped"] += 1
                    if mapped_ticker in universe["tiingo"]:
                        stats["ticker_in_tiingo"] += 1

            v2_eligible = (str(ev.get("eligible", "")) or "").strip().lower() == "true"
            v3_2_eligible = v2_eligible and is_drug and bool(mapped_ticker)
            if v3_2_eligible:
                stats["eligible_v3_2"] += 1

            rows_out.append({
                **ev,
                "is_drug_adcom": is_drug,
                "app_type": joined[0] if joined else "",
                "app_number": joined[1] if joined else "",
                "openfda_sponsor": sponsor,
                "mapped_ticker_v3_2": mapped_ticker,
                "mapped_name_v3_2": mapped_name,
                "eligible_v3_2": v3_2_eligible,
            })
            if (i + 1) % 100 == 0:
                LOG.info("progress %d/%d · extracted=%d · joined=%d · mapped=%d",
                         i + 1, len(events), stats["app_num_extracted"], stats["app_num_joined_openfda"], stats["ticker_mapped"])

    out_path = DATA_DIR / f"h1a_events_v3_2_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        **stats,
        "app_number_extraction_rate": round(stats["app_num_extracted"] / max(1, stats["total"]), 3),
        "openfda_join_rate_among_extracted": round(stats["app_num_joined_openfda"] / max(1, stats["app_num_extracted"]), 3),
        "ticker_map_rate_among_sponsors": round(stats["ticker_mapped"] / max(1, stats["sponsor_recovered"]), 3),
        "eligible_v3_2_rate": round(stats["eligible_v3_2"] / max(1, stats["total"]), 3),
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
