"""Biotech Universe Snapshot (Phase A · B15-1).

US 바이오 · 시총 $50M~$5B · 상장폐지·인수 종목 포함.

산출: `backend/data/biotech_universe_snapshot_<git_sha>_<UTCdate>.csv`
컬럼: ticker, cik, sic, subsector, company_name, market_cap_usd, listing_status, snapshot_date

방법:
1. SEC EDGAR SIC 검색 (SIC 2834 · 2836 · 8731) 로 CIK+회사명 수집
2. company_tickers.json 로 티커 매핑 (액티브 티커만 매핑 성공)
3. yfinance 로 시가총액 조회 (액티브만 · 상장폐지는 market_cap=None, listing_status=DELISTED_OR_ACQUIRED)
4. 시총 $50M~$5B 필터 (액티브만) · 상폐/인수는 별도 유지 (커버리지 실측 표본으로 활용)

제약 (문서화):
- 진정한 survivorship-free universe 는 CRSP/Compustat 유료 데이터 필요
- 본 스크립트는 SEC EDGAR 등록 이력만으로 delisted 를 잡음 (100% 커버리지 아님)
- Phase A 착수 단계에선 이 스크립트로 액티브 subset + delisted 후보군 확보 후, 커버율 실측(B15-2)에서 판정

Fable 지적 대응 (v2.1 §4):
- 상장폐지/인수 종목의 SEC EDGAR 필링 이력은 남아있음 (10-K 마지막 filing 이후 상장 상태 확인)
- yfinance 커버율은 별도 스크립트로 측정 (biotech_coverage_test.py)

실행:
    ./backend/venv/bin/python backend/scripts/biotech_universe_snapshot.py
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging  # noqa: F401

import csv
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


LOG = logging.getLogger("biotech_universe")

SIC_BIOTECH = {
    "2834": "Pharmaceutical Preparations",
    "2836": "Biological Products",
    "8731": "Commercial Physical & Biological Research",
}

SEC_UA = "TossTradebot-BiotechRadar/1.0 (sung2011103@naver.com)"
SEC_BASE = "https://www.sec.gov"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

MCAP_MIN = 50_000_000
MCAP_MAX = 5_000_000_000

REQ_INTERVAL_SEC = 0.5  # B59 보수적 상향 (2 req/s · SEC 규정 준수)
SEC_FROM = "sung2011103@naver.com"


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


def fetch_company_tickers(client: httpx.Client) -> dict[str, dict]:
    """SEC EDGAR company_tickers.json → {cik_str: {ticker, title, cik}}."""
    cache = DATA_DIR / "sec_company_tickers.json"
    if cache.exists():
        LOG.info("company_tickers cache hit: %s", cache)
        return json.loads(cache.read_text())
    LOG.info("fetching %s", SEC_COMPANY_TICKERS_URL)
    r = client.get(SEC_COMPANY_TICKERS_URL, timeout=30.0)
    r.raise_for_status()
    raw = r.json()
    cache.write_text(json.dumps(raw))
    LOG.info("cached %d entries → %s", len(raw), cache)
    return raw


def cik_to_ticker_map(raw: dict) -> dict[str, tuple[str, str]]:
    """{cik_padded10: (ticker, title)}."""
    out: dict[str, tuple[str, str]] = {}
    for _, entry in raw.items():
        cik10 = str(entry["cik_str"]).zfill(10)
        out[cik10] = (entry["ticker"], entry["title"])
    return out


def fetch_sic_ciks(client: httpx.Client, sic: str) -> list[tuple[str, str]]:
    """SEC EDGAR SIC 검색 → [(cik_padded10, company_name)] · 페이지네이션 포함.

    URL: /cgi-bin/browse-edgar?action=getcompany&SIC={sic}&type=10-K&dateb=&owner=include&count=100&start={n}
    """
    ciks: list[tuple[str, str]] = []
    start = 0
    count = 100
    while True:
        url = (
            f"{SEC_BASE}/cgi-bin/browse-edgar?action=getcompany&SIC={sic}"
            f"&type=10-K&dateb=&owner=include&count={count}&start={start}"
        )
        LOG.info("SIC %s · start %d", sic, start)
        time.sleep(REQ_INTERVAL_SEC)
        r = client.get(url, timeout=30.0)
        if r.status_code != 200:
            LOG.warning("SEC HTTP %d · SIC %s start %d", r.status_code, sic, start)
            break
        html = r.text
        # 간단 파싱: <a href="/cgi-bin/browse-edgar?action=getcompany&CIK=0000XXX&...">회사명</a>
        import re
        rows = re.findall(
            r'CIK=(\d{10})[^"]*"[^>]*>[^<]*</a></td>\s*<td[^>]*>([^<]+)</td>',
            html,
        )
        if not rows:
            # 대체 패턴 (테이블 구조 차이)
            rows = re.findall(r'CIK=(\d{10})[^"]*"[^>]*>([^<]+)</a>', html)
        if not rows:
            LOG.info("no more rows · SIC %s · total %d", sic, len(ciks))
            break
        for cik, name in rows:
            ciks.append((cik, name.strip()))
        # 페이지 종료 판정: "Next 100" 링크 부재
        if 'Next 100' not in html and 'action=getcompany' not in html[html.rfind('</table>'):]:
            break
        start += count
        if start > 5000:
            LOG.warning("safety stop at start=%d for SIC %s", start, sic)
            break
    LOG.info("SIC %s · %d ciks", sic, len(ciks))
    return ciks


def fetch_market_cap_batch(tickers: list[str]) -> dict[str, float | None]:
    """yfinance batch → {ticker: market_cap_usd or None}."""
    import yfinance as yf
    out: dict[str, float | None] = {}
    # yfinance batch info 는 불안정 · 개별 조회로 안정성 확보
    for i, tkr in enumerate(tickers):
        if i > 0 and i % 20 == 0:
            LOG.info("mcap %d/%d", i, len(tickers))
        try:
            t = yf.Ticker(tkr)
            info = t.info
            mc = info.get("marketCap")
            out[tkr] = float(mc) if mc else None
        except Exception as e:
            LOG.debug("mcap fail %s: %s", tkr, e)
            out[tkr] = None
    return out


def main() -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # B44 · 기존 보안 경로 연결 (setup_secure_logging 자동 · 2026-08 사고 산출물 재사용)
    from backend.services import config as _config  # noqa: F401
    git_sha = _git_sha()
    snapshot_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with httpx.Client(headers={"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": "gzip"}) as client:
        raw = fetch_company_tickers(client)
        cik_map = cik_to_ticker_map(raw)
        LOG.info("cik→ticker map: %d entries", len(cik_map))

        universe: list[dict] = []
        for sic, subsector in SIC_BIOTECH.items():
            sic_ciks = fetch_sic_ciks(client, sic)
            for cik, name in sic_ciks:
                ticker_pair = cik_map.get(cik)
                ticker = ticker_pair[0] if ticker_pair else None
                universe.append(
                    {
                        "cik": cik,
                        "sic": sic,
                        "subsector": subsector,
                        "company_name": name,
                        "ticker": ticker or "",
                        # listing_status: ticker 매핑 안 되면 DELISTED_OR_ACQUIRED
                        "listing_status_pre_mcap": "ACTIVE" if ticker else "DELISTED_OR_ACQUIRED",
                    }
                )

    LOG.info("SIC 검색 · 총 %d 회사", len(universe))
    active_tickers = [u["ticker"] for u in universe if u["ticker"]]
    LOG.info("액티브 ticker: %d", len(active_tickers))

    mcap = fetch_market_cap_batch(active_tickers)

    for u in universe:
        t = u["ticker"]
        m = mcap.get(t)
        u["market_cap_usd"] = m
        # 최종 listing_status: mcap 있으면 ACTIVE, 없으면 UNKNOWN/DELISTED
        if u["listing_status_pre_mcap"] == "DELISTED_OR_ACQUIRED":
            u["listing_status"] = "DELISTED_OR_ACQUIRED"
        elif m is None:
            u["listing_status"] = "UNKNOWN_LISTING"
        else:
            u["listing_status"] = "ACTIVE"
        # mcap filter (액티브만 적용)
        u["in_scope"] = (
            u["listing_status"] == "ACTIVE"
            and m is not None
            and MCAP_MIN <= m <= MCAP_MAX
        )
        u["snapshot_date"] = snapshot_date
        u["git_sha"] = git_sha
        u.pop("listing_status_pre_mcap", None)

    out_path = DATA_DIR / f"biotech_universe_snapshot_{git_sha}_{snapshot_date}.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "ticker", "cik", "sic", "subsector", "company_name",
                "market_cap_usd", "listing_status", "in_scope",
                "snapshot_date", "git_sha",
            ],
        )
        w.writeheader()
        for u in universe:
            w.writerow(u)
    LOG.info("snapshot → %s", out_path)

    # summary
    total = len(universe)
    active = sum(1 for u in universe if u["listing_status"] == "ACTIVE")
    delisted = sum(1 for u in universe if u["listing_status"] == "DELISTED_OR_ACQUIRED")
    unknown = sum(1 for u in universe if u["listing_status"] == "UNKNOWN_LISTING")
    in_scope = sum(1 for u in universe if u["in_scope"])
    print(f"\n== Biotech Universe Snapshot ({snapshot_date} · {git_sha}) ==")
    print(f"total_sic_matched:     {total}")
    print(f"active_ticker_matched: {active}")
    print(f"delisted_or_acquired:  {delisted}")
    print(f"unknown_listing:       {unknown}")
    print(f"in_scope ($50M-$5B):   {in_scope}")
    print(f"snapshot:              {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
