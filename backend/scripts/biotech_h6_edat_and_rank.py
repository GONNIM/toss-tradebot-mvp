"""WP15 · H6 실행 준비 · EDAT 재실행 + CT.gov 스폰서 매핑 + 분기 순위표.

용도:
- 8세트 × 48분기 PubMed 를 datetype=edat (Entrez 등록일) 로 재실행 · pdat 와 차이
- CT.gov 스폰서 매핑 (obesity_glp1 · 모든 테마) → Tiingo 우주 매핑 → 분기 소속 상장사
- 분기별 순위표 (2015Q1~2026Q2 · z-점수 60/40) · 3분위 · 비만·GLP-1 상위 3분위 진입 분기

원칙:
- 무인증 · CT.gov API v2 · leadSponsor.name
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import calendar
import csv
import json
import logging
import re
import subprocess
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, pstdev

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h6_edat_rank")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

PUBMED = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"
UA = "TossTradebot-BiotechRadar/1.0 (sung2011103@naver.com)"

# WP10 사전 커밋 사전 v1 · 8 세트
THEMES = {
    "obesity_glp1": ["obesity", "GLP-1", "semaglutide", "tirzepatide", "liraglutide", "Wegovy", "Mounjaro"],
    "hair_loss": ["androgenetic alopecia", "hair loss", "finasteride", "minoxidil", "dutasteride"],
    "longevity_rejuvenation": ["longevity", "rejuvenation", "senolytics", "epigenetic reprogramming", "Yamanaka factor", "anti-aging"],
    "meal_replacement_metabolic": ["meal replacement", "metabolic health", "GLP-1 combination", "caloric restriction"],
    "hibernation_hypothermia": ["hibernation", "torpor", "therapeutic hypothermia", "induced torpor"],
    "cognitive_memory": ["memory enhancement", "cognitive enhancer", "nootropic", "long-term potentiation", "engram", "memory reconsolidation"],
    "control_nash": ["NASH", "nonalcoholic steatohepatitis", "MASH", "resmetirom", "obeticholic acid"],
    "control_amyloid": ["amyloid beta", "aducanumab", "lecanemab", "gantenerumab", "alzheimer amyloid", "dementia amyloid"],
}
MAIN_THEMES = [t for t in THEMES if not t.startswith("control_")]


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


def quarter_range(y: int, q: int) -> tuple[str, str]:
    sm = 3 * (q - 1) + 1
    em = sm + 2
    last = calendar.monthrange(y, em)[1]
    return date(y, sm, 1).strftime("%Y/%m/%d"), date(y, em, last).strftime("%Y/%m/%d")


def pubmed_count(client: httpx.Client, terms: list[str], mindate: str, maxdate: str, datetype: str = "edat") -> int:
    """WP15-2 · retry + backoff (5s → 15s → 45s)."""
    term = " OR ".join(f'"{t}"[Title/Abstract]' for t in terms)
    params = {
        "db": "pubmed", "term": term, "mindate": mindate, "maxdate": maxdate,
        "datetype": datetype, "retmode": "json", "retmax": 0,
        "tool": "TossTradebot-BiotechRadar", "email": "sung2011103@naver.com",
    }
    backoffs = [5, 15, 45]
    last_err = None
    for attempt in range(len(backoffs) + 1):
        try:
            r = client.get(PUBMED, params=params, timeout=30.0)
            if r.status_code == 200:
                return int(r.json().get("esearchresult", {}).get("count", 0))
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = f"http {r.status_code}"
            else:
                r.raise_for_status()
        except Exception as e:
            last_err = str(e)[:100]
        if attempt < len(backoffs):
            LOG.warning("pubmed retry %d after %ds · last=%s", attempt + 1, backoffs[attempt], last_err)
            time.sleep(backoffs[attempt])
    LOG.error("pubmed exhausted retries · last=%s · returning 0", last_err)
    return 0


def ctgov_sponsors(client: httpx.Client, terms: list[str], start_date: str, end_date: str, max_pages: int = 5) -> list[str]:
    """분기 내 신규 임상의 leadSponsor.name 목록 (중복 포함) · pageSize 100."""
    query = " OR ".join(terms)
    sponsors = []
    next_token = None
    for page in range(max_pages):
        params = {
            "query.term": query,
            "filter.advanced": f"AREA[StudyFirstPostDate]RANGE[{start_date},{end_date}]",
            "pageSize": 100,
            "format": "json",
            "fields": "protocolSection.identificationModule.nctId,protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
        }
        if next_token:
            params["pageToken"] = next_token
        r = client.get(CTGOV, params=params, timeout=30.0)
        if r.status_code != 200:
            break
        j = r.json()
        for st in j.get("studies", []):
            spon = (
                st.get("protocolSection", {})
                .get("sponsorCollaboratorsModule", {})
                .get("leadSponsor", {})
                .get("name", "")
            )
            if spon:
                sponsors.append(spon)
        next_token = j.get("nextPageToken")
        if not next_token:
            break
        time.sleep(0.3)
    return sponsors


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


def zscore(vals: list[float]) -> list[float]:
    if not vals:
        return []
    m = mean(vals)
    s = pstdev(vals) or 1.0
    return [(v - m) / s for v in vals]


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    LOG.info("git_sha=%s", sha)

    universe = load_universe(sha)
    LOG.info("universe · biotech_name_map=%d · Tiingo Stock=%d", len(universe["name_map"]), len(universe["tiingo"]))

    quarters = [(y, q) for y in range(2015, 2027) for q in (1, 2, 3, 4)]
    # 2026Q2 까지만
    quarters = [(y, q) for (y, q) in quarters if (y < 2026 or q <= 2)]

    # EDAT PubMed · pdat 재활용 (기존 h6_theme_probe_v2 파일)
    pdat_map: dict[tuple[str, int, int], int] = {}
    v2_csv = DATA_DIR / f"h6_theme_probe_v2_{sha}.csv"
    if v2_csv.exists():
        with v2_csv.open() as f:
            for row in csv.DictReader(f):
                try:
                    pdat_map[(row["theme"], int(row["year"]), int(row["quarter"]))] = int(row["pubmed_count"])
                except Exception:
                    continue

    edat_rows = []
    ctgov_membership = defaultdict(list)  # (theme, y, q) → [sponsor,...]
    tiingo_hits_by_theme_quarter: dict[tuple[str, int, int], set] = defaultdict(set)

    with httpx.Client(headers={"User-Agent": UA}) as client:
        for theme, terms in THEMES.items():
            LOG.info("theme=%s", theme)
            for y, q in quarters:
                pm_min, pm_max = quarter_range(y, q)
                edat = pubmed_count(client, terms, pm_min, pm_max, "edat")
                time.sleep(0.35)
                pdat = pdat_map.get((theme, y, q))
                edat_rows.append({
                    "theme": theme,
                    "year": y,
                    "quarter": q,
                    "pubmed_edat": edat,
                    "pubmed_pdat": pdat if pdat is not None else "",
                    "edat_minus_pdat": (edat - pdat) if pdat is not None else "",
                })

                # CT.gov 스폰서 · main themes 만 (부하 감소)
                if theme in MAIN_THEMES or theme.startswith("control_"):
                    sp_start = pm_min.replace("/", "-")
                    sp_end = pm_max.replace("/", "-")
                    sponsors = ctgov_sponsors(client, terms, sp_start, sp_end, max_pages=3)
                    time.sleep(0.3)
                    ctgov_membership[(theme, y, q)] = sponsors
                    for spon in sponsors:
                        k = normalize_name(spon)
                        if k in universe["name_map"]:
                            t = universe["name_map"][k]["ticker"]
                            if t in universe["tiingo"]:
                                tiingo_hits_by_theme_quarter[(theme, y, q)].add(t)

    # 저장 EDAT
    edat_path = DATA_DIR / f"h6_theme_edat_{sha}.csv"
    with edat_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(edat_rows[0].keys()))
        w.writeheader()
        w.writerows(edat_rows)

    # 저장 membership
    memb_path = DATA_DIR / f"h6_membership_{sha}.csv"
    memb_rows = []
    for (theme, y, q), sponsors in ctgov_membership.items():
        tickers = tiingo_hits_by_theme_quarter.get((theme, y, q), set())
        memb_rows.append({
            "theme": theme,
            "year": y,
            "quarter": q,
            "sponsors_raw_count": len(sponsors),
            "tiingo_matched_tickers": "|".join(sorted(tickers)),
            "tiingo_match_count": len(tickers),
        })
    with memb_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["theme", "year", "quarter", "sponsors_raw_count", "tiingo_matched_tickers", "tiingo_match_count"])
        w.writeheader()
        w.writerows(memb_rows)

    # 분기별 순위표 (z-점수 60/40) · 주 6 테마만 (대조군 제외)
    rank_rows = []
    # per quarter t: (theme, z_pm, z_ct)
    theme_edat_by_q: dict[tuple[int, int], dict[str, int]] = defaultdict(dict)
    theme_ct_by_q: dict[tuple[int, int], dict[str, int]] = defaultdict(dict)
    for row in edat_rows:
        if row["theme"] not in MAIN_THEMES:
            continue
        theme_edat_by_q[(row["year"], row["quarter"])][row["theme"]] = row["pubmed_edat"]
    for (theme, y, q), sponsors in ctgov_membership.items():
        if theme in MAIN_THEMES:
            theme_ct_by_q[(y, q)][theme] = len(sponsors)

    obesity_top_tercile_first_quarter = None
    quarters_sorted = sorted(theme_edat_by_q.keys())
    for y, q in quarters_sorted:
        themes_present = list(theme_edat_by_q[(y, q)].keys())
        if len(themes_present) < 3:
            continue
        pm_vals = [theme_edat_by_q[(y, q)][t] for t in themes_present]
        ct_vals = [theme_ct_by_q.get((y, q), {}).get(t, 0) for t in themes_present]
        z_pm = zscore([float(v) for v in pm_vals])
        z_ct = zscore([float(v) for v in ct_vals])
        combined = [(themes_present[i], 0.6 * z_pm[i] + 0.4 * z_ct[i]) for i in range(len(themes_present))]
        combined.sort(key=lambda x: -x[1])
        # 3분위 정렬 (n=6 → top 2·mid 2·bot 2)
        n = len(combined)
        top_n = max(1, n // 3)
        top_set = set(t for t, _ in combined[:top_n])
        for rank_idx, (theme, score) in enumerate(combined, 1):
            tercile = "top" if theme in top_set else ("bot" if rank_idx > n - top_n else "mid")
            rank_rows.append({
                "year": y, "quarter": q, "theme": theme,
                "z_pm_edat": round(z_pm[themes_present.index(theme)], 3),
                "z_ct_new": round(z_ct[themes_present.index(theme)], 3),
                "score_60pm_40ct": round(score, 3),
                "rank": rank_idx,
                "tercile": tercile,
            })
        if "obesity_glp1" in top_set and obesity_top_tercile_first_quarter is None:
            obesity_top_tercile_first_quarter = f"{y}Q{q}"

    rank_path = DATA_DIR / f"h6_rank_{sha}.csv"
    with rank_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["year", "quarter", "theme", "z_pm_edat", "z_ct_new", "score_60pm_40ct", "rank", "tercile"])
        w.writeheader()
        w.writerows(rank_rows)

    # 요약 · EDAT vs pdat 차이 분포
    diffs = [r["edat_minus_pdat"] for r in edat_rows if r["edat_minus_pdat"] != ""]
    diffs_num = [d for d in diffs if isinstance(d, (int, float))]
    total_sponsors = sum(len(v) for v in ctgov_membership.values())
    total_matched_tickers = sum(len(v) for v in tiingo_hits_by_theme_quarter.values())

    summary = {
        "git_sha": sha,
        "edat_csv": str(edat_path),
        "membership_csv": str(memb_path),
        "rank_csv": str(rank_path),
        "quarters_covered": len(quarters),
        "edat_vs_pdat_diff_mean": round(sum(diffs_num) / max(1, len(diffs_num)), 1) if diffs_num else None,
        "edat_vs_pdat_diff_max_abs": max((abs(d) for d in diffs_num), default=0),
        "ctgov_sponsors_total_raw": total_sponsors,
        "tiingo_matched_ticker_slots": total_matched_tickers,
        "obesity_glp1_top_tercile_first_quarter": obesity_top_tercile_first_quarter,
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
