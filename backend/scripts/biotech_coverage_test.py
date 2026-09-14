"""Biotech 상장폐지/인수 종목 가격 소스 커버율 실측 (Phase A · B15-2).

2021~2026 M&A · 상장폐지 바이오 20종목 표본에 대해
yfinance 및 기존 파이프 소스 (Stooq) 의 과거 가격 커버율을 측정한다.

출력: `backend/data/biotech_coverage_test_<git_sha>_<UTCdate>.csv` + 콘솔 요약
컬럼: ticker, event_type, event_date, event_desc, window_start, window_end,
      yfinance_available, yfinance_row_count, yfinance_first_dt, yfinance_last_dt,
      stooq_available, stooq_row_count, stooq_first_dt, stooq_last_dt

방법:
- 각 티커에 대해 event_date 12개월 전 ~ event_date 시점의 가격 이력을 조회
- 히스토리 존재 여부와 실제 반환 row 수를 기록
- yfinance rate limit 관용적 · Stooq 는 봇 차단 우려 있으므로 조용히 실패 허용

표본 선정 근거:
- 2021~2026 사이 미국 상장 바이오/제약 M&A 및 자진 상장폐지·파산 사례
- Fable 리뷰 v2 요구: 표본 20종목 수동 대조
- 근거: 공개 M&A 발표 (SEC 8-K · 회사 보도자료)

실행:
    ./backend/venv/bin/python backend/scripts/biotech_coverage_test.py
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG = logging.getLogger("biotech_coverage")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Sample:
    ticker: str
    event_type: str   # ACQUIRED / DELISTED / BANKRUPT
    event_date: str   # YYYY-MM-DD (close date or delisting date · 공개 발표 기준)
    event_desc: str   # 짧은 근거


# 20 표본 (2021~2026)
SAMPLES: list[Sample] = [
    Sample("HZNP", "ACQUIRED", "2023-10-06", "Horizon Therapeutics → Amgen"),
    Sample("SGEN", "ACQUIRED", "2023-12-14", "Seagen → Pfizer"),
    Sample("GBT",  "ACQUIRED", "2022-10-05", "Global Blood Therapeutics → Pfizer"),
    Sample("ARNA", "ACQUIRED", "2022-03-11", "Arena Pharmaceuticals → Pfizer"),
    Sample("ALXN", "ACQUIRED", "2021-07-21", "Alexion Pharmaceuticals → AstraZeneca"),
    Sample("TRIL", "ACQUIRED", "2021-11-17", "Trillium Therapeutics → Pfizer"),
    Sample("AKUS", "ACQUIRED", "2022-12-22", "Akouos → Eli Lilly"),
    Sample("MYOV", "ACQUIRED", "2023-03-13", "Myovant Sciences → Sumitomo"),
    Sample("DCPH", "ACQUIRED", "2024-06-06", "Deciphera Pharmaceuticals → Ono"),
    Sample("PRVL", "ACQUIRED", "2021-01-22", "Prevail Therapeutics → Eli Lilly"),
    Sample("XLRN", "ACQUIRED", "2021-11-08", "Acceleron Pharma → Merck"),
    Sample("AVEO", "ACQUIRED", "2023-08-04", "AVEO Pharmaceuticals → LG Chem"),
    Sample("KDMN", "ACQUIRED", "2022-09-21", "Kadmon Holdings → Sanofi"),
    Sample("CNCE", "ACQUIRED", "2023-03-06", "Concert Pharmaceuticals → Sun Pharma"),
    Sample("TALS", "ACQUIRED", "2023-11-06", "Talaris → Tourmaline merger"),
    Sample("SYRS", "BANKRUPT", "2024-11-11", "Syros Pharmaceuticals bankruptcy · reverse merger"),
    Sample("VBIV", "DELISTED", "2024-06-11", "VBI Vaccines Nasdaq 상장폐지 (준수 실패)"),
    Sample("HGEN", "BANKRUPT", "2023-02-27", "Humanigen Chapter 11"),
    Sample("KZR",  "DELISTED", "2024-04-01", "Kezar Life Sciences 상장 유지 (참고: 논란 사례 · 표본 확인용)"),
    Sample("PRQR", "ACQUIRED", "2022-11-08", "ProQR Therapeutics N.V. → Laboratoires Théa (참고: 부분 자산 매각)"),
]


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            cwd=Path(__file__).resolve().parent.parent.parent,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def test_yfinance(ticker: str, start: str, end: str) -> dict:
    """yfinance 로 history 조회 · 커버율 측정."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        # auto_adjust default = True 하지만 커버율 측정용이라 데이터 존재 여부만 중요
        df = t.history(start=start, end=end, auto_adjust=False)
        if df is None or df.empty:
            return {
                "available": False,
                "row_count": 0,
                "first_dt": "",
                "last_dt": "",
            }
        return {
            "available": True,
            "row_count": int(len(df)),
            "first_dt": str(df.index[0].date()),
            "last_dt": str(df.index[-1].date()),
        }
    except Exception as e:
        LOG.debug("yfinance fail %s: %s", ticker, e)
        return {
            "available": False,
            "row_count": 0,
            "first_dt": "",
            "last_dt": f"ERROR: {type(e).__name__}",
        }


