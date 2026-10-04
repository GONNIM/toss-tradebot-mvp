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
    MONTHLY_ALLOCATION, TiingoBlocked, fetch_iex, fetch_one, hourly_check, load_usage, record_request, save_usage,
)
from collections import Counter
from backend.scripts.biotech_sec_common import SEC_DAILY_CAP, SecBlockedError, SecDailyLedger, build_client, nearest_shares_outstanding, sec_get

LOG = logging.getLogger("biotech_mcap_daily")

FLAG = "BIOTECH_MCAP_ENABLED"
IEX_KEEP_DAYS = 30                  # WP75-2 · IEX 응답 원문 보관 기간
BENCH = "XBI"                       # WP95 · 레이더 미반영 채널 기준 (90일 수익률 비교) · IEX 요청에 항상 포함
HISTORY_KEEP_DAYS = 400             # P3a · 가격 누적 파일 보관 (PRD v0.5 6절 · 52주 · 12개월 차트) · WP95 는 100
WINDOW_DAYS = 90                    # 레이더 load_returns_90d 의 달력 90일 창
BACKFILL_MAX = 50                   # 하루 백필 종목 상한 (시간당 50 장부 안에서)
BACKFILL_DAYS = 380                 # P3a · 백필 일봉 기간 (달력) · 12개월 + 여유 · WP95 는 120
YEAR_DAYS = 365                     # P3a · 기록 시작일이 오늘−365일보다 늦으면 백필 대상 (12개월 기록)
SHORT_GAP_DAYS = 10                 # P3a · 백필 첫 거래일이 요청 시작일보다 이만큼 늦으면 상장 뒤 기록이 짧은 종목으로 봄
MIN_DATES_IN_WINDOW = 55            # 90일 창 안 거래일 수 하한 (약 62 거래일 중) · 미만이면 백필 대상
STALE_DAYS = 10                     # 백필로 받은 마지막 거래일이 이보다 오래되면 거래 정지 등으로 보고
SKIP_DAYS = 30                      # 그런 종목은 30일 동안 백필 대상에서 뺌 (2026-10-01 · APGE 9/4 · FBRX 8/27 에서 멈춤)


def _skip_path() -> Path:
    return _P.out_dir("prices") / "backfill_skip.json"


def _short_path() -> Path:
    """P3a · Tiingo 일봉이 12개월보다 짧은 종목 (상장 1년 미만 등) · ticker → 첫 거래일 · 매일 다시 받지 않게."""
    return _P.out_dir("prices") / "backfill_short.json"


def _load_short() -> dict[str, str]:
    p = _short_path()
    return json.loads(p.read_text()) if p.exists() else {}


def _load_skip(today: date) -> dict[str, str]:
    p = _skip_path()
    if not p.exists():
        return {}
    lo = (today - timedelta(days=SKIP_DAYS)).isoformat()
    return {k: v for k, v in json.loads(p.read_text()).items() if v >= lo}


def history_path() -> Path:
    return _P.out_dir("prices") / "iex_daily_history.csv"


def load_history(path: Path | None = None) -> dict[tuple[str, str], float]:
    path = path or history_path()
    out: dict[tuple[str, str], float] = {}
    if path.exists():
        with path.open() as f:
            for r in csv.DictReader(f):
                try:
                    out[(r["ticker"], r["date"])] = float(r["close"])
                except (KeyError, ValueError):
                    continue
    return out


def save_history(hist: dict[tuple[str, str], float], today: date, path: Path | None = None) -> int:
    """HISTORY_KEEP_DAYS 일 지난 행 삭제 후 저장 · 삭제 행 수."""
    path = path or history_path()
    cutoff = (today - timedelta(days=HISTORY_KEEP_DAYS)).isoformat()
    keep = {k: v for k, v in hist.items() if k[1] >= cutoff}
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "date", "close"])
        for (tk, d), c in sorted(keep.items()):
            w.writerow([tk, d, c])
    tmp.replace(path)
    return len(hist) - len(keep)


