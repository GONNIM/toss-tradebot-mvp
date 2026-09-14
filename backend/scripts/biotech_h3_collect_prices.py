"""H3 가격 수집 (B69 배선 · 현행 상태).

큐 (2026-09-03 현행):
- queue_eodhd_v3_{git_sha}.csv (85건 · biotech 폐지 · v3) · EODHD 20/day 분할 · 5일차
- yfinance 는 완료 상태 (194/194 · 1일차) · 이 스크립트에선 EODHD 만 수집 · yfinance 재수집 필요 시 별도 티켓

원장 skip (B67-4):
- 시작 시 `load_ledger_kept_ciks()` · status=kept 인 target_cik 큐에서 제거

수신 즉시 검증 (B74 · 2026-09-03 규칙 교체):
- validate_and_truncate:
  (a) 적격: first_bar ≤ form25_date - 90d (폐지 이전 커버) · 미커버 = 재활용 심볼 quarantine
  (b) 절단: 통과 시 form25_date + 30d 초과 바 제거 후 적재 · truncated_bars 체크포인트
  (c) form25_date 부재 = held (호출 전 큐 분리 · 사전 필터)
- validate_event_window (프로브 대상): first_bar ≤ form25 + 30d 이내
- 격리 원본 보존 · `h3_prices_quarantined_raw_{git_sha}.csv` append (재판정 시 재호출 불필요)

체크포인트 6분류 (B62):
- fetched · rows_gt_0 · validated_kept · quarantined · empty · held (sum_check)

수율 중단선 (B69-5):
- validated_kept / fetched < 0.5 시 루프 중단 + 잔여 큐 보존

가격 데이터 저장:
- backend/data/h3_prices_{git_sha}_{date}.csv (ticker · date · open · high · low · close · volume · source)

원칙 (B47 · B44):
- biotech 독립 이름공간
- setup_secure_logging 재사용

실행:
    python -m backend.scripts.biotech_h3_collect_prices --dry-run
    python -m backend.scripts.biotech_h3_collect_prices
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
from datetime import datetime
from pathlib import Path

import httpx

LOG = logging.getLogger("biotech_h3_prices")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
EODHD_DAILY_QUOTA = 20


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


def _load_dotenv() -> None:
    for p in (Path(__file__).resolve().parent.parent / ".env",):
        if not p.exists():
            continue
        try:
            for line in p.read_text().splitlines():
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                if s.startswith("export "):
                    s = s[len("export "):].strip()
                k, _, v = s.partition("=")
                k = k.strip()
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1]
                if k and k not in os.environ:
                    os.environ[k] = v
        except Exception as e:
            LOG.warning(".env 파싱 실패: %s", type(e).__name__)


def collect_yfinance(ticker: str, start: str) -> list[dict]:
    """yfinance 일봉 수집 · 실패 시 빈 리스트."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.history(start=start, auto_adjust=False)
        if df is None or df.empty:
            return []
        rows = []
        for idx, row in df.iterrows():
            rows.append({
                "ticker": ticker,
                "date": str(idx.date()),
                "open": float(row["Open"]) if row["Open"] == row["Open"] else 0.0,
                "high": float(row["High"]) if row["High"] == row["High"] else 0.0,
                "low": float(row["Low"]) if row["Low"] == row["Low"] else 0.0,
                "close": float(row["Close"]) if row["Close"] == row["Close"] else 0.0,
                "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
                "source": "yfinance",
            })
        return rows
    except Exception as e:
        LOG.debug("yfinance fail %s: %s", ticker, e)
        return []


def load_ledger_kept_ciks() -> set[str]:
    """B67-4 중복 방지 · 원장에서 status=kept 인 target_cik 집합 반환.
    수집기는 큐 처리 전 원장 조회 · kept target_cik 는 skip.
    """
    ledger_glob = list(DATA_DIR.glob("h3_delisted_ledger_v*_*.csv"))
    if not ledger_glob:
        LOG.warning("원장 파일 없음 · 중복 방지 skip")
        return set()
    latest = sorted(ledger_glob)[-1]
    LOG.info("원장 로드: %s", latest)
    with open(latest) as f:
        return {r["target_cik"] for r in csv.DictReader(f) if r.get("status") == "kept" and r.get("target_cik")}


