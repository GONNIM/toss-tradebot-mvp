"""WP75 · 시총 매일 산정 (표시 전용 · 2026-09-28 승인 설계 · 설정 플래그 기본 꺼짐).

- 주식수: SEC companyfacts 의 dei:EntityCommonStockSharesOutstanding · 주 1회 (월요일 주간 AACT 잡 끝) · 후보 종목만
  · 헤더 = biotech_sec_common.build_client() 단일 상수 · 403 · 429 즉시 중단
- 가격: Tiingo 일 1회 · 후보 종목만 · PR #52 클라이언트 (biotech_h6_collect_prices.fetch_one) 와 월 사용 장부 재사용
  · 403 · 429 즉시 중단 · 키 = config 로더의 환경변수 TIINGO_API_KEY · 요청 헤더로만
- 표시: <RUNTIME>/mcap_display.json (ticker → shares · shares_asof · close · close_date) · API 가 읽어 배지 계산
  · 배지 조건 (API): 주식수 12개월 이내 AND 종가 60일 이내 · 기준일 병기
- 후보 선정 · 점수 · 판정에는 쓰지 않는다 (candidates · time_state · confirm · radar 는 이 파일을 읽지 않음 · 테스트로 강제)

설정 플래그 BIOTECH_MCAP_ENABLED (환경변수 · 기본 꺼짐):
  꺼짐 → Tiingo · SEC 호출 0회 · 단계는 "건너뜀" 으로 기록하고 파이프는 계속
  (SEC 주식수 조회도 같은 플래그로 막음 · 가격 없이 주식수만으로는 쓸 곳이 없어서 승인 전 서버 호출을 늘리지 않음)

실행:
    python -m backend.scripts.biotech_mcap_daily daily    # 일일 07:00 파이프 단계 (가격 · 표시 파일)
    python -m backend.scripts.biotech_mcap_daily weekly   # 주간 잡 (주식수)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import csv
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from backend.scripts import _biotech_paths as _P
from backend.scripts.biotech_h6_collect_prices import (
    MONTHLY_ALLOCATION, REQ_INTERVAL, TiingoBlocked, fetch_one, load_usage, save_usage,
)
from backend.scripts.biotech_sec_common import SecBlockedError, build_client, nearest_shares_outstanding, sec_get

LOG = logging.getLogger("biotech_mcap_daily")

FLAG = "BIOTECH_MCAP_ENABLED"
PRICE_LOOKBACK_DAYS = 10            # 최근 종가 1개를 얻기 위한 조회 창 (주말·휴장 여유)
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


def enabled() -> bool:
    return (os.environ.get(FLAG) or "").strip().lower() in ("1", "true", "on", "yes")


def _root() -> Path:
    return _P.out_dir("mcap").parent        # RUNTIME (서버) · backend/data/biotech (로컬)


def _kst_today() -> date:
    return datetime.now(timezone(timedelta(hours=9))).date()


def load_candidates() -> dict[str, str]:
    """ticker → cik (최신 candidates · 해석기 조회)."""
    p = _P.find_glob("biotech_candidates_2*.csv", subdir="candidates") or _P.find_glob("biotech_candidates_2*.csv")
    if p is None:
        return {}
    with p.open() as f:
        return {r["ticker"]: (r.get("cik") or "") for r in csv.DictReader(f) if r.get("ticker")}


# ── 주식수 (주간) ────────────────────────────────────────────────────

def dei_shares(facts: dict, asof: str) -> dict | None:
    """dei:EntityCommonStockSharesOutstanding 만 (us-gaap 제외) · 공용 헬퍼 재사용."""
    node = (facts.get("facts", {}) or {}).get("dei", {}).get("EntityCommonStockSharesOutstanding")
    if not node:
        return None
    return nearest_shares_outstanding({"facts": {"dei": {"EntityCommonStockSharesOutstanding": node}}}, asof)


def weekly_shares(cands: dict[str, str], get: Callable[[str], dict], today: date) -> dict:
    out: dict[str, dict] = {}
    requests, blocked = 0, None
    for tk, cik in sorted(cands.items()):
        if not cik:
            continue
        requests += 1
        try:
            r = get(SEC_FACTS_URL.format(cik=str(int(cik)).zfill(10)))
        except SecBlockedError as e:
            blocked = str(e)
            break
        if r.get("status") == 429:
            blocked = "SEC HTTP 429"
            break
        if r.get("status") != 200 or not r.get("json"):
            continue
        hit = dei_shares(r["json"], today.isoformat())
        if hit:
            out[tk] = {"cik": cik, "shares": hit["shares"], "shares_asof": hit["asof"], "accn": hit["accn"]}
    if blocked:
        LOG.error("%s · SEC 주식수 조회 즉시 중단", blocked)
    return {"date": today.isoformat(), "requests": requests, "blocked": blocked, "shares": out}


# ── 가격 (일일) ──────────────────────────────────────────────────────

def daily_prices(tickers: list[str], key: str, get: Callable[..., Any], today: date,
                 sleep: Callable[[float], None] = time.sleep) -> dict:
    month = today.strftime("%Y%m")
    usage = load_usage(month)
    out: dict[str, dict] = {}
    failed: dict[str, str] = {}
    requests, blocked = 0, None
    start = (today - timedelta(days=PRICE_LOOKBACK_DAYS)).isoformat()
    for tk in tickers:
        if tk not in usage["symbols"] and len(usage["symbols"]) >= MONTHLY_ALLOCATION:
            failed[tk] = "monthly_allocation_reached"
            continue
        if requests:
            sleep(REQ_INTERVAL)
        requests += 1
        usage["symbols"].setdefault(tk, {"first_use": today.isoformat(), "by": "WP75"})
        try:
            bars = fetch_one(get, tk, key, today.isoformat(), start=start)
            last = max(bars, key=lambda b: b["date"])
            out[tk] = {"close": last["adjClose"], "close_date": last["date"]}
        except TiingoBlocked as e:
            blocked, failed[tk] = str(e), "blocked"
            LOG.error("%s · Tiingo 즉시 중단", e)
            break
        except LookupError as e:
            failed[tk] = str(e)
    save_usage(usage)
    return {"date": today.isoformat(), "requests": requests, "blocked": blocked, "failed": failed, "prices": out,
            "monthly_unique_used": len(usage["symbols"])}


def build_display(shares: dict, prices: dict) -> dict:
    """표시 파일 · 두 쪽 다 있는 종목만 (배지 12개월 / 60일 조건은 API 가 적용)."""
    return {tk: {"shares": s["shares"], "shares_asof": s["shares_asof"],
                 "close": prices[tk]["close"], "close_date": prices[tk]["close_date"]}
            for tk, s in shares.items() if tk in prices}


def _latest_json(prefix: str) -> dict:
    hits = sorted((_root() / "mcap").glob(f"{prefix}_*.json"))
    return json.loads(hits[-1].read_text()) if hits else {}


def run(mode: str, get_tiingo: Callable[..., Any] | None = None, get_sec: Callable[[str], dict] | None = None,
        today: date | None = None) -> dict:
    today = today or _kst_today()
    if not enabled():
        LOG.info("시총 %s 단계 건너뜀 (%s 꺼짐 · Tiingo · SEC 호출 0회)", mode, FLAG)
        return {"mode": mode, "skipped": True, "reason": f"{FLAG} off"}
    cands = load_candidates()
    mdir = _P.out_dir("mcap")
    if mode == "weekly":
        if get_sec is None:
            client = build_client()                        # biotech_sec_common 단일 헤더 상수
            get_sec = lambda url: sec_get(client, url)     # noqa: E731
        res = weekly_shares(cands, get_sec, today)
        (mdir / f"shares_{today:%Y%m%d}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
        return {"mode": mode, "requests": res["requests"], "blocked": res["blocked"], "tickers": len(res["shares"])}
    key = (os.environ.get("TIINGO_API_KEY") or "").strip()
    if not key:
        LOG.warning("TIINGO_API_KEY 없음 · 가격 단계 건너뜀")
        return {"mode": mode, "skipped": True, "reason": "no key"}
    if get_tiingo is None:
        import httpx
        get_tiingo = httpx.Client(timeout=30).get
    res = daily_prices(sorted(cands), key, get_tiingo, today)
    del key
    (mdir / f"prices_{today:%Y%m%d}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    display = build_display(_latest_json("shares").get("shares", {}), res["prices"])
    (_root() / "mcap_display.json").write_text(json.dumps(
        {"generated": today.isoformat(), "rows": display}, ensure_ascii=False, indent=1))
    return {"mode": mode, "requests": res["requests"], "blocked": res["blocked"], "failed": len(res["failed"]),
            "display_rows": len(display), "monthly_unique_used": res["monthly_unique_used"]}


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["daily", "weekly"])
    args = ap.parse_args()
    print(json.dumps(run(args.mode), ensure_ascii=False))


if __name__ == "__main__":
    main()
