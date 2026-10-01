"""WP75 · 시총 매일 산정 (표시 전용 · 2026-09-28 승인 설계 · 설정 플래그 기본 꺼짐).

- 주식수: SEC companyfacts 의 dei:EntityCommonStockSharesOutstanding · 주 1회 (월요일 주간 AACT 잡 끝) · 후보 종목만
  · 헤더 = biotech_sec_common.build_client() 단일 상수 · 403 · 429 즉시 중단
- 가격 (WP75-2 · 2026-10-01): Tiingo IEX 일괄 **1회** (`/iex/?tickers=…` · 후보 전 종목) · PR #52 클라이언트 모듈
  (biotech_h6_collect_prices.fetch_iex · 같은 헤더 규칙) 과 월 사용 장부 재사용 · 요청 1회를 장부 시간 단위에도 기록
  · tngoLast 의 timestamp 날짜 = 마지막 미국 거래일 (응답 최빈 날짜) 인 종목만 사용 · 아니면 배지 숨김 + "가격 오래됨" 로그
  · 응답 원문 <RUNTIME>/mcap/iex_<YYYYMMDD>.json (30일 지난 파일 삭제) · 새 후보 종목만 월 고유에 추가 등록
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
    MONTHLY_ALLOCATION, TiingoBlocked, fetch_iex, hourly_check, load_usage, record_request, save_usage,
)
from collections import Counter
from backend.scripts.biotech_sec_common import SecBlockedError, SecDailyLedger, build_client, nearest_shares_outstanding, sec_get

LOG = logging.getLogger("biotech_mcap_daily")

FLAG = "BIOTECH_MCAP_ENABLED"
IEX_KEEP_DAYS = 30                  # WP75-2 · IEX 응답 원문 보관 기간
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
    """dei:EntityCommonStockSharesOutstanding 만 (us-gaap 제외).

    - asof 이하 가장 가까운 end 를 고른다 (없으면 공용 헬퍼 규칙대로 가장 가까운 미래)
    - 같은 end 에 값이 여러 개면 (주식 종류가 둘 이상) 같은 공시 (accn) 안의 값을 합산한다
    - 같은 end 를 여러 공시가 보고하면 가장 최근 제출 (filed) 공시 하나만 쓴다 (정정 공시 중복 합산 방지)
    """
    node = (facts.get("facts", {}) or {}).get("dei", {}).get("EntityCommonStockSharesOutstanding")
    if not node:
        return None
    base = nearest_shares_outstanding({"facts": {"dei": {"EntityCommonStockSharesOutstanding": node}}}, asof)
    if not base:
        return None
    same_end = [it for it in (node.get("units", {}) or {}).get("shares", []) if it.get("end") == base["asof"] and it.get("val") is not None]
    by_accn: dict[str, list[dict]] = {}
    for it in same_end:
        by_accn.setdefault(it.get("accn", ""), []).append(it)
    accn, items = max(by_accn.items(), key=lambda kv: (max(i.get("filed", "") for i in kv[1]), kv[0]))
    return {"asof": base["asof"], "shares": sum(int(i["val"]) for i in items), "accn": accn,
            "concept": "dei:EntityCommonStockSharesOutstanding", "n_values": len(items)}


class _ByteCountingClient:
    """공용 SEC 클라이언트를 감싸 받은 바이트만 센다 (헤더·재시도·403 처리는 sec_get 그대로)."""

    def __init__(self, client) -> None:
        self._c, self.bytes = client, 0

    def get(self, *a, **k):
        r = self._c.get(*a, **k)
        self.bytes += len(r.content or b"")
        return r


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
            if hit["n_values"] > 1:
                LOG.info("주식수 합산 · %s · 값 %d개 (주식 종류 둘 이상) · 합 %d · %s", tk, hit["n_values"], hit["shares"], hit["asof"])
            out[tk] = {"cik": cik, "shares": hit["shares"], "shares_asof": hit["asof"], "accn": hit["accn"],
                       "n_values": hit["n_values"]}
    if blocked:
        LOG.error("%s · SEC 주식수 조회 즉시 중단", blocked)
    return {"date": today.isoformat(), "requests": requests, "blocked": blocked, "shares": out}


# ── 가격 (일일) ──────────────────────────────────────────────────────

def prune_iex(folder: Path, today: date, keep_days: int = IEX_KEEP_DAYS) -> int:
    """iex_<YYYYMMDD>.json 중 keep_days 일 지난 파일 삭제 (파일 이름 날짜 기준)."""
    n = 0
    for f in folder.glob("iex_*.json"):
        try:
            d = datetime.strptime(f.stem[4:], "%Y%m%d").date()
        except ValueError:
            continue
        if (today - d).days > keep_days:
            f.unlink()
            n += 1
    return n


def pick_prices(rows: list[dict]) -> tuple[dict, dict, str | None]:
    """마지막 미국 거래일 = tngoLast 가 있는 행의 timestamp 날짜 최빈값 · 그 날짜인 종목만 사용 · 나머지는 숨김."""
    dated = [(str(r.get("ticker", "")).upper(), r.get("tngoLast"), str(r.get("timestamp") or "")[:10]) for r in rows]
    days = Counter(d for _, px, d in dated if px is not None and d)
    last_day = days.most_common(1)[0][0] if days else None
    prices, hidden = {}, {}
    for tk, px, d in dated:
        if px is not None and d and d == last_day:
            prices[tk] = {"close": px, "close_date": d}
        else:
            hidden[tk] = d or "가격 없음"
            LOG.info("가격 오래됨 · %s · %s", tk, d or "가격 없음")
    return prices, hidden, last_day


def daily_prices(tickers: list[str], key: str, get: Callable[..., Any], today: date,
                 now: Callable[[], datetime] | None = None) -> dict:
    """WP75-2 · IEX 일괄 1회 · 새 후보만 월 고유에 등록 · 요청 1회 장부 시간 단위 기록 · 응답 원문 보관."""
    now = now or (lambda: datetime.now(timezone(timedelta(hours=9))))
    month = today.strftime("%Y%m")
    usage = load_usage(month)
    failed: dict[str, str] = {}
    room = MONTHLY_ALLOCATION - len(usage["symbols"])
    ask = []
    for tk in tickers:
        if tk in usage["symbols"]:
            ask.append(tk)
        elif room > 0:
            ask.append(tk)
            room -= 1
        else:
            failed[tk] = "monthly_allocation_reached"
    base = {"date": today.isoformat(), "requests": 0, "blocked": None, "failed": failed, "prices": {}, "hidden": {},
            "last_us_trading_day": None, "monthly_unique_used": len(usage["symbols"]), "new_symbols": 0}
    if not ask:
        return base
    ok, next_at = hourly_check(usage, now())
    if not ok:
        LOG.warning("Tiingo 시간당 한도 · 다음 가능 시각 %s · 가격 단계 건너뜀", f"{next_at:%Y-%m-%d %H:%M}")
        save_usage(usage)
        return {**base, "blocked": f"hourly_limit · next {next_at:%Y-%m-%d %H:%M}"}
    new = [tk for tk in ask if tk not in usage["symbols"]]
    for tk in new:
        usage["symbols"][tk] = {"first_use": today.isoformat(), "by": "WP75"}
    record_request(usage, now(), by="WP75")
    save_usage(usage)
    mdir = _P.out_dir("mcap")
    pruned = prune_iex(mdir, today)
    if pruned:
        LOG.info("IEX 원문 %d일 지난 파일 %d개 삭제", IEX_KEEP_DAYS, pruned)
    try:
        rows = fetch_iex(get, ask, key)
    except TiingoBlocked as e:
        LOG.error("%s · Tiingo 즉시 중단", e)
        return {**base, "requests": 1, "blocked": str(e), "monthly_unique_used": len(usage["symbols"]), "new_symbols": len(new)}
    except LookupError as e:
        LOG.error("IEX 응답 이상 · %s", e)
        return {**base, "requests": 1, "failed": {**failed, "_iex": str(e)}, "monthly_unique_used": len(usage["symbols"]),
                "new_symbols": len(new)}
    (mdir / f"iex_{today:%Y%m%d}.json").write_text(json.dumps(rows, ensure_ascii=False))
    prices, hidden, last_day = pick_prices(rows)
    for tk in ask:
        if tk not in prices and tk not in hidden:
            hidden[tk] = "응답 없음"
    return {**base, "requests": 1, "prices": prices, "hidden": hidden, "last_us_trading_day": last_day,
            "monthly_unique_used": len(usage["symbols"]), "new_symbols": len(new)}


def build_display(shares: dict, prices: dict) -> dict:
    """표시 파일 · 두 쪽 다 있는 종목만 (배지 12개월 / 60일 조건은 API 가 적용)."""
    return {tk: {"shares": s["shares"], "shares_asof": s["shares_asof"],
                 "close": prices[tk]["close"], "close_date": prices[tk]["close_date"]}
            for tk, s in shares.items() if tk in prices}


def _latest_json(prefix: str) -> dict:
    hits = sorted((_root() / "mcap").glob(f"{prefix}_*.json"))
    return json.loads(hits[-1].read_text()) if hits else {}


def _record_sec(n: int, today: date, ledger: SecDailyLedger | None) -> None:
    """WP88-2 · 주식수 조회 SEC 요청을 하루 공용 장부에 "mcap_shares" 로 기록 (꺼져 있으면 0회)."""
    led = ledger or SecDailyLedger.load(f"{today:%Y%m%d}")
    led.add("mcap_shares", n)
    led.save()


def run(mode: str, get_tiingo: Callable[..., Any] | None = None, get_sec: Callable[[str], dict] | None = None,
        today: date | None = None, ledger: SecDailyLedger | None = None) -> dict:
    today = today or _kst_today()
    if not enabled():
        LOG.info("시총 %s 단계 건너뜀 (%s 꺼짐 · Tiingo · SEC 호출 0회)", mode, FLAG)
        if mode == "weekly":
            _record_sec(0, today, ledger)
        return {"mode": mode, "skipped": True, "reason": f"{FLAG} off"}
    cands = load_candidates()
    mdir = _P.out_dir("mcap")
    if mode == "weekly":
        counter = None
        if get_sec is None:
            counter = _ByteCountingClient(build_client())  # biotech_sec_common 단일 헤더 상수 · 받은 용량 집계
            get_sec = lambda url: sec_get(counter, url)    # noqa: E731
        t0 = time.time()
        sent = {"n": 0}      # WP88-3 · 보내기 직전에 셈 · 예외로 끝나도 그때까지 보낸 수를 장부에 남김
        inner = get_sec

        def counted(url: str) -> dict:
            sent["n"] += 1
            return inner(url)

        try:
            res = weekly_shares(cands, counted, today)
        finally:
            _record_sec(sent["n"], today, ledger)
        res["elapsed_sec"] = round(time.time() - t0, 1)
        res["bytes_received"] = counter.bytes if counter else None
        (mdir / f"shares_{today:%Y%m%d}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
        LOG.info("SEC 주식수 조회 · 요청 %d · 소요 %.1f초 · 받은 용량 %s 바이트 · 종목 %d · 합산 종목 %d · 중단 %s",
                 res["requests"], res["elapsed_sec"], res["bytes_received"], len(res["shares"]),
                 sum(1 for v in res["shares"].values() if v.get("n_values", 1) > 1), res["blocked"])
        return {"mode": mode, "requests": res["requests"], "blocked": res["blocked"], "tickers": len(res["shares"]),
                "elapsed_sec": res["elapsed_sec"], "bytes_received": res["bytes_received"]}
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
    LOG.info("시총 가격 · IEX 요청 %d · 마지막 미국 거래일 %s · 가격 사용 %d · 숨김 %d · 배지 표시 %d · 월 고유 %d (새 등록 %d)",
             res["requests"], res["last_us_trading_day"], len(res["prices"]), len(res["hidden"]), len(display),
             res["monthly_unique_used"], res["new_symbols"])
    return {"mode": mode, "requests": res["requests"], "blocked": res["blocked"], "failed": len(res["failed"]),
            "hidden": len(res["hidden"]), "display_rows": len(display), "monthly_unique_used": res["monthly_unique_used"]}


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["daily", "weekly"])
    args = ap.parse_args()
    print(json.dumps(run(args.mode), ensure_ascii=False))


if __name__ == "__main__":
    main()