def is_warrant_unit_rights(sym: str, peers: list[str] | None = None) -> bool:
    """B68-2-1 재활용 티커 판정 · W/WS/U/R 접미.
    B69-7 조건부: peers (동일 회사명 후보 집합) 가 주어지면 기저 심볼(접미 제거형)이
    peers 에 존재할 때만 True. 단독 티커(VERU 류) 오탐 방지.
    """
    import re
    m = re.match(r'^(.+?)(W|WS|U|R)$', sym)
    if not m:
        return False
    if peers is None:
        return True  # 조건 없이 접미 판정 (backward compat)
    base = m.group(1)
    return base in peers  # 기저 심볼이 후보에 있어야 접미 배제


def validate_event_window(rows: list[dict], first_event_date: str, form25_date: str) -> tuple[bool, str]:
    """B68 프로브 즉시 검증 · first_date 가 (first_event-1y ~ form25+30d) 창과 겹침 확인."""
    if not rows or not first_event_date or not form25_date:
        return (True, "")  # 데이터 부재 시 스킵
    try:
        from datetime import datetime, timedelta
        first_data = min(rows, key=lambda r: r["date"])["date"]
        fd = datetime.strptime(first_data, "%Y-%m-%d")
        ev = datetime.strptime(first_event_date, "%Y-%m-%d")
        f25 = datetime.strptime(form25_date, "%Y-%m-%d")
        lo = ev - timedelta(days=365)
        hi = f25 + timedelta(days=30)
        if fd > hi:
            return (False, f"first_data {first_data} > event window end {hi.date()}")
        return (True, "")
    except ValueError:
        return (True, "date parse fail · skip")


def validate_and_truncate(rows: list[dict], form25_date: str, pre_cover_days: int = 90, post_cutoff_days: int = 30) -> tuple[bool, str, list[dict], int]:
    """B74 · 격리 규칙 교체 (2026-09-03 · OTC 지속 오격리 루프 종식).

    규칙:
      (a) 적격: first_bar ≤ form25_date - pre_cover_days
          · 시계열이 폐지 이전 구간을 커버해야 통과
          · 미커버 = 재활용 심볼에 새 회사만 실린 것 → quarantine
      (b) 절단 저장: 통과 시 form25_date + post_cutoff_days 초과 바 제거
      (c) form25_date 부재는 held 분류 (호출부에서 사전 분리)

    반환: (kept, reason, truncated_rows, truncated_bars)
    """
    from datetime import datetime, timedelta
    if not rows:
        return (False, "no data", [], 0)
    if not form25_date:
        return (False, "held: form25_date missing", [], 0)
    try:
        f25 = datetime.strptime(form25_date, "%Y-%m-%d")
    except ValueError:
        return (False, "form25_date parse fail", [], 0)
    try:
        first = min(rows, key=lambda r: r["date"])["date"]
        fd = datetime.strptime(first, "%Y-%m-%d")
    except (ValueError, KeyError):
        return (False, "first_bar parse fail", [], 0)
    # (a) 적격 판정
    pre_required = f25 - timedelta(days=pre_cover_days)
    if fd > pre_required:
        return (False,
                f"no pre-delisting coverage · first_bar {first} > form25 {form25_date} - {pre_cover_days}d",
                [], 0)
    # (b) 절단
    cutoff = f25 + timedelta(days=post_cutoff_days)
    kept_rows = []
    truncated = 0
    for r in rows:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d")
        except (ValueError, KeyError):
            continue
        if d <= cutoff:
            kept_rows.append(r)
        else:
            truncated += 1
    return (True, "", kept_rows, truncated)


