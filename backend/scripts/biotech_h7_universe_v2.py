"""WP11 · H7 universe skeleton v2 (Tiingo supported_tickers 기반).

용도:
- Tiingo `supported_tickers.zip` (~40MB · 무료 · 무인증) 다운로드
- US 보통주 필터 (assetType=Stock · exchange in {NYSE, NASDAQ, AMEX})
- 상장·폐지일 (startDate · endDate) 기록
- 분기별 활성 종목 수 (2016Q1 · 2020Q1 · 2024Q1)
- SIC 컬럼은 예약 (SEC 재개 후 배선)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import io
import json
import logging
import subprocess
import zipfile
from datetime import date
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

LOG = logging.getLogger("biotech_h7_universe_v2")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
CACHE = DATA_DIR / "tiingo_supported_tickers.csv"

TIINGO_URL = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"
UA = "TossTradebot-BiotechRadar/1.0 (sung2011103@naver.com)"

US_EXCHANGES = {"NYSE", "NASDAQ", "AMEX", "NYSE ARCA", "BATS"}


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


def download_supported_tickers() -> Path:
    if CACHE.exists():
        LOG.info("using cache: %s (%.1f MB)", CACHE, CACHE.stat().st_size / 1e6)
        return CACHE
    LOG.info("downloading Tiingo supported_tickers.zip (~40MB)...")
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True) as client:
        r = client.get(TIINGO_URL, timeout=180.0)
        r.raise_for_status()
    LOG.info("downloaded %.1f MB", len(r.content) / 1e6)
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    inner_names = zf.namelist()
    LOG.info("zip contents: %s", inner_names)
    if not inner_names:
        raise RuntimeError("empty zip")
    csv_bytes = zf.read(inner_names[0])
    CACHE.write_bytes(csv_bytes)
    LOG.info("cached: %s (%.1f MB)", CACHE, CACHE.stat().st_size / 1e6)
    return CACHE


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    LOG.info("git_sha=%s", sha)

    src = download_supported_tickers()

    total = 0
    filtered = 0
    rows_out = []
    with src.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            exchange = (row.get("exchange") or "").strip().upper()
            asset_type = (row.get("assetType") or "").strip()
            if exchange not in US_EXCHANGES:
                continue
            if asset_type != "Stock":
                continue
            filtered += 1
            rows_out.append(
                {
                    "ticker": row.get("ticker", ""),
                    "exchange": exchange,
                    "asset_type": asset_type,
                    "first_bar_date": row.get("startDate", ""),
                    "last_bar_date": row.get("endDate", ""),
                    "price_currency": row.get("priceCurrency", ""),
                    "sic": "",
                }
            )

    out_path = DATA_DIR / f"universe_skeleton_v2_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "ticker",
                "exchange",
                "asset_type",
                "first_bar_date",
                "last_bar_date",
                "price_currency",
                "sic",
            ],
        )
        w.writeheader()
        w.writerows(rows_out)

    def active_at(qend: str) -> int:
        n = 0
        for r in rows_out:
            fd = r["first_bar_date"]
            ld = r["last_bar_date"]
            if fd and fd <= qend and (not ld or ld >= qend):
                n += 1
        return n

    picks = {
        "2016Q1": active_at("2016-03-31"),
        "2020Q1": active_at("2020-03-31"),
        "2024Q1": active_at("2024-03-31"),
    }
    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "total_rows": total,
        "us_stock_rows": filtered,
        "quarterly_active_sample": picks,
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
