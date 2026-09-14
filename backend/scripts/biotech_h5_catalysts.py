"""WP17-2 · H5 해외 촉매 · openFDA drugsfda GLP-1 승인일 (WP19 v2 · 2026-09-08 · 재정의).

용도:
- semaglutide 등 사전 커밋 GLP-1 성분 drugsfda submissions 승인일 (2019~2026)
- **WP19 v2 필터 (사전 커밋)**: `submission_type = ORIG` **OR** `submission_class_code = EFFICACY` (적응증 확장) 만
  · **라벨·CMC (LABEL/CHEMISTRY/MANUFACTURING) 기타 SUPPL 제외**
- **WP19 v2 시각 규칙**: 미국 승인일 = 미국 장 마감 후 도착 간주 · **D = 다음 한국 거래일** (KRX 캘린더 근사 = KS200 시계열 존재일)
- 산출: h5_catalysts_v2_{sha}.csv · 사후 조정 금지 (사전 커밋)

원칙:
- 무인증 · openFDA 무료 · rate 240/min
- submission_status = "AP" (approved) 만
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import subprocess
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h5_catalysts")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
OPENFDA = "https://api.fda.gov/drug/drugsfda.json"
UA = "TossTradebot-BiotechRadar/1.0 (sung2011103@naver.com)"

# GLP-1 계열 성분 (사전 커밋 · 사후 조정 금지)
GLP1_INGREDIENTS = [
    "SEMAGLUTIDE",
    "TIRZEPATIDE",
    "LIRAGLUTIDE",
    "DULAGLUTIDE",
    "EXENATIDE",
    "LIXISENATIDE",
    "ALBIGLUTIDE",
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


def load_kr_trading_days() -> set[str]:
    """KRX 거래일 집합 = h5_prices KS200 시계열 존재 날짜."""
    p = PROJECT_ROOT / "backend" / "data" / "h5_prices_add7af7.csv"
    days = set()
    if not p.exists():
        return days
    with p.open() as f:
        for row in csv.DictReader(f):
            if row.get("ticker") == "KS200":
                days.add(row.get("date", ""))
    return days


def next_kr_trading_day(us_date_str: str, kr_days: set[str]) -> str:
    """미국 승인일 → 다음 KR 거래일 (WP19 v2 규칙).

    미국 장 마감 후 도착 간주 → 최소 KST 다음 캘린더일 · 그 이후 첫 KR 거래일.
    """
    try:
        d = datetime.strptime(us_date_str, "%Y%m%d").date()
    except Exception:
        return ""
    candidate = d + timedelta(days=1)
    for step in range(0, 21):
        k = (candidate + timedelta(days=step)).strftime("%Y-%m-%d")
        if k in kr_days:
            return k
    # fallback: KST +1 캘린더
    return candidate.strftime("%Y-%m-%d")


def kst_dday(us_date_str: str) -> str:
    """호환 유지 (fixture 등) · WP19 이후 v2 함수 사용."""
    try:
        d = datetime.strptime(us_date_str, "%Y%m%d").date()
    except Exception:
        return ""
    return (d + timedelta(days=1)).strftime("%Y-%m-%d")


def fetch_ingredient(client: httpx.Client, ingredient: str) -> list[dict]:
    """openFDA drugsfda · openfda.substance_name 매치 · 전체 페이지."""
    all_rows = []
    skip = 0
    limit = 100
    while True:
        r = client.get(
            OPENFDA,
            params={
                "search": f'openfda.substance_name:"{ingredient}"',
                "limit": limit,
                "skip": skip,
            },
            timeout=30.0,
        )
        if r.status_code == 404:
            break  # no results
        r.raise_for_status()
        j = r.json()
        results = j.get("results", [])
        if not results:
            break
        all_rows.extend(results)
        total = j.get("meta", {}).get("results", {}).get("total", 0)
        skip += len(results)
        if skip >= total or not results:
            break
        time.sleep(0.4)
    return all_rows


def extract_ap_events(records: list[dict], ingredient: str, kr_days: set[str]) -> list[dict]:
    """WP19 v2 필터 · ORIG OR EFFICACY 만."""
    events = []
    for rec in records:
        app_no = rec.get("application_number", "")
        sponsor = rec.get("sponsor_name", "")
        products = rec.get("products", [])
        brand_names = "|".join(sorted(set(
            p.get("brand_name", "") for p in products if p.get("brand_name")
        )))
        for sub in rec.get("submissions", []):
            if sub.get("submission_status") != "AP":
                continue
            sub_type = (sub.get("submission_type") or "").upper()
            class_code = (sub.get("submission_class_code") or "").upper()
            # WP19 사전 커밋 필터
            if sub_type != "ORIG" and class_code != "EFFICACY":
                continue
            sub_date_us = sub.get("submission_status_date", "")
            if not sub_date_us or not sub_date_us.startswith(("2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026")):
                continue
            events.append({
                "ingredient": ingredient,
                "application_number": app_no,
                "submission_type": sub_type,
                "submission_class_code": class_code,
                "submission_number": sub.get("submission_number", ""),
                "submission_status_date_us": sub_date_us,
                "d_day_kst": next_kr_trading_day(sub_date_us, kr_days),
                "sponsor_name": sponsor,
                "brand_names": brand_names,
                "review_priority": sub.get("review_priority", ""),
            })
    return events


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    LOG.info("git_sha=%s · ingredients=%d", sha, len(GLP1_INGREDIENTS))

    kr_days = load_kr_trading_days()
    LOG.info("KR trading days loaded: %d", len(kr_days))
    all_events = []
    per_ingredient = {}
    with httpx.Client(headers={"User-Agent": UA}) as client:
        for ing in GLP1_INGREDIENTS:
            LOG.info("querying openFDA · %s", ing)
            try:
                records = fetch_ingredient(client, ing)
            except Exception as e:
                LOG.error("failed %s: %s", ing, e)
                per_ingredient[ing] = {"applications": 0, "ap_events": 0, "error": str(e)}
                continue
            events = extract_ap_events(records, ing, kr_days)
            all_events.extend(events)
            per_ingredient[ing] = {
                "applications": len(records),
                "ap_events_2019_2026_filtered": len(events),
            }
            LOG.info("  apps=%d · AP events (ORIG|EFFICACY)=%d", len(records), len(events))
            time.sleep(0.4)

    # dedup by (application_number, submission_number)
    seen = set()
    unique = []
    for e in all_events:
        k = (e["application_number"], e["submission_number"])
        if k in seen:
            continue
        seen.add(k)
        unique.append(e)
    unique.sort(key=lambda e: e["submission_status_date_us"])

    out_path = DATA_DIR / f"h5_catalysts_v2_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "d_day_kst", "submission_status_date_us", "ingredient",
            "sponsor_name", "brand_names", "application_number",
            "submission_type", "submission_class_code",
            "submission_number", "review_priority",
        ])
        w.writeheader()
        w.writerows(unique)

    year_dist = {}
    for e in unique:
        y = e["submission_status_date_us"][:4]
        year_dist[y] = year_dist.get(y, 0) + 1

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "per_ingredient": per_ingredient,
        "total_ap_events_2019_2026": len(unique),
        "year_dist": year_dist,
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
