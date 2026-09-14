"""H3 filing 실집계 (B36 재발행 · 최우선).

원칙 (B47 · 독립 운영):
- biotech 이름공간 독립 스크립트
- 기존 backend/discovery/activist 코드 수정 금지 · 읽기 참조만
- SEED_ACTIVISTS 매치 재활용 (있으면 "기존 seed" 출처)
- setup_secure_logging 재사용 (backend.services.config import)

절차:
1. 7 기관 (RA Capital · Baker Bros · Perceptive · Deep Track · Farallon · OrbiMed · Redmile) CIK 확정
   - 기존 SEED_ACTIVISTS 대조 (활성 활동가 26 US)
   - 미매치 시 EDGAR EFTS 회사명 검색 · 기관당 복수 CIK 후보 기록
2. 각 CIK submissions API → 2021-09-01~2026-09-01 filing 집계
   - SC 13D · SC 13D/A · SC 13G · SC 13G/A · Form 4 · Form 4/A
   - filer CIK 일치 강제 (B24 규칙)
3. EFTS 로 filing 대상 종목 CIK 추출 (target)
4. 각 target CIK submissions → 상장 상태 (Form 25/25-NSE 유무 + 최근 filing 기간)
5. CSV 산출: `backend/data/h3_filing_census_{git_sha}.csv`

산출 수치: 기관별 filing 건수 · 고유 티커 수 · 폐지 종목 수 · EODHD 분할 일수 = ceil(폐지/20)

실행:
    python -m backend.scripts.biotech_h3_filing_census
    python -m backend.scripts.biotech_h3_filing_census --dry-run  # CIK 확정만
"""
from __future__ import annotations

from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING  # noqa: E402 · WP23

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging  # noqa: F401

import csv
import json
import logging
import math
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

LOG = logging.getLogger("biotech_h3_census")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

EFTS_BASE = "https://efts.sec.gov/LATEST/search-index"
SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
REQ_INTERVAL = 0.5  # SEC 10 req/s 이내

DATE_START = "2021-09-01"
DATE_END = "2026-09-01"
FORM_25 = {"25", "25-NSE"}
FILING_FORMS_TARGET = {"SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A", "4", "4/A"}
DAILY_QUOTA_EODHD = 20


@dataclass
class Institution:
    name: str
    search_queries: list[str]  # 여러 검색어 fallback
    seed_lookup: str  # SEED_ACTIVISTS 매치 후보 (fund 이름)
    ciks: list[dict] = field(default_factory=list)  # [{cik, display, source}]


INSTITUTIONS: list[Institution] = [
    Institution("RA Capital",     ['"RA Capital Management"', '"RA Capital Healthcare"'],       "ra capital"),
    Institution("Baker Bros",     ['"Baker Bros. Advisors"', '"Baker Brothers"'],               "baker bros"),
    Institution("Perceptive",     ['"Perceptive Advisors"', '"Perceptive Life Sciences"'],      "perceptive"),
    Institution("Deep Track",     ['"Deep Track Capital"', '"Deep Track Biotechnology"'],       "deep track"),
    Institution("Farallon",       ['"Farallon Capital"', '"Farallon Capital Management"'],      "farallon"),
    Institution("OrbiMed",        ['"OrbiMed Advisors"', '"OrbiMed Capital"'],                  "orbimed"),
    Institution("Redmile",        ['"Redmile Group"', '"Redmile Capital"'],                     "redmile"),
]


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=False,
            cwd=Path(__file__).resolve().parent.parent.parent,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _get(client: httpx.Client, url: str, params: dict | None = None, retries: int = 3) -> httpx.Response | None:
    delay = REQ_INTERVAL
    for attempt in range(retries):
        time.sleep(delay)
        try:
            r = client.get(url, params=params, timeout=25.0)
            if r.status_code < 500:
                return r
        except Exception as e:
            LOG.warning("HTTP ERR %s: %s (retry %d)", type(e).__name__, e, attempt + 1)
        delay = min(delay * 3, 5.0)
    return None


