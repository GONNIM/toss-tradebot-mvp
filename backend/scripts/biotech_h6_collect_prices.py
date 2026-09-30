"""H6 가격 수집 (Tiingo · 10월 승인분 · 2026-10-01 실행) · 로컬 실행 전용.

규칙 (docs/plans/biotech/data/h6_params_v2.json price_collection · 사전 고정):
- 대상 = docs/plans/biotech/verification/H6/c3-20260928/h6_price_targets_59.csv (임상 수 많은 순 · priority)
- 1티커 1호출 (전 기간 일봉 · 2014-10-01 ~ 오늘) · 월 고유 종목 450개 이내 (Tiingo 월 한도 500 중 배분)
- 403 · 429 즉시 중단 (남은 종목은 다음 실행) · 키는 config 로더가 읽은 환경변수 TIINGO_API_KEY · 요청 헤더로만 (URL 에 키 없음)
- 월 고유 종목 사용량은 <산출폴더>/tiingo_usage_<YYYYMM>.json 에 누적 (H6 · WP75 공용 장부)

산출 (경로 해석기 out_dir · 로컬 = backend/data/biotech/h6/):
- h6_prices_tiingo_<YYYYMMDD>.csv  (ticker + Tiingo 일봉 열 13개 그대로 + source)
- h6_prices_tiingo_<YYYYMMDD>.summary.json (요청 수 · 성공 · 실패와 사유 · 커버율 · 남은 월 한도) · 사본 docs/plans/biotech/verification/H6/c3-20260928/

커버율:
- 종목 기준 = 일봉을 1개 이상 받은 종목 / 대상 59
- 거래일 기준 = (종목별 받은 날짜 수 합) / (서로 다른 날짜 수 × 대상 수) · 서로 다른 날짜 = 대상 전 종목 일봉 날짜 합집합 (2015-01-01 이후)
  (창 단위 v2.1 판정식 `first_bar ≤ 창시작+7d AND last_bar ≥ event-30d` 은 백테스트 창이 정해지는 본 실행에서 적용)

실행:
    PYTHONPATH=. backend/venv/bin/python -m backend.scripts.biotech_h6_collect_prices --dry-run
    PYTHONPATH=. backend/venv/bin/python -m backend.scripts.biotech_h6_collect_prices
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · .env 로드 (키는 환경변수로만)
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

import httpx

from backend.scripts import _biotech_paths as _P

LOG = logging.getLogger("biotech_h6_collect_prices")

TIINGO_URL = "https://api.tiingo.com/tiingo/daily/{t}/prices"
START_DATE = "2014-10-01"          # H6 첫 분기 2015Q1 직전 여유
COVER_FROM = date(2015, 1, 1)
MONTHLY_ALLOCATION = 450           # 월 고유 종목 배분 (한도 500 중)
REQ_INTERVAL = 1.0                 # 초당 1회 이하 (하루 1,000회 한도와 무관하게 보수적)
TARGETS_REL = ("verification", "H6", "c3-20260928", "h6_price_targets_59.csv")
# Tiingo 일봉 응답 열 전부 (그대로 저장 · 하나라도 빠지면 그 종목 실패)
TIINGO_FIELDS = ["date", "open", "high", "low", "close", "volume",
                 "adjOpen", "adjHigh", "adjLow", "adjClose", "adjVolume", "divCash", "splitFactor"]
CSV_FIELDS = ["ticker"] + TIINGO_FIELDS + ["source"]


class TiingoBlocked(RuntimeError):
    pass


def targets_path() -> Path:
    return _P.DATA_DIR_DOCS.parent.joinpath(*TARGETS_REL)


def load_targets(path: Path | None = None) -> list[str]:
    with (path or targets_path()).open() as f:
        rows = sorted(csv.DictReader(f), key=lambda r: int(r["priority"]))
    return [r["ticker"].strip().upper() for r in rows]


def usage_path(month: str) -> Path:
    return _P.out_dir("h6").parent / f"tiingo_usage_{month}.json"


def load_usage(month: str) -> dict:
    p = usage_path(month)
    return json.loads(p.read_text()) if p.exists() else {"month": month, "symbols": {}}


def save_usage(u: dict) -> None:
    usage_path(u["month"]).write_text(json.dumps(u, ensure_ascii=False, indent=1))


def _weekdays(a: date, b: date) -> int:
    n, d = 0, a
    while d <= b:
        n += d.weekday() < 5
        d += timedelta(days=1)
    return n


def coverage(bars_by_ticker: dict[str, list[dict]], targets: list[str]) -> dict:
    """종목 기준 = 받은 종목 / 대상 · 거래일 기준 분모 = 대상 전체에서 나온 서로 다른 날짜 수 (2015-01-01 이후)."""
    got = [t for t in targets if bars_by_ticker.get(t)]
    dates_by = {t: {b["date"] for b in bars_by_ticker.get(t, []) if b["date"] >= COVER_FROM.isoformat()} for t in targets}
    all_dates = set().union(*dates_by.values()) if dates_by else set()
    denom = len(all_dates)                                                   # 분모 = 서로 다른 날짜 수 (전 종목 합집합)
    ratios = {t: round(len(dates_by[t]) / denom, 4) if denom else 0.0 for t in targets}
    overall = sum(len(v) for v in dates_by.values()) / (denom * len(targets)) if denom and targets else 0.0
    return {"ticker_coverage": f"{len(got)}/{len(targets)}",
            "ticker_coverage_pct": round(len(got) / max(len(targets), 1) * 100, 1),
            "distinct_trading_dates": denom,
            "trading_day_coverage_pct": round(overall * 100, 1),                # (종목별 날짜 수 합) / (분모 × 대상 수)
            "trading_day_coverage_by_ticker": ratios}


def fetch_one(get: Callable[..., Any], ticker: str, key: str, end: str, start: str = START_DATE) -> list[dict]:
    """Tiingo 일봉 1호출 · H6 (전 기간) 와 WP75 시총 (최근 며칠) 가 함께 쓰는 단일 클라이언트."""
    r = get(TIINGO_URL.format(t=ticker), params={"startDate": start, "endDate": end},
            headers={"Authorization": f"Token {key}", "Content-Type": "application/json"})
    if r.status_code in (403, 429):
        raise TiingoBlocked(f"Tiingo HTTP {r.status_code}")
    if r.status_code == 404:
        raise LookupError("not_found")
    if r.status_code != 200:
        raise LookupError(f"http_{r.status_code}")
    data = r.json()
    if not isinstance(data, list) or not data:
        raise LookupError("empty")
    missing = sorted({f for b in data for f in TIINGO_FIELDS if f not in b})
    if missing:
        raise LookupError("missing_fields:" + ",".join(missing))
    return [{"ticker": ticker, **{f: b[f] for f in TIINGO_FIELDS}, "date": str(b["date"])[:10], "source": "tiingo"} for b in data]


def run(targets: list[str], key: str, get: Callable[..., Any], today: date, sleep: Callable[[float], None] = time.sleep) -> dict:
    month = today.strftime("%Y%m")
    usage = load_usage(month)
    bars: dict[str, list[dict]] = {}
    failed: dict[str, str] = {}
    requests = 0
    blocked = None
    for t in targets:
        if t not in usage["symbols"] and len(usage["symbols"]) >= MONTHLY_ALLOCATION:
            failed[t] = "monthly_allocation_reached"
            continue
        if requests:
            sleep(REQ_INTERVAL)
        requests += 1
        usage["symbols"].setdefault(t, {"first_use": today.isoformat(), "by": "H6"})
        try:
            bars[t] = fetch_one(get, t, key, today.isoformat())
        except TiingoBlocked as e:
            blocked = str(e)
            failed[t] = "blocked"
            LOG.error("%s · 즉시 중단 · 남은 종목은 다음 실행", e)
            break
        except LookupError as e:
            failed[t] = str(e)
    save_usage(usage)
    remaining = [t for t in targets if t not in bars and t not in failed]
    return {"requests": requests, "success": len(bars), "failed": failed, "not_attempted": remaining,
            "blocked": blocked, "monthly_unique_used": len(usage["symbols"]),
            "monthly_remaining": MONTHLY_ALLOCATION - len(usage["symbols"]),
            "bars": bars, **coverage(bars, targets)}


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    targets = load_targets()
    key = (os.environ.get("TIINGO_API_KEY") or "").strip()
    today = datetime.now(timezone(timedelta(hours=9))).date()
    LOG.info("H6 가격 수집 · 대상 %d · 키 %s · 월 %s 사용 %d/%d", len(targets), "SET" if key else "MISSING",
             today.strftime("%Y%m"), len(load_usage(today.strftime("%Y%m"))["symbols"]), MONTHLY_ALLOCATION)
    if args.dry_run or not key:
        print(json.dumps({"dry_run": True, "targets": len(targets), "first": targets[:5], "key": "SET" if key else "MISSING",
                          "targets_file": str(targets_path()), "out_dir": str(_P.out_dir("h6"))}, ensure_ascii=False, indent=2))
        return
    client = httpx.Client(timeout=60)
    res = run(targets, key, client.get, today)
    client.close()
    del key
    out = _P.out_dir("h6") / f"h6_prices_tiingo_{today:%Y%m%d}.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for rows in res.pop("bars").values():
            w.writerows(rows)
    summary = {**res, "output": str(out)}
    body = json.dumps(summary, ensure_ascii=False, indent=2)
    out.with_suffix(".summary.json").write_text(body)
    # 요약만 git 추적 폴더에 사본 (가격 CSV 는 git 에 넣지 않음)
    (targets_path().parent / f"h6_prices_tiingo_{today:%Y%m%d}.summary.json").write_text(body)
    print(json.dumps({k: v for k, v in summary.items() if k != "trading_day_coverage_by_ticker"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