def test_stooq(ticker: str, start: str, end: str) -> dict:
    """Stooq · 봇 차단 우려 있음. HTTP GET 로 CSV 조회 시도."""
    try:
        import httpx
        # Stooq US ticker suffix: .us
        sym = ticker.lower() + ".us"
        url = f"https://stooq.com/q/d/l/?s={sym}&d1={start.replace('-', '')}&d2={end.replace('-', '')}&i=d"
        r = httpx.get(url, timeout=15.0, headers={"User-Agent": "TossTradebot-BiotechRadar/1.0 (sung2011103@naver.com)"})
        if r.status_code != 200:
            return {"available": False, "row_count": 0, "first_dt": "", "last_dt": f"HTTP {r.status_code}"}
        text = r.text
        # Stooq 봇 차단: HTML/JS challenge 반환 검출 (2026-06-20~ 확인)
        low = text.lstrip().lower()
        if low.startswith("<!doctype") or low.startswith("<html") or "<script" in low[:500]:
            return {"available": False, "row_count": 0, "first_dt": "", "last_dt": "BOT_CHALLENGE"}
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines or lines[0].lower().startswith("no data") or len(lines) < 2:
            return {"available": False, "row_count": 0, "first_dt": "", "last_dt": ""}
        header = lines[0].lower()
        if "date" not in header or "close" not in header:
            return {"available": False, "row_count": 0, "first_dt": "", "last_dt": "BAD_FORMAT"}
        rows = lines[1:]
        first_dt = rows[0].split(",")[0] if "," in rows[0] else ""
        last_dt = rows[-1].split(",")[0] if "," in rows[-1] else ""
        return {
            "available": True,
            "row_count": len(rows),
            "first_dt": first_dt,
            "last_dt": last_dt,
        }
    except Exception as e:
        LOG.debug("stooq fail %s: %s", ticker, e)
        return {
            "available": False,
            "row_count": 0,
            "first_dt": "",
            "last_dt": f"ERROR: {type(e).__name__}",
        }


def main() -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    git_sha = _git_sha()
    snapshot_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    results: list[dict] = []
    yf_ok = 0
    stq_ok = 0

    for i, s in enumerate(SAMPLES, 1):
        # event_date 기준 12개월 전 ~ event_date 창
        try:
            ev = datetime.strptime(s.event_date, "%Y-%m-%d")
        except ValueError:
            LOG.warning("bad event_date %s", s.event_date)
            continue
        start = (ev - timedelta(days=365)).strftime("%Y-%m-%d")
        end = s.event_date

        LOG.info("[%d/%d] %s (%s) %s..%s", i, len(SAMPLES), s.ticker, s.event_type, start, end)
        yfr = test_yfinance(s.ticker, start, end)
        stqr = test_stooq(s.ticker, start, end)

        if yfr["available"]:
            yf_ok += 1
        if stqr["available"]:
            stq_ok += 1

        results.append({
            "ticker": s.ticker,
            "event_type": s.event_type,
            "event_date": s.event_date,
            "event_desc": s.event_desc,
            "window_start": start,
            "window_end": end,
            "yfinance_available": yfr["available"],
            "yfinance_row_count": yfr["row_count"],
            "yfinance_first_dt": yfr["first_dt"],
            "yfinance_last_dt": yfr["last_dt"],
            "stooq_available": stqr["available"],
            "stooq_row_count": stqr["row_count"],
            "stooq_first_dt": stqr["first_dt"],
            "stooq_last_dt": stqr["last_dt"],
        })

    # CSV 저장
    out_path = DATA_DIR / f"biotech_coverage_test_{git_sha}_{snapshot_date}.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    n = len(SAMPLES)
    yf_pct = yf_ok / n * 100.0 if n else 0.0
    stq_pct = stq_ok / n * 100.0 if n else 0.0

    print("\n== Biotech Coverage Test (2021~2026 delisted/acquired 20 samples) ==")
    print(f"git_sha:            {git_sha}")
    print(f"snapshot_date:      {snapshot_date}")
    print(f"sample_size:        {n}")
    print(f"yfinance_coverage:  {yf_ok}/{n} = {yf_pct:.1f}%")
    print(f"stooq_coverage:     {stq_ok}/{n} = {stq_pct:.1f}%")
    print(f"csv:                {out_path}")
    print("\n티커별 세부:")
    for r in results:
        yf_flag = "YF✓" if r["yfinance_available"] else "YF✗"
        st_flag = "SQ✓" if r["stooq_available"] else "SQ✗"
        print(f"  {r['ticker']:6s} {r['event_type']:9s} {r['event_date']} "
              f"{yf_flag}({r['yfinance_row_count']:>4d}) {st_flag}({r['stooq_row_count']:>4d})  "
              f"{r['event_desc']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