def load_seed_activists() -> dict[str, str]:
    """기존 SEED_ACTIVISTS 를 읽기 전용으로 파싱 · {name_lower: cik} 반환."""
    try:
        from backend.discovery.activist.universe import SEED_ACTIVISTS
    except Exception as e:
        LOG.warning("SEED_ACTIVISTS import fail: %s", e)
        return {}
    out = {}
    for a in SEED_ACTIVISTS:
        if getattr(a, "cik", None):
            out[a.name.lower()] = a.cik
    return out


def resolve_cik(client: httpx.Client, inst: Institution, seed: dict[str, str]) -> None:
    """기관 CIK 확정.
    1) SEED_ACTIVISTS 매치 확인
    2) 미매치 시 EFTS 회사명 검색 (filter 없이 · 후보 다수 허용)
    """
    # 1) SEED
    for seed_name, seed_cik in seed.items():
        if inst.seed_lookup in seed_name:
            inst.ciks.append({
                "cik": seed_cik,
                "display": seed_name,
                "source": "기존 seed",
            })
    if inst.ciks:
        LOG.info("[%s] 기존 seed 매치: %d개", inst.name, len(inst.ciks))
        return

    # 2) EFTS 회사명 검색 (여러 query fallback · form filter 없음)
    seen: set[str] = set()
    lookup_low = inst.seed_lookup.lower()
    for q in inst.search_queries:
        r = _get(client, EFTS_BASE, {"q": q})
        if r is None or r.status_code != 200:
            continue
        hits = r.json().get("hits", {}).get("hits", [])
        for h in hits[:80]:
            src = h.get("_source", {})
            ciks = src.get("ciks") or []
            names = src.get("display_names") or []
            for i, cik in enumerate(ciks):
                if cik in seen:
                    continue
                # display_names / ciks 대응 · names[i] fallback names[0]
                display = names[i] if i < len(names) else (names[0] if names else "")
                if lookup_low not in display.lower():
                    continue
                seen.add(cik)
                inst.ciks.append({
                    "cik": cik,
                    "display": display,
                    "source": f"EDGAR EFTS ({q})",
                })
    LOG.info("[%s] EFTS 매치: %d개 CIK", inst.name, len(inst.ciks))


def fetch_submissions(client: httpx.Client, cik: str) -> dict | None:
    url = f"{SUBMISSIONS_BASE}/CIK{cik.zfill(10)}.json"
    r = _get(client, url)
    if r is None or r.status_code != 200:
        return None
    try:
        return r.json()
    except Exception:
        return None


def collect_older_files(client: httpx.Client, subs: dict, max_pages: int = 10) -> list[dict]:
    """filings.files paginated · 오래된 filing 커버 (5년 백테스트용)."""
    older = subs.get("filings", {}).get("files", [])
    out: list[dict] = []
    for pg in older[:max_pages]:
        url = f"{SUBMISSIONS_BASE}/{pg.get('name')}"
        r = _get(client, url)
        if r is None or r.status_code != 200:
            continue
        try:
            out.append(r.json())
        except Exception:
            pass
    return out


def count_filings_in_range(recent: dict, extra_pages: list[dict]) -> tuple[dict[str, int], list[str]]:
    """form 별 filing 건수 + 발견된 accession 목록.

    반환: (form_counts, accessions)
    """
    counts: dict[str, int] = {}
    accs: list[str] = []
    all_pages = [recent] + extra_pages
    for page in all_pages:
        forms = page.get("form", [])
        dates = page.get("filingDate", [])
        accessions = page.get("accessionNumber", [])
        for i, f in enumerate(forms):
            if f not in FILING_FORMS_TARGET:
                continue
            try:
                d = datetime.strptime(dates[i], "%Y-%m-%d")
                if not (datetime(2021, 9, 1) <= d <= datetime(2026, 9, 1)):
                    continue
            except (ValueError, IndexError):
                continue
            counts[f] = counts.get(f, 0) + 1
            if i < len(accessions):
                accs.append(accessions[i])
    return counts, accs


