"""Phase C · h58 · 프리프린트 (bioRxiv/medRxiv) 회사별 게재 인덱스.

bioRxiv 별도 API 대신 PubMed [SB=preprint] 필터 활용:
- 회사명 [AD] AND preprint[SB] AND YYYY:YYYY[EDAT]
- 무인증 3 req/sec · h57 과 동일 파이프

이유: bioRxiv API 는 회사 검색 미지원 (date-range 전량 다운로드 필요)
반면 PubMed 는 bioRxiv 프리프린트도 색인 · [SB=preprint] 로 필터

캐시: `backend/data/h58_preprint_index_{sha}.json`
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging, data_sha
from backend.scripts.biotech_h57_pubmed_index import (
    git_sha, load_targets, load_readout_ciks, normalize_company, UA, REQ_INTERVAL, ESEARCH,
)

import json
import logging
import sys
import time
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h58_preprint_index")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"


def preprint_count(client: httpx.Client, company: str, edat_from: str, edat_to: str) -> int:
    q = f'"{normalize_company(company)}"[AD] AND preprint[SB] AND {edat_from}:{edat_to}[EDAT]'
    params = {"db": "pubmed", "term": q, "retmode": "json", "retmax": "0"}
    time.sleep(REQ_INTERVAL)
    r = client.get(ESEARCH, params=params, timeout=15.0)
    if r.status_code != 200:
        return -1
    try:
        return int(r.json().get("esearchresult", {}).get("count", 0))
    except Exception:
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
    target_ciks = sorted(readout_ciks & set(targets.keys()))
    LOG.info("processing %d CIKs", len(target_ciks))

    cache_path = DATA_DIR / f"h58_preprint_index_{sha}.json"
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())

    windows = {"y2026": ("2026/01", "2026/12"), "y2025": ("2025/01", "2025/12"),
               "y2024": ("2024/01", "2024/12"), "y2023": ("2023/01", "2023/12")}

    max_ciks = int(sys.argv[1]) if len(sys.argv) > 1 else len(target_ciks)

    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"}) as client:
        for i, cik in enumerate(target_ciks[:max_ciks], 1):
            if cik in cache:
                continue
            company = targets[cik]
            entry = {"company": company, "counts": {}}
            for w_name, (lo, hi) in windows.items():
                cnt = preprint_count(client, company, lo, hi)
                entry["counts"][w_name] = cnt
            cache[cik] = entry
            if i % 20 == 0:
                cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
                LOG.info("progress %d/%d · last=%s (%s) · counts=%s",
                         i, len(target_ciks), cik, company[:30], entry["counts"])

    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

    dist = {}
    for e in cache.values():
        s = sum(v for v in e["counts"].values() if v > 0)
        b = 0 if s == 0 else (1 if s < 3 else 2)
        dist[b] = dist.get(b, 0) + 1

    summary = {
        "git_sha": sha, "cache_path": str(cache_path),
        "total_ciks_processed": len(cache),
        "coverage_pct": round(len(cache) / max(len(target_ciks), 1) * 100, 1),
        "preprint_bucket_distribution": dist,  # 0=none, 1=<3, 2=3+
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
