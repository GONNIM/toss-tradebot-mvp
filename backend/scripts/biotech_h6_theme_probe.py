"""WP5 · H6 테마 사전 실측 (PubMed + CT.gov · 2테마 분기 집계).

용도:
- 사전 커밋 테마 사전 v1 중 2개 (GLP-1 비만 · 탈모) 를 2015~2026 분기별 게재/등록 집계
- point-in-time 순위 규칙 근거 확보 (분기별 카운트)

원칙:
- 무인증 · 무료
- PubMed E-utilities · datetype=pdat
- CT.gov API v2 · studyFirstPostDate 필드 기간 필터
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import calendar
import csv
import json
import logging
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

LOG = logging.getLogger("biotech_h6_theme")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

UA = "TossTradebot-BiotechRadar/1.0 (sung2011103@naver.com)"

PUBMED = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"

# 사전 커밋 테마 사전 v2 · WP10 · 사용자 지시 · 키워드 서로소
# 주 6 테마 + 대조군 2 = 8 세트
THEMES = {
    "obesity_glp1": [
        "obesity", "GLP-1", "semaglutide", "tirzepatide", "liraglutide", "Wegovy", "Mounjaro",
    ],
    "hair_loss": [
        "androgenetic alopecia", "hair loss", "finasteride", "minoxidil", "dutasteride",
    ],
    "longevity_rejuvenation": [
        "longevity", "rejuvenation", "senolytics", "epigenetic reprogramming",
        "Yamanaka factor", "anti-aging",
    ],
    "meal_replacement_metabolic": [
        "meal replacement", "metabolic health", "GLP-1 combination", "caloric restriction",
    ],
    "hibernation_hypothermia": [
        "hibernation", "torpor", "therapeutic hypothermia", "induced torpor",
    ],
    "cognitive_memory": [
        "memory enhancement", "cognitive enhancer", "nootropic",
        "long-term potentiation", "engram", "memory reconsolidation",
    ],
    # 대조군 (별개 절 · 순위 산정 미참여 · 실측만)
    "control_nash": [
        "NASH", "nonalcoholic steatohepatitis", "MASH", "resmetirom", "obeticholic acid",
    ],
    "control_amyloid": [
        "amyloid beta", "aducanumab", "lecanemab", "gantenerumab",
        "alzheimer amyloid", "dementia amyloid",
    ],
}


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


def quarter_range(year: int, q: int) -> tuple[str, str]:
    start_month = 3 * (q - 1) + 1
    end_month = start_month + 2
    last_day = calendar.monthrange(year, end_month)[1]
    return (
        date(year, start_month, 1).strftime("%Y/%m/%d"),
        date(year, end_month, last_day).strftime("%Y/%m/%d"),
    )


def pubmed_count(client: httpx.Client, terms: list[str], mindate: str, maxdate: str) -> int:
    term = " OR ".join(f'"{t}"[Title/Abstract]' for t in terms)
    r = client.get(
        PUBMED,
        params={
            "db": "pubmed",
            "term": term,
            "mindate": mindate,
            "maxdate": maxdate,
            "datetype": "pdat",
            "retmode": "json",
            "retmax": 0,
            "tool": "TossTradebot-BiotechRadar",
            "email": "sung2011103@naver.com",
        },
        timeout=30.0,
    )
    r.raise_for_status()
    return int(r.json().get("esearchresult", {}).get("count", 0))


def ctgov_count(client: httpx.Client, terms: list[str], start_date: str, end_date: str) -> int:
    """CT.gov API v2 · studyFirstPostDate 범위 · totalCount."""
    query = " OR ".join(terms)
    r = client.get(
        CTGOV,
        params={
            "query.term": query,
            "filter.advanced": f"AREA[StudyFirstPostDate]RANGE[{start_date},{end_date}]",
            "countTotal": "true",
            "pageSize": 1,
            "format": "json",
        },
        timeout=30.0,
    )
    if r.status_code != 200:
        LOG.warning("CT.gov status=%s body=%s", r.status_code, r.text[:200])
        return -1
    return int(r.json().get("totalCount", 0))


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    LOG.info("git_sha=%s", sha)

    quarters = [(y, q) for y in range(2015, 2027) for q in (1, 2, 3, 4)]

    rows = []
    with httpx.Client(headers={"User-Agent": UA}) as client:
        for theme, terms in THEMES.items():
            LOG.info("theme=%s terms=%s", theme, terms)
            for y, q in quarters:
                pm_min, pm_max = quarter_range(y, q)
                # CT.gov 는 YYYY-MM-DD 형식
                ct_start = pm_min.replace("/", "-")
                ct_end = pm_max.replace("/", "-")
                pm_count = pubmed_count(client, terms, pm_min, pm_max)
                time.sleep(0.4)
                ct_count = ctgov_count(client, terms, ct_start, ct_end)
                time.sleep(0.4)
                rows.append(
                    {
                        "theme": theme,
                        "year": y,
                        "quarter": q,
                        "quarter_start": pm_min,
                        "quarter_end": pm_max,
                        "pubmed_count": pm_count,
                        "ctgov_count": ct_count,
                    }
                )
                if q == 4:
                    LOG.info(" %d Q4 done · pm=%d ct=%d", y, pm_count, ct_count)

    out_path = DATA_DIR / f"h6_theme_probe_v2_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["theme", "year", "quarter", "quarter_start", "quarter_end", "pubmed_count", "ctgov_count"],
        )
        w.writeheader()
        w.writerows(rows)

    # 요약: 테마별 시작·끝 분기 카운트
    summary = {"git_sha": sha, "csv_path": str(out_path), "themes": {}}
    for theme in THEMES:
        theme_rows = [r for r in rows if r["theme"] == theme]
        first = theme_rows[0]
        last = theme_rows[-1]
        # 최대 카운트 분기
        top_pm = max(theme_rows, key=lambda r: r["pubmed_count"])
        top_ct = max(theme_rows, key=lambda r: r["ctgov_count"])
        summary["themes"][theme] = {
            "n_quarters": len(theme_rows),
            "first_quarter": f"{first['year']}Q{first['quarter']}",
            "last_quarter": f"{last['year']}Q{last['quarter']}",
            "first_pubmed": first["pubmed_count"],
            "last_pubmed": last["pubmed_count"],
            "first_ctgov": first["ctgov_count"],
            "last_ctgov": last["ctgov_count"],
            "peak_pubmed_quarter": f"{top_pm['year']}Q{top_pm['quarter']}",
            "peak_pubmed_count": top_pm["pubmed_count"],
            "peak_ctgov_quarter": f"{top_ct['year']}Q{top_ct['quarter']}",
            "peak_ctgov_count": top_ct["ctgov_count"],
        }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