def find_target_ciks_via_efts(client: httpx.Client, name_queries: list[str], fund_ciks: set[str], forms: str) -> set[str]:
    """EFTS 회사명 검색 · 알려진 fund CIK 제외 · subject CIK 추출.

    EFTS 관례: hits[i]._source.ciks 배열에서 fund_ciks 아닌 항목 = target(subject).
    페이지네이션 · 여러 검색어 fallback.
    """
    targets: set[str] = set()
    fund_no_pad = {c.lstrip("0") for c in fund_ciks}
    for q in name_queries:
        for from_offset in range(0, 1000, 100):
            r = _get(client, EFTS_BASE, {
                "q": q,
                "forms": forms,
                "dateRange": "custom",
                "startdt": DATE_START,
                "enddt": DATE_END,
                "from": from_offset,
            })
            if r is None or r.status_code != 200:
                break
            try:
                data = r.json()
            except Exception:
                break
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break
            for h in hits:
                src = h.get("_source", {})
                ciks_in_hit = src.get("ciks") or []
                # 관례: hit 안의 ciks 중 우리 fund CIK 세트에 없는 것 = target
                for c in ciks_in_hit:
                    if c.lstrip("0") not in fund_no_pad:
                        targets.add(c)
            if len(hits) < 100:
                break
    return targets


def check_listing_status(client: httpx.Client, target_cik: str) -> dict:
    """target CIK 의 상장 상태 · Form 25/25-NSE 유무 + 최근 filing 날짜."""
    subs = fetch_submissions(client, target_cik)
    if subs is None:
        return {"status": "SUBMISSIONS_UNAVAILABLE", "form25": False, "last_filing": ""}
    recent = subs.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    has_form25 = any(f in FORM_25 for f in forms)
    last_date = dates[0] if dates else ""
    if has_form25:
        return {"status": "DELISTED", "form25": True, "last_filing": last_date, "name": subs.get("name", "")}
    if last_date:
        try:
            d = datetime.strptime(last_date, "%Y-%m-%d")
            if (datetime.now() - d).days > 365 * 2:
                return {"status": "INACTIVE_FILER", "form25": False, "last_filing": last_date, "name": subs.get("name", "")}
        except ValueError:
            pass
    return {"status": "ACTIVE", "form25": False, "last_filing": last_date, "name": subs.get("name", "")}