def needs_backfill(hist: dict[tuple[str, str], float], tickers: list[str], today: date,
                   short: dict[str, str] | None = None) -> list[str]:
    """레이더 90일 창을 덮지 못한 종목 (창 시작 이전 기록 없음 또는 창 안 거래일 < 55)
    + P3a · 기록 시작일이 오늘−365일보다 늦은 종목 (Tiingo 첫 거래일까지 이미 받은 짧은 종목은 제외)."""
    lo = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    lo_year = (today - timedelta(days=YEAR_DAYS)).isoformat()
    short = short or {}
    by: dict[str, list[str]] = {}
    for tk, d in hist:
        by.setdefault(tk, []).append(d)
    out = []
    for tk in tickers:
        ds = by.get(tk, [])
        if not ds or min(ds) > lo or sum(1 for d in ds if d >= lo) < MIN_DATES_IN_WINDOW:
            out.append(tk)
        elif min(ds) > lo_year and not (tk in short and min(ds) <= short[tk]):
            out.append(tk)
    return out


def backfill_prices(tickers: list[str], key: str, get: Callable[..., Any], today: date,
                    now: Callable[[], datetime] | None = None) -> dict:
    """WP95 · 90일 창을 못 덮은 종목을 하루 최대 50개 Tiingo 일봉으로 채움 · H6 수집기·장부 (시간당 50 · 월 고유) 재사용.
    P3a · 기간 380일 · 12개월 기록이 없는 종목도 대상."""
    now = now or (lambda: datetime.now(timezone(timedelta(hours=9))))
    hist = load_history()
    skip = _load_skip(today)
    short = _load_short()
    todo = [t for t in needs_backfill(hist, tickers, today, short) if t not in skip]
    if not todo:
        LOG.info("가격 누적 · 백필 완료 (90일 창 · 12개월 기록을 못 덮은 종목 0)")
        return {"requests": 0, "filled": 0, "remaining": 0, "blocked": None}
    usage = load_usage(today.strftime("%Y%m"))
    start = (today - timedelta(days=BACKFILL_DAYS)).isoformat()
    requests = filled = 0
    blocked = None
    for tk in todo[:BACKFILL_MAX]:
        ok, next_at = hourly_check(usage, now())
        if not ok:
            blocked = f"hourly_limit · next {next_at:%Y-%m-%d %H:%M}"
            LOG.warning("가격 백필 · 시간당 한도 · 다음 가능 시각 %s", f"{next_at:%Y-%m-%d %H:%M}")
            break
        if tk not in usage["symbols"]:
            if len(usage["symbols"]) >= MONTHLY_ALLOCATION:
                continue
            usage["symbols"][tk] = {"first_use": today.isoformat(), "by": "WP75-backfill"}
        record_request(usage, now(), by="WP75-backfill")
        requests += 1
        try:
            bars = fetch_one(get, tk, key, today.isoformat(), start=start)
        except TiingoBlocked as e:
            blocked = str(e)
            LOG.error("%s · 가격 백필 즉시 중단", e)
            break
        except LookupError:
            continue
        for b in bars:
            hist[(tk, b["date"])] = float(b["close"])
        filled += 1
        last_bar = max(b["date"] for b in bars)
        first_bar = min(b["date"] for b in bars)
        if first_bar > (date.fromisoformat(start) + timedelta(days=SHORT_GAP_DAYS)).isoformat():
            short[tk] = first_bar
            LOG.info("가격 백필 · %s 첫 거래일 %s (12개월보다 짧은 기록 · 다시 받지 않음)", tk, first_bar)
        if last_bar < (today - timedelta(days=STALE_DAYS)).isoformat():
            skip[tk] = today.isoformat()
            LOG.info("가격 백필 · %s 마지막 거래일 %s · %d일 동안 백필 제외", tk, last_bar, SKIP_DAYS)
    save_usage(usage)
    save_history(hist, today)
    _skip_path().write_text(json.dumps(skip, ensure_ascii=False))
    _short_path().write_text(json.dumps(short, ensure_ascii=False))
    remaining = len([t for t in needs_backfill(hist, tickers, today, short) if t not in skip])
    LOG.info("가격 백필 · Tiingo 일봉 요청 %d · 채운 종목 %d · 남은 종목 %d%s", requests, filled, remaining,
             " · 백필 완료" if remaining == 0 else "")
    return {"requests": requests, "filled": filled, "remaining": remaining, "blocked": blocked}
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
    tickers = list(dict.fromkeys([*tickers, BENCH]))   # WP95 · XBI 항상 포함
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
    # WP95 · 레이더 90일 수익률 입력 · 마지막 미국 거래일 값만 누적 (오래된 값은 넣지 않음)
    hist = load_history()
    added = sum(1 for tk, p in prices.items() if (tk, p["close_date"]) not in hist)
    for tk, p in prices.items():
        hist[(tk, p["close_date"])] = float(p["close"])
    pruned_rows = save_history(hist, today)
    LOG.info("가격 누적 · %s · 더한 행 %d · %d일 지나 지운 행 %d", last_day, added, HISTORY_KEEP_DAYS, pruned_rows)
    return {**base, "requests": 1, "prices": prices, "hidden": hidden, "last_us_trading_day": last_day,
            "monthly_unique_used": len(usage["symbols"]), "new_symbols": len(new), "history_added": added}


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
        if (mdir / f"shares_{today:%Y%m%d}.json").exists():   # WP98-3 · 같은 날 이미 받았으면 다시 받지 않음
            LOG.info("SEC 주식수 조회 건너뜀 · 오늘 파일 shares_%s.json 있음 (요청 0)", f"{today:%Y%m%d}")
            _record_sec(0, today, ledger)
            return {"mode": mode, "skipped": True, "reason": "already today"}
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
    # WP98 · 주식수 파일이 아직 없으면 (플래그 켠 뒤 첫 주간 잡 전) 주간 주식수 조회를 지금 1회 · 하루 SEC 상한 안에서만
    if not _latest_json("shares"):
        led = ledger or SecDailyLedger.load(f"{today:%Y%m%d}")
        need = sum(1 for cik in cands.values() if cik)
        if led.total() + need > SEC_DAILY_CAP:
            LOG.warning("주식수 파일 없음 · 오늘 SEC %d + 필요 %d > 상한 %d · 주식수 조회 건너뜀 (배지 표시 0)", led.total(), need, SEC_DAILY_CAP)
        else:
            LOG.info("주식수 파일 없음 · 주간 주식수 조회를 지금 1회 실행 (SEC 약 %d회 · 장부 mcap_shares)", need)
            run("weekly", get_sec=get_sec, today=today, ledger=led)
    if get_tiingo is None:
        import httpx
        get_tiingo = httpx.Client(timeout=30).get
    res = daily_prices(sorted(cands), key, get_tiingo, today)
    res["backfill"] = backfill_prices(list(dict.fromkeys([*sorted(cands), BENCH])), key, get_tiingo, today)   # WP95
    del key
    (mdir / f"prices_{today:%Y%m%d}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    display = build_display(_latest_json("shares").get("shares", {}), res["prices"])
    (_root() / "mcap_display.json").write_text(json.dumps(
        {"generated": today.isoformat(), "rows": display}, ensure_ascii=False, indent=1))
    LOG.info("시총 가격 · IEX 요청 %d · 마지막 미국 거래일 %s · 가격 사용 %d · 숨김 %d · 배지 표시 %d · 월 고유 %d (새 등록 %d)",
             res["requests"], res["last_us_trading_day"], len(res["prices"]), len(res["hidden"]), len(display),
             res["monthly_unique_used"], res["new_symbols"])
    return {"mode": mode, "requests": res["requests"], "blocked": res["blocked"], "failed": len(res["failed"]),
            "backfill": res["backfill"], "hidden": len(res["hidden"]), "display_rows": len(display), "monthly_unique_used": res["monthly_unique_used"]}


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["daily", "weekly"])
    args = ap.parse_args()
    print(json.dumps(run(args.mode), ensure_ascii=False))


if __name__ == "__main__":
    main()
