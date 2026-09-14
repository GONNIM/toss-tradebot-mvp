"""WP17-3 · H5 국내 가격 + 벤치 (FDR).

용도:
- h5_kr_mapping_v2 15사 stock_code 별 일별 종가 (2019~2026)
- 벤치: KS200 (KOSPI200) · KQ150 (KOSDAQ150) 지수 · 인덱스 시장 flag
- 산출: h5_prices_{sha}.csv (long format · ticker/date/close/source/type=stock|index)

원칙:
- FDR (`FinanceDataReader`) 무인증 · adj 여부 명시 (FDR .DataReader 는 수정주가)
- 벤치는 index (KS200/KQ150) 승계
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import subprocess
from pathlib import Path

import FinanceDataReader as fdr

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h5_prices")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

BENCH_TICKERS = {"KS200": "KOSPI200", "KOSDAQ": "KOSDAQ_전체"}
# KOSDAQ150 지수 심볼 (KQ150/KRX150) 은 Yahoo 프록시 404 · KOSDAQ 전체 지수로 대체
# 사후 백테스트 리포트에 벤치 대체 사실 명시 필수


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


def load_mapping(sha: str) -> list[dict]:
    p = DATA_DIR / f"h5_kr_mapping_v2_{sha}.csv"
    with p.open() as f:
        return list(csv.DictReader(f))


def market_of(stock_code: str) -> str:
    """대략 판정: 6자리 코드 앞자리로 KOSPI/KOSDAQ 분류 어렵고 · KRX listing 참조 없이는 정확 어려움.
    보수적: FDR StockListing 조회 대신 우선순위 = 대부분 stock_code 5~6 자리."""
    return "unknown"  # 벤치 병기 · 시장 분류는 mapping 후속


def fetch_stock(code: str, start: str = "2019-01-01") -> list[dict]:
    df = fdr.DataReader(code, start)
    if df is None or df.empty:
        return []
    rows = []
    for idx, row in df.iterrows():
        rows.append({
            "ticker": code,
            "date": idx.strftime("%Y-%m-%d"),
            "close": float(row.get("Close", 0) or 0),
            "source": "fdr",
            "type": "stock",
        })
    return rows


def fetch_index(ticker: str, start: str = "2019-01-01") -> list[dict]:
    df = fdr.DataReader(ticker, start)
    if df is None or df.empty:
        return []
    rows = []
    for idx, row in df.iterrows():
        rows.append({
            "ticker": ticker,
            "date": idx.strftime("%Y-%m-%d"),
            "close": float(row.get("Close", 0) or 0),
            "source": "fdr",
            "type": "index",
        })
    return rows


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    LOG.info("git_sha=%s", sha)

    mapping = load_mapping(sha)
    LOG.info("mapping rows: %d", len(mapping))

    all_rows = []
    ok_stocks = 0
    fail_stocks = 0
    for m in mapping:
        code = m["stock_code"]
        name = m["candidate_name"]
        try:
            rows = fetch_stock(code)
            if rows:
                all_rows.extend(rows)
                ok_stocks += 1
                LOG.info("  %s (%s) · %d bars", name, code, len(rows))
            else:
                fail_stocks += 1
                LOG.warning("  %s (%s) · no data", name, code)
        except Exception as e:
            fail_stocks += 1
            LOG.error("  %s (%s) · fail: %s", name, code, e)

    for tk, tn in BENCH_TICKERS.items():
        try:
            rows = fetch_index(tk)
            LOG.info(" bench %s (%s) · %d bars", tn, tk, len(rows))
            all_rows.extend(rows)
        except Exception as e:
            LOG.error(" bench %s failed: %s", tn, e)

    out_path = DATA_DIR / f"h5_prices_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "date", "close", "source", "type"])
        w.writeheader()
        w.writerows(all_rows)

    per_ticker = {}
    for r in all_rows:
        per_ticker.setdefault(r["ticker"], 0)
        per_ticker[r["ticker"]] += 1

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "mapping_companies": len(mapping),
        "stock_ok": ok_stocks,
        "stock_fail": fail_stocks,
        "benches_ok": [k for k in BENCH_TICKERS if k in per_ticker],
        "total_rows": len(all_rows),
        "unique_tickers": len(per_ticker),
        "adj_note": "FDR DataReader = 수정주가 (adjClose) · 종가만 사용",
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