def main() -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # B44 · 기존 보안 경로 (setup_secure_logging 자동)
    from backend.services import config as _config  # noqa: F401

    dry_run = "--dry-run" in sys.argv
    git_sha = _git_sha()

    seed = load_seed_activists()
    LOG.info("SEED_ACTIVISTS 로드: %d 항목", len(seed))

    with httpx.Client(
        headers={"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}
    ) as client:
        # ─ 1) CIK 확정 ─
        for inst in INSTITUTIONS:
            resolve_cik(client, inst, seed)

        if dry_run:
            print("\n== B36 · DRY-RUN (CIK 확정만) ==")
            for inst in INSTITUTIONS:
                print(f"\n[{inst.name}]")
                if not inst.ciks:
                    print("  CIK 미확보")
                    continue
                for c in inst.ciks:
                    print(f"  CIK={c['cik']} · {c['source']} · {c['display']}")
            return 0

        # ─ 2·3·4) filing 집계 + target 추출 + 상태 확인 ─
        rows: list[dict] = []
        total_targets: set[str] = set()
        total_delisted: set[str] = set()

        for inst in INSTITUTIONS:
            LOG.info("=== [%s] 집계 시작 (CIK %d개) ===", inst.name, len(inst.ciks))
            inst_filing_counts: dict[str, int] = {}

            for c in inst.ciks:
                cik = c["cik"]
                LOG.info("  CIK %s submissions 조회", cik)
                subs = fetch_submissions(client, cik)
                if subs is None:
                    LOG.warning("  CIK %s submissions 미확보", cik)
                    continue

                extra_pages = collect_older_files(client, subs)
                counts, _accs = count_filings_in_range(subs.get("filings", {}).get("recent", {}), extra_pages)
                for form, n in counts.items():
                    inst_filing_counts[form] = inst_filing_counts.get(form, 0) + n

            # target extraction · 기관 name 기준 EFTS 검색 · fund CIK 배제
            fund_ciks = set(c["cik"] for c in inst.ciks)
            targets_sc = find_target_ciks_via_efts(client, inst.search_queries, fund_ciks, "SC 13D,SC 13D/A,SC 13G,SC 13G/A")
            targets_f4 = find_target_ciks_via_efts(client, inst.search_queries, fund_ciks, "4,4/A")
            inst_targets = targets_sc | targets_f4
            LOG.info("  [%s] targets · SC=%d · F4=%d · union=%d",
                     inst.name, len(targets_sc), len(targets_f4), len(inst_targets))

            # 상장 상태 확인
            inst_delisted: set[str] = set()
            for t in inst_targets:
                status = check_listing_status(client, t)
                if status["status"] == "DELISTED":
                    inst_delisted.add(t)

            total_targets |= inst_targets
            total_delisted |= inst_delisted

            rows.append({
                "institution": inst.name,
                "cik_count": len(inst.ciks),
                "cik_list": ";".join(c["cik"] for c in inst.ciks),
                "cik_source": ";".join(set(c["source"] for c in inst.ciks)),
                "sc13d": inst_filing_counts.get("SC 13D", 0),
                "sc13d_a": inst_filing_counts.get("SC 13D/A", 0),
                "sc13g": inst_filing_counts.get("SC 13G", 0),
                "sc13g_a": inst_filing_counts.get("SC 13G/A", 0),
                "form4": inst_filing_counts.get("4", 0),
                "form4_a": inst_filing_counts.get("4/A", 0),
                "total_filings": sum(inst_filing_counts.values()),
                "unique_targets": len(inst_targets),
                "delisted_targets": len(inst_delisted),
            })

        out_path = DATA_DIR / f"h3_filing_census_{git_sha}.csv"
        with open(out_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

        agg_total_filings = sum(r["total_filings"] for r in rows)
        agg_unique_targets = len(total_targets)
        agg_delisted = len(total_delisted)
        eodhd_days = math.ceil(agg_delisted / DAILY_QUOTA_EODHD) if agg_delisted else 0

        print("\n== B36 H3 filing census ==")
        print(f"git_sha:                    {git_sha}")
        print(f"date_range:                 {DATE_START}..{DATE_END}")
        print(f"institutions:               {len(INSTITUTIONS)}")
        print(f"total_filings:              {agg_total_filings}")
        print(f"total_unique_targets:       {agg_unique_targets}")
        print(f"total_delisted_targets:     {agg_delisted}")
        print(f"eodhd_split_days_needed:    ceil({agg_delisted}/{DAILY_QUOTA_EODHD}) = {eodhd_days}")
        print(f"csv:                        {out_path}")
        print()
        for r in rows:
            print(f"  {r['institution']:15s} CIK={r['cik_count']} · filings={r['total_filings']:4d} "
                  f"(SC13D={r['sc13d']:3d} SC13D/A={r['sc13d_a']:3d} SC13G={r['sc13g']:3d} "
                  f"SC13G/A={r['sc13g_a']:3d} F4={r['form4']:4d} F4/A={r['form4_a']:3d}) "
                  f"targets={r['unique_targets']:4d} delisted={r['delisted_targets']:3d}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
