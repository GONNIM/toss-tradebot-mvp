"""H3 가격 데이터 통합기 (B81 · 덮어쓰기 결함 fix).

기존 결함: `biotech_h3_collect_prices.py` 가 h3_prices CSV 를 `w` 모드로 open ·
매 실행 덮어씀 · 이전 kept 데이터 유실 (B77 발견).

B81 조치:
- 수집기 = 실행별 파일 `h3_prices_{sha}_{date}_run{N}.csv` 저장
- 통합기 (본 스크립트) = 모든 실행별 파일 스캔 · 중복 (ticker, date) 제거 · 최신 우선

산출: `backend/data/h3_prices_merged_{git_sha}.csv`

실행:
    python -m backend.scripts.biotech_h3_merge_prices
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import logging
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

LOG = logging.getLogger("biotech_h3_merge")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


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


def main() -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    git_sha = _git_sha()

    # 실행별 파일 스캔 · 최신 우선 (v2 는 legacy 뒤 · 스키마 adj_close 포함 우선)
    v2_files = sorted(DATA_DIR.glob(f"h3_prices_v2_{git_sha}_*_run*.csv"))
    run_files = sorted(DATA_DIR.glob(f"h3_prices_{git_sha}_*_run*.csv"))
    legacy_files = sorted(DATA_DIR.glob(f"h3_prices_{git_sha}_*.csv"))
    legacy_files = [p for p in legacy_files if "_run" not in p.name and "_merged" not in p.name and "_v2_" not in p.name]

    # 순서: legacy → run(v1) → v2 (v2 가 최신 · 덮어쓰기)
    all_files = legacy_files + run_files + v2_files
    LOG.info("scan: legacy %d · run(v1) %d · v2 %d · total %d",
             len(legacy_files), len(run_files), len(v2_files), len(all_files))

    # (ticker, date) → row (최신 우선 · 순서상 뒤가 최신)
    # B92 · eodhd 소스 제외 (EODHD PASS 철회 · 데이터 신뢰 불가)
    EXCLUDE_SOURCES = {"eodhd"}
    merged: dict[tuple[str, str], dict] = {}
    excluded_count = 0
    for path in all_files:
        LOG.info("load: %s", path.name)
        with open(path) as f:
            for r in csv.DictReader(f):
                if r.get("source") in EXCLUDE_SOURCES:
                    excluded_count += 1
                    continue
                key = (r["ticker"], r["date"])
                merged[key] = r  # 뒤에서 덮어쓰기 = 최신 우선
    LOG.info("excluded eodhd rows: %d", excluded_count)

    out_path = DATA_DIR / f"h3_prices_merged_{git_sha}.csv"
    if not merged:
        LOG.warning("병합 결과 0 rows")
        return 1
    fields = list(next(iter(merged.values())).keys())
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in merged.values():
            w.writerow(row)

    # 통계
    from collections import Counter
    src_count = Counter(r.get("source", "?") for r in merged.values())
    tickers = {r["ticker"] for r in merged.values()}
    print("\n== B81 · h3_prices 통합 ==")
    print(f"git_sha:             {git_sha}")
    print(f"scanned files:       {len(all_files)} (legacy {len(legacy_files)} + run {len(run_files)})")
    print(f"merged rows:         {len(merged)}")
    print(f"unique tickers:      {len(tickers)}")
    print(f"source 분포:          {dict(src_count)}")
    print(f"output:              {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