# 하위 호환 · 기존 validate_last_date 호출 부재 이후 삭제 예정
def validate_last_date(*args, **kwargs):
    raise DeprecationWarning("validate_last_date 는 B74 로 교체됨 · validate_and_truncate 사용")


def collect_eodhd(ticker: str, start: str, api_key: str) -> list[dict]:
    """EODHD 일봉 수집 · 실패 시 빈 리스트 · 재시도 없음 (한도 준수).
    B79 · date 필드 부재 (dict 에러 페이로드) 는 fetch_error 로 처리 · 빈 리스트 반환.
    """
    if not api_key:
        return []
    sym = f"{ticker}.US"
    url = f"https://eodhd.com/api/eod/{sym}"
    params = {"api_token": api_key, "fmt": "json", "period": "d", "from": start}
    try:
        r = httpx.get(url, params=params, timeout=20.0)
        if r.status_code != 200:
            return []
        data = r.json()
        if not isinstance(data, list) or not data:
            return []
        # B79 · 각 element 에서 date 없는 것 필터 (에러 페이로드)
        rows = []
        for d in data:
            if not isinstance(d, dict) or not d.get("date"):
                continue
            rows.append({
                "ticker": ticker,
                "date": d["date"],
                "open": float(d.get("open") or 0),
                "high": float(d.get("high") or 0),
                "low": float(d.get("low") or 0),
                "close": float(d.get("close") or 0),
                "volume": int(d.get("volume") or 0),
                "source": "eodhd",
            })
        return rows
    except Exception:
        return []


