"""WP6 · H7 universe skeleton (h3_prices_merged 기반 · SIC 컬럼 예약).

용도:
- h3_prices_merged 286 티커의 first/last bar 산출 → 분기별 활성 종목 수
- SIC 컬럼은 h3_targets_v2 로부터 매핑 (있는 것만)
- Tiingo supported_tickers 확장은 별건 · 본 스크립트는 최소 뼈대만

원칙:
- 무인증 · 로컬 파일 기반
- 결과: universe_skeleton_{sha}.csv + 분기별 카운트 summary
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h7_universe")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"


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


def load_sic_map(sha: str) -> dict[str, str]:
    """h3_targets_v2_{sha}.csv · ticker → sic (2834/2836)."""
    path = DATA_DIR / f"h3_targets_v2_{sha}.csv"
    if not path.exists():
        LOG.warning("h3_targets_v2 not found: %s", path)
        return {}
    out = {}
    with path.open() as f:
        for row in csv.DictReader(f):
            t = (row.get("ticker") or "").strip()
            sic = (row.get("sic_biotech") or row.get("sic") or "").strip()
            if t and sic:
                out[t] = sic
    return out


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    LOG.info("git_sha=%s", sha)

    prices_path = DATA_DIR / f"h3_prices_merged_{sha}.csv"
    if not prices_path.exists():
        LOG.error("h3_prices_merged not found: %s", prices_path)
        return

    sic_map = load_sic_map(sha)
    LOG.info("sic map size: %d", len(sic_map))

    # first/last bar per ticker + source
    first_bar: dict[str, str] = {}
    last_bar: dict[str, str] = {}
    source_by_ticker: dict[str, set] = defaultdict(set)

    with prices_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = (row.get("ticker") or "").strip()
            d = (row.get("date") or "").strip()
            src = (row.get("source") or "").strip()
            if not ticker or not d:
                continue
            if ticker not in first_bar or d < first_bar[ticker]:
                first_bar[ticker] = d
            if ticker not in last_bar or d > last_bar[ticker]:
                last_bar[ticker] = d
            if src:
                source_by_ticker[ticker].add(src)

    LOG.info("distinct tickers with bars: %d", len(first_bar))

    # csv 저장
    out_path = DATA_DIR / f"universe_skeleton_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["ticker", "first_bar_date", "last_bar_date", "source", "sic"],
        )
        w.writeheader()
        for t in sorted(first_bar):
            w.writerow(
                {
                    "ticker": t,
                    "first_bar_date": first_bar[t],
                    "last_bar_date": last_bar[t],
                    "source": "|".join(sorted(source_by_ticker[t])),
                    "sic": sic_map.get(t, ""),
                }
            )

    # 분기별 활성 종목 수 (first ≤ quarter_end ≤ last)
    quarters = [
        (y, q, date(y, 3 * q, [31, 30, 30, 31][q - 1]))
        for y in range(2016, 2027)
        for q in (1, 2, 3, 4)
    ]
    counts = []
    for y, q, qe in quarters:
        qe_str = qe.strftime("%Y-%m-%d")
        active = sum(
            1
            for t in first_bar
            if first_bar[t] <= qe_str and last_bar[t] >= qe_str
        )
        counts.append({"quarter": f"{y}Q{q}", "quarter_end": qe_str, "active_tickers": active})

    # 요약: 특정 분기 카운트
    picks = {"2016Q1": None, "2020Q1": None, "2024Q1": None}
    for c in counts:
        if c["quarter"] in picks:
            picks[c["quarter"]] = c["active_tickers"]

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "total_tickers_with_bars": len(first_bar),
        "sic_mapped": sum(1 for t in first_bar if t in sic_map),
        "quarterly_active_sample": picks,
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    # 분기별 CSV
    q_path = DATA_DIR / f"universe_skeleton_quarterly_{sha}.csv"
    with q_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["quarter", "quarter_end", "active_tickers"])
        w.writeheader()
        w.writerows(counts)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
