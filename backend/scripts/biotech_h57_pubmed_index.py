"""Phase C · h57 · PubMed 회사별 게재 인덱스 (E-utilities · 무인증).

용도:
- 340 CIK 회사 각각 · 회사명 [AD] (Affiliation) 필드 · 최근 3년 (36개월) 게재 PMID+EDAT 인덱스 캐시
- 이벤트별 창 필터는 in-memory (API 부담 최소화)

Rate limit: 무인증 3 req/sec · 인증키 있으면 10 req/sec (미사용)
API: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi

캐시: `backend/data/h57_pubmed_index_{sha}.json`
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging, data_sha

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
LOG = logging.getLogger("biotech_h57_pubmed_index")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
UA = "TossTradebot BiotechRadar suauncle@gmail.com"
REQ_INTERVAL = 0.4  # 3/sec 안전 여유

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_targets(sha: str) -> dict[str, str]:
    """CIK → 회사명 (targets_v2 우선 · SEC company_tickers fallback)."""
    m: dict[str, str] = {}
    p = DATA_DIR / f"h3_targets_v2_{sha}.csv"
    if p.exists():
        with p.open() as f:
            for r in csv.DictReader(f):
                cik = (r.get("target_cik") or "").zfill(10)
                name = (r.get("company_name") or r.get("name") or "").strip()
                if cik and name:
                    m[cik] = name
    sp = DATA_DIR / "sec_company_tickers.json"
    if sp.exists():
        for _, e in json.loads(sp.read_text()).items():
            cik = str(e.get("cik_str", "")).zfill(10)
            title = str(e.get("title", "")).strip()
            if cik and title and cik not in m:
                m[cik] = title
    return m


def load_readout_ciks() -> set[str]:
    """WP39 완주 풀에서 CIK 추출 (이벤트 있는 회사 우선)."""
    cp = DATA_DIR / "h39_readouts_checkpoint.json"
    if not cp.exists():
        return set()
    ciks = set()
    for e in json.loads(cp.read_text()).get("events", []):
        c = (e.get("cik") or "").zfill(10)
        if c:
            ciks.add(c)
    return ciks


def normalize_company(name: str) -> str:
    """PubMed [AD] 검색용 · 접미사 제거 · quote 대비."""
    n = name.strip()
    for suf in [", Inc.", ", Inc", " Inc.", " Inc", " LLC", " Corp", " Corporation",
                " Ltd", " Limited", " Co., Ltd.", " plc", " PLC", " AG", " SA", " NV"]:
        if n.endswith(suf):
            n = n[: -len(suf)]
    return n.strip()


def pubmed_search_count_dates(client: httpx.Client, company: str, edat_from: str, edat_to: str, retries: int = 2) -> int:
    """회사 · EDAT 범위 게재 count 만 반환 (retmax=0 · esearch count field · 부담 최소).

    - retmax=0 로 idlist 미반환 → count 만 · 빠름
    - timeout 재시도 (지수 backoff · 최대 retries)
    - 오류 시 -1 반환 (0 = 게재 없음과 구분)
    """
    q = f'"{normalize_company(company)}"[AD] AND {edat_from}:{edat_to}[EDAT]'
    params = {"db": "pubmed", "term": q, "retmode": "json", "retmax": "0"}
    for attempt in range(retries + 1):
        time.sleep(REQ_INTERVAL * (2 ** attempt))
        try:
            r = client.get(ESEARCH, params=params, timeout=30.0)
            if r.status_code != 200:
                return -1
            data = r.json()
            return int(data.get("esearchresult", {}).get("count", 0))
        except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            LOG.warning("timeout %s (attempt %d) · %s", company[:30], attempt + 1, e.__class__.__name__)
        except Exception as e:
            LOG.warning("error %s · %s", company[:30], e.__class__.__name__)
            return -1
    return -1


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    if not (DATA_DIR / f"h3_targets_v2_{sha}.csv").exists():
        fb = data_sha(DATA_DIR)
        if fb:
            LOG.info("git_sha %s 데이터 부재 · data_sha fallback → %s", sha, fb)
            sha = fb

    targets = load_targets(sha)
    readout_ciks = load_readout_ciks()
    LOG.info("targets: %d · readout_ciks: %d", len(targets), len(readout_ciks))

    # 이벤트 있는 회사만 처리 (340 근사)
    target_ciks = sorted(readout_ciks & set(targets.keys()))
    LOG.info("processing %d CIKs (readout ∩ targets)", len(target_ciks))

    cache_path = DATA_DIR / f"h57_pubmed_index_{sha}.json"
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
        LOG.info("resume: %d cached", len(cache))

    # 창 정의: EDAT 최근 3년 (2023/09 ~ 2026/09)
    # 이벤트별 소문 지수 산정 시 D-day 기준 D-180~D-31 · D-360~D-181 재계산
    # 여기서는 창 미리 나눔 (recent · baseline · pre) · 그 이상 데이터 미필요
    windows = {
        "y2026": ("2026/01", "2026/12"),
        "y2025": ("2025/01", "2025/12"),
        "y2024": ("2024/01", "2024/12"),
        "y2023": ("2023/01", "2023/12"),
    }

    max_ciks = int(sys.argv[1]) if len(sys.argv) > 1 else len(target_ciks)
    LOG.info("cap max_ciks=%d (arg 1 or all)", max_ciks)

    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"}) as client:
        for i, cik in enumerate(target_ciks[:max_ciks], 1):
            if cik in cache:
                continue
            company = targets[cik]
            entry = {"company": company, "counts": {}}
            for w_name, (lo, hi) in windows.items():
                cnt = pubmed_search_count_dates(client, company, lo, hi)
                entry["counts"][w_name] = cnt
            cache[cik] = entry
            if i % 20 == 0:
                cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
                LOG.info("progress %d/%d · last=%s (%s) · counts=%s",
                         i, len(target_ciks), cik, company[:30],
                         entry["counts"])

    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

    dist = {}
    for e in cache.values():
        s = sum(e["counts"].values())
        b = 0 if s == 0 else (1 if s < 5 else (2 if s < 20 else 3))
        dist[b] = dist.get(b, 0) + 1

    summary = {
        "git_sha": sha,
        "cache_path": str(cache_path),
        "total_ciks_processed": len(cache),
        "coverage_pct": round(len(cache) / max(len(target_ciks), 1) * 100, 1),
        "count_bucket_distribution": dist,  # 0=no pubs, 1=<5, 2=<20, 3=20+
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