def update_ledger_status(kept_ciks_new: set[str]) -> str:
    """B69-4 원장 즉시 갱신 · 새 kept 티커의 target_cik 로 원장 상태 업데이트."""
    ledger_glob = sorted(DATA_DIR.glob("h3_delisted_ledger_v*_*.csv"))
    if not ledger_glob:
        return ""
    latest = ledger_glob[-1]
    with open(latest) as f:
        rows = list(csv.DictReader(f))
    fields = list(rows[0].keys())
    for r in rows:
        if r["target_cik"] in kept_ciks_new and r.get("status") != "kept":
            r["status"] = "kept"
            r["status_reason"] = (r.get("status_reason", "") + " · B69 신규 수집").strip(" ·")
    with open(latest, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    return str(latest)


def main() -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from backend.services import config as _config  # noqa: F401 · B44 보안 경로

    dry_run = "--dry-run" in sys.argv
    git_sha = _git_sha()
    today = datetime.now().strftime("%Y-%m-%d")

    _load_dotenv()
    eod_key = os.environ.get("EODHD_API_KEY")
    # 마스킹 필터 오탐 방지: 라벨을 `key=value` 형태로 두지 않고 상태 명시만
    LOG.info("eodhd credential status: %s", "SET" if eod_key else "MISSING")

    # B81 · 실행별 파일 · run 번호 자동 산정 (기존 파일 스캔)
    run_no = 1
    while (DATA_DIR / f"h3_prices_{git_sha}_{today}_run{run_no}.csv").exists():
        run_no += 1
    LOG.info("run number: %d", run_no)

    # B69-1 · 큐 v3 로드
    q_eod_path = DATA_DIR / f"queue_eodhd_v3_{git_sha}.csv"
    if not q_eod_path.exists():
        LOG.error("queue v3 부재: %s", q_eod_path)
        return 1
    with open(q_eod_path) as f:
        eod_rows = list(csv.DictReader(f))
    LOG.info("queue_eodhd_v3 로드: %d건", len(eod_rows))

    # B67-4 · 원장에서 kept target_cik skip
    kept_ciks = load_ledger_kept_ciks()
    before = len(eod_rows)
    eod_rows = [r for r in eod_rows if r.get("target_cik") not in kept_ciks]
    skip_count = before - len(eod_rows)
    LOG.info("원장 kept skip: %d건 (kept CIK %d개 · 잔여 큐 %d건)", skip_count, len(kept_ciks), len(eod_rows))

    if dry_run:
        print(f"\n== DRY-RUN B69 배선 검증 ==")
        print(f"(a) 큐 v3 로드:          {before}건")
        print(f"    원장 kept skip:      {skip_count}건")
        print(f"    잔여 큐:              {len(eod_rows)}건")
        print(f"(b) kept target_cik 수: {len(kept_ciks)}")
        print(f"(c) 상위 20:")
        for i, r in enumerate(eod_rows[:20], 1):
            print(f"    {i:2d}. {r['ticker']:12s} cik={r.get('target_cik','')[:10]} form25={r.get('form25_date','')}")
        print(f"(d) 검증 함수 연결:")
        print(f"    load_ledger_kept_ciks: {load_ledger_kept_ciks.__name__}")
        print(f"    validate_last_date:    {validate_last_date.__name__}")
        print(f"    validate_event_window: {validate_event_window.__name__}")
        print(f"    is_warrant_unit_rights:{is_warrant_unit_rights.__name__}")
        return 0

    # 백테스트 창
    start_date = "2020-01-01"
    # B81 · 실행별 파일 (덮어쓰기 방지 · 통합기 별도)
    prices_path = DATA_DIR / f"h3_prices_{git_sha}_{today}_run{run_no}.csv"
    checkpoint_path = DATA_DIR / f"h3_prices_checkpoint_{git_sha}_{today}_run{run_no}.json"
    quarantine_path = DATA_DIR / f"h3_prices_quarantine_{git_sha}_{today}_run{run_no}.csv"

    # B62 6분류 + B74 truncated_bars 체크포인트
    ck = {
        "date": today, "git_sha": git_sha,
        "fetched": 0, "rows_gt_0": 0,
        "validated_kept": 0, "quarantined": 0,
        "empty": 0, "held": 0,
        "truncated_bars_total": 0,
        "kept_tickers": [], "quarantined_tickers": [], "empty_tickers": [], "held_tickers": [],
    }
    quarantine_rows: list[dict] = []
    quarantine_raw_rows: list[dict] = []  # B74-2 격리 원본 보존
    kept_ciks_new: set[str] = set()

    # B74-1(c) form25_date 부재 = held (호출 전 큐 분리)
    held_before_call = [r for r in eod_rows if not r.get("form25_date")]
    eod_rows = [r for r in eod_rows if r.get("form25_date")]
    if held_before_call:
        for r in held_before_call:
            ck["held"] += 1
            ck["held_tickers"].append(r["ticker"])
        LOG.info("held (form25_date 부재): %d건", len(held_before_call))

    with open(prices_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "date", "open", "high", "low", "close", "volume", "source"])
        w.writeheader()

        # EODHD 큐 상위 20 (일 한도)
        today_queue = eod_rows[:EODHD_DAILY_QUOTA]
        LOG.info("EODHD 오늘 처리 대상: %d건 (한도 %d/day)", len(today_queue), EODHD_DAILY_QUOTA)

        stop_loop = False
        for i, row in enumerate(today_queue, 1):
            tkr = row["ticker"]
            form25 = row.get("form25_date", "")
            eodhd_delist = row.get("eodhd_delist_date", "")
            first_event = row.get("first_event_date", "")
            is_probe = "similar-resolved" in row.get("ticker_source", "") or "재매칭" in row.get("ticker_source", "")

            LOG.info("[%d/%d] %s (probe=%s)", i, len(today_queue), tkr, is_probe)
            data = collect_eodhd(tkr, start_date, eod_key)
            ck["fetched"] += 1

            if not data:
                ck["empty"] += 1
                ck["empty_tickers"].append(tkr)
            else:
                ck["rows_gt_0"] += 1
                # B74 · 신 규칙: 적격 판정 + 절단
                ok, reason, truncated_data, trunc_bars = validate_and_truncate(data, form25)
                if not ok:
                    ck["quarantined"] += 1
                    ck["quarantined_tickers"].append(tkr)
                    quarantine_rows.append({"ticker": tkr, "target_cik": row.get("target_cik", ""),
                                           "form25_date": form25, "reason": f"validate_and_truncate: {reason}"})
                    # B74-2 원본 보존
                    quarantine_raw_rows.extend(data)
                else:
                    # B68 프로브 즉시 검증 (프로브 대상만) · 절단 후 데이터로 검증
                    if is_probe:
                        ok2, reason2 = validate_event_window(truncated_data, first_event, form25)
                    else:
                        ok2, reason2 = True, ""
                    if not ok2:
                        ck["quarantined"] += 1
                        ck["quarantined_tickers"].append(tkr)
                        quarantine_rows.append({"ticker": tkr, "target_cik": row.get("target_cik", ""),
                                               "form25_date": form25, "reason": f"validate_event_window: {reason2}"})
                        quarantine_raw_rows.extend(data)
                    else:
                        # 통과 · 절단 데이터 적재
                        w.writerows(truncated_data)
                        ck["validated_kept"] += 1
                        ck["kept_tickers"].append(tkr)
                        ck["truncated_bars_total"] += trunc_bars
                        if row.get("target_cik"):
                            kept_ciks_new.add(row["target_cik"])

            # B71 · 매 반복 종료 시 수율 판정 (empty/quarantine continue 우회 방지 · 격리 연속 상황도 커버)
            if ck["fetched"] >= 10:
                yield_rate = ck["validated_kept"] / ck["fetched"]
                if yield_rate < 0.5:
                    LOG.warning("수율 %.1f%% < 50%% · 잔여 %d건 보존 · 루프 중단",
                                yield_rate * 100, len(today_queue) - i)
                    stop_loop = True
                    break

        if stop_loop:
            LOG.info("수율 중단선 발동 · 잔여 큐 %d건 보존", len(today_queue) - ck["fetched"])

    # quarantine CSV
    if quarantine_rows:
        with open(quarantine_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(quarantine_rows[0].keys()))
            w.writeheader(); w.writerows(quarantine_rows)

    # B74-2 격리 원본 보존
    if quarantine_raw_rows:
        raw_path = DATA_DIR / f"h3_prices_quarantined_raw_{git_sha}.csv"
        # 기존 파일에 append (누적)
        write_header = not raw_path.exists()
        with open(raw_path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ticker","date","open","high","low","close","volume","source"])
            if write_header: w.writeheader()
            w.writerows(quarantine_raw_rows)

    # sum_check
    ck["sum_check"] = ck["fetched"] == (ck["validated_kept"] + ck["quarantined"] + ck["empty"] + ck["held"])
    with open(checkpoint_path, "w") as f:
        json.dump(ck, f, indent=2, ensure_ascii=False)

    # 원장 갱신
    ledger_updated = update_ledger_status(kept_ciks_new)

    yr = (ck["validated_kept"] / ck["fetched"] * 100) if ck["fetched"] else 0
    print(f"\n== B69 수집 (3일차 or 이후) · {today} ==")
    print(f"git_sha:              {git_sha}")
    print(f"fetched:              {ck['fetched']}")
    print(f"rows_gt_0:            {ck['rows_gt_0']}")
    print(f"validated_kept:       {ck['validated_kept']}")
    print(f"quarantined:          {ck['quarantined']}")
    print(f"empty:                {ck['empty']}")
    print(f"held:                 {ck['held']}")
    print(f"truncated_bars_total: {ck.get('truncated_bars_total', 0)}")
    print(f"sum_check:            {ck['sum_check']}")
    print(f"수율 (kept/fetched):  {yr:.1f}%")
    print(f"원장 갱신:            {ledger_updated}")
    print(f"prices_csv:           {prices_path}")
    print(f"checkpoint:           {checkpoint_path}")
    if quarantine_rows:
        print(f"quarantine:           {quarantine_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
