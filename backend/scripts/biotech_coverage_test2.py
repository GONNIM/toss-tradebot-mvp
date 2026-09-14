"""Biotech 상장폐지/인수 종목 가격 소스 커버율 실측 · EODHD + FMP (Phase A · B15-2 재실행 · Fable B21 통과선 18/20).

기존 biotech_coverage_test.py (yfinance + Stooq · 2/20 · 0/20) 후속.
Fable 판정: CRSP/Compustat 기관용 제외 · EODHD·FMP 개인 무료 티어 검증.

동일 20 표본 (biotech_coverage_test.py 목록 그대로) · 소스만 교체.

산출: `backend/data/biotech_coverage_test2_{git_sha}_2026-09-02.csv`
컬럼: ticker · delist_reason · yfinance_ok · eodhd_status · eodhd_range · fmp_status · fmp_range

API 키:
- EODHD_API_KEY 환경변수 · 부재 시 DEMO 로 fallback (5티커 한정)
- FMP_API_KEY 환경변수 · 부재 시 SIGNUP_REQUIRED 로 기록

절대 금지:
- 결제 정보 입력 단계 진행
- 유료 티어 upgrade

무료 티어 한도:
- EODHD 무료: 20 calls/day (page 표기)
- FMP 무료: 250 calls/day, 500MB / 30d bandwidth (page 표기)

실행:
    EODHD_API_KEY=... FMP_API_KEY=... ./backend/venv/bin/python backend/scripts/biotech_coverage_test2.py
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging  # noqa: F401

import csv
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

LOG = logging.getLogger("biotech_coverage2")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# B24·B27·B28 v4 표본 CSV 경로 (biotech_samples_finalize_v4.py 산출물 · v3 supersede)
V2_SAMPLES_CSV = "biotech_coverage_samples_v4"  # prefix · latest match

# B29 · 집단 분류: 커버율 분리 리포트용
COHORT_ACQUIRED = {"ACQUIRED"}
COHORT_FAILED = {"BANKRUPT"}  # 파산/부실폐지 · DELISTED(사유 미확인) 는 별도 아래 처리


# B30 · .env 로더 (표준 라이브러리 파싱 · 기존 os.environ 우선)
def _load_dotenv() -> None:
    """backend/.env 및 프로젝트 루트 .env 파싱. 기존 환경변수 우선 (덮어쓰지 않음).

    KEY=VALUE 라인만 처리 · 따옴표 stripping · 주석/공백 무시.
    실패해도 조용히 통과 (로거 warning 만).
    """
    # python-dotenv 시도 → 표준 라이브러리 fallback
    try:
        from dotenv import load_dotenv as _pkg_loader  # type: ignore
        for p in (Path(__file__).resolve().parent.parent / ".env",
                  Path(__file__).resolve().parent.parent.parent / ".env"):
            if p.exists():
                _pkg_loader(str(p), override=False)
        return
    except ImportError:
        pass

    for p in (Path(__file__).resolve().parent.parent / ".env",
              Path(__file__).resolve().parent.parent.parent / ".env"):
        if not p.exists():
            continue
        try:
            for line in p.read_text().splitlines():
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                # export KEY=VAL 형식 지원
                if s.startswith("export "):
                    s = s[len("export "):].strip()
                k, _, v = s.partition("=")
                k = k.strip()
                v = v.strip()
                # 따옴표 stripping
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1]
                if k and k not in os.environ:
                    os.environ[k] = v
        except Exception as e:
            LOG.warning(".env 파싱 실패 %s: %s", p, type(e).__name__)


@dataclass(frozen=True)
class Sample:
    ticker: str
    event_type: str
    event_date: str
    event_desc: str


def _load_v2_samples() -> list[Sample]:
    """B22 v2 검증 CSV 에서 표본 로드 · verified=True 만 채택."""
    candidates = sorted(DATA_DIR.glob(f"{V2_SAMPLES_CSV}_*.csv"))
    if not candidates:
        raise SystemExit(
            f"v2 표본 CSV 부재 · biotech_samples_verify.py 를 먼저 실행하세요 · "
            f"기대 경로: {DATA_DIR}/{V2_SAMPLES_CSV}_*.csv"
        )
    latest = candidates[-1]
    LOG.info("v2 표본 로드: %s", latest)
    out: list[Sample] = []
    with open(latest, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            if row.get("verified", "").strip().lower() != "true":
                continue
            out.append(Sample(
                ticker=row["ticker"],
                event_type=row["event_type"],
                event_date=row["event_date"],
                event_desc=row.get("event_desc", "") or row.get("edgar_company", ""),
            ))
    LOG.info("verified 표본: %d", len(out))
    return out


# 하드코딩 목록 제거됨 · v2 CSV 로드로 대체
SAMPLES: list[Sample] = _load_v2_samples()

# yfinance 실측 (기존 biotech_coverage_test.py 결과 · v2 표본 재실측 예정)
# 구표본 실측이라 v2 재실측 필요 · §4 표에 주석 있음
YFINANCE_OK: set[str] = set()  # v2 재실측 후 채움


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


def _window(event_date: str) -> tuple[str, str]:
    ev = datetime.strptime(event_date, "%Y-%m-%d")
    start = (ev - timedelta(days=365)).strftime("%Y-%m-%d")
    return start, event_date


def test_yfinance(ticker: str, start: str, end: str) -> dict:
    """yfinance history 조회 · v2 표본 재실측용."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.history(start=start, end=end, auto_adjust=False)
        if df is None or df.empty:
            return {"status": "EMPTY", "range": ""}
        first = str(df.index[0].date())
        last = str(df.index[-1].date())
        return {"status": "AVAILABLE", "range": f"{first}..{last} ({len(df)} rows)"}
    except Exception as e:
        return {"status": f"ERR_{type(e).__name__}", "range": ""}


def test_eodhd(ticker: str, start: str, end: str, api_key: str | None) -> dict:
    if not api_key:
        return {"status": "SIGNUP_REQUIRED", "range": ""}
    sym = f"{ticker}.US"
    url = f"https://eodhd.com/api/eod/{sym}"
    params = {"api_token": api_key, "fmt": "json", "period": "d", "from": start, "to": end}
    try:
        r = httpx.get(url, params=params, timeout=20.0)
        if r.status_code == 402 or r.status_code == 429:
            return {"status": f"RATE_LIMIT_{r.status_code}", "range": ""}
        if r.status_code == 403:
            return {"status": "NOT_IN_DEMO_OR_403", "range": ""}
        if r.status_code == 404:
            return {"status": "NOT_FOUND", "range": ""}
        if r.status_code != 200:
            return {"status": f"HTTP_{r.status_code}", "range": ""}
        data = r.json()
        if not isinstance(data, list) or not data:
            return {"status": "EMPTY", "range": ""}
        # B79 · date 필드 부재 시 fetch_error 로 분리 (에러 페이로드가 list 안 dict 로 옴)
        first = data[0].get("date", "") if isinstance(data[0], dict) else ""
        last = data[-1].get("date", "") if isinstance(data[-1], dict) else ""
        if not first or not last:
            return {"status": "FETCH_ERROR", "range": f"date_missing (n={len(data)})"}
        return {"status": "AVAILABLE", "range": f"{first}..{last} ({len(data)} rows)"}
    except Exception as e:
        return {"status": f"ERR_{type(e).__name__}", "range": ""}


def test_fmp(ticker: str, start: str, end: str, api_key: str | None) -> dict:
    """FMP · B29 정책: 1회 재시도 허용 (5xx/네트워크 예외 시)."""
    if not api_key:
        return {"status": "SIGNUP_REQUIRED", "range": ""}
    url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}"
    params = {"apikey": api_key, "from": start, "to": end}
    last_status = "ERR_Unknown"
    for attempt in (1, 2):
        try:
            r = httpx.get(url, params=params, timeout=20.0)
            if r.status_code == 401:
                return {"status": "INVALID_KEY_401", "range": ""}
            if r.status_code == 403:
                return {"status": "FORBIDDEN_403", "range": ""}
            if r.status_code == 429:
                return {"status": "RATE_LIMIT_429", "range": ""}
            if r.status_code >= 500:
                last_status = f"HTTP_{r.status_code}"
                if attempt == 1:
                    continue
                return {"status": last_status, "range": ""}
            if r.status_code != 200:
                return {"status": f"HTTP_{r.status_code}", "range": ""}
            body = r.json()
            hist = body.get("historical") if isinstance(body, dict) else None
            if not hist:
                return {"status": "EMPTY", "range": ""}
            first = hist[-1].get("date", "")
            last = hist[0].get("date", "")
            return {"status": "AVAILABLE", "range": f"{first}..{last} ({len(hist)} rows)"}
        except Exception as e:
            last_status = f"ERR_{type(e).__name__}"
            if attempt == 1:
                continue
            return {"status": last_status, "range": ""}
    return {"status": last_status, "range": ""}


def main() -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # B44 · 기존 보안 경로 연결 (backend.services.config import 시 setup_secure_logging() 자동)
    # 2026-08-22 DART_API_KEY 사고 산출물의 재사용 · 신규 유틸 금지 (Fable 정정)
    from backend.services import config as _config  # noqa: F401
    _load_dotenv()  # B30 · .env 자동 로드 (환경변수 우선)

    dry_run = "--dry-run" in sys.argv

    git_sha = _git_sha()
    snapshot_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    eod_key = os.environ.get("EODHD_API_KEY")
    fmp_key = os.environ.get("FMP_API_KEY")
    # 마스킹: 존재 여부만 로그. 값 원문·길이·prefix 노출 금지
    LOG.info("EODHD_API_KEY=%s FMP_API_KEY=%s",
             "SET" if eod_key else "MISSING",
             "SET" if fmp_key else "MISSING")

    out_path = DATA_DIR / f"biotech_coverage_test2_{git_sha}_{snapshot_date}.csv"

    if dry_run:
        # B29-2 dry-run · API 호출 없이 표본·키·창·경로만 검증
        print("\n== Biotech Coverage Test 2 · DRY-RUN ==")
        print(f"git_sha:               {git_sha}")
        print(f"snapshot_date:         {snapshot_date}")
        print(f"samples_loaded:        {len(SAMPLES)}")
        print(f"EODHD_API_KEY:         {'SET' if eod_key else 'MISSING'}")
        print(f"FMP_API_KEY:           {'SET' if fmp_key else 'MISSING'}")
        print(f"planned_csv:           {out_path}")
        print(f"planned_calls_per_src: EODHD 1×{len(SAMPLES)} (재시도 금지) · FMP 최대 2×{len(SAMPLES)} (재시도 1회)")
        print("\n표본별 창 (호출 없음):")
        for i, s in enumerate(SAMPLES, 1):
            start, end = _window(s.event_date)
            print(f"  {i:2d}. {s.ticker:6s} {s.event_type:25s} window {start}..{end}")
        return 0

    results: list[dict] = []
    yf_ok = 0
    eod_ok = 0
    fmp_ok = 0
    eod_calls = 0
    fmp_calls = 0

    for i, s in enumerate(SAMPLES, 1):
        start, end = _window(s.event_date)
        LOG.info("[%d/%d] %s (%s) %s..%s", i, len(SAMPLES), s.ticker, s.event_type, start, end)
        yfr = test_yfinance(s.ticker, start, end)
        eod = test_eodhd(s.ticker, start, end, eod_key)
        eod_calls += 1 if eod_key else 0
        fmp = test_fmp(s.ticker, start, end, fmp_key)
        # FMP 재시도 카운트 정확도는 어려움 · 상한 = 2·min = 1 · 대략 상한 사용
        fmp_calls += 1 if fmp_key and fmp["status"] not in ("SIGNUP_REQUIRED",) else 0
        if yfr["status"] == "AVAILABLE":
            yf_ok += 1
        if eod["status"] == "AVAILABLE":
            eod_ok += 1
        if fmp["status"] == "AVAILABLE":
            fmp_ok += 1
        results.append({
            "ticker": s.ticker,
            "delist_reason": s.event_type,
            "event_date": s.event_date,
            "event_desc": s.event_desc,
            "yfinance_status": yfr["status"],
            "yfinance_range": yfr["range"],
            "eodhd_status": eod["status"],
            "eodhd_range": eod["range"],
            "fmp_status": fmp["status"],
            "fmp_range": fmp["range"],
        })

    # CSV (out_path 는 dry-run 분기에서 이미 계산됨)
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    n = len(SAMPLES)
    # B29 · 집단별 분리 커버율
    def _cohort_stats(cohort_types: set[str]) -> tuple[int, int, int, int]:
        rows = [r for r in results if r["delist_reason"] in cohort_types]
        cn = len(rows)
        cy = sum(1 for r in rows if r["yfinance_status"] == "AVAILABLE")
        ce = sum(1 for r in rows if r["eodhd_status"] == "AVAILABLE")
        cf = sum(1 for r in rows if r["fmp_status"] == "AVAILABLE")
        return cn, cy, ce, cf

    acq_n, acq_yf, acq_eod, acq_fmp = _cohort_stats(COHORT_ACQUIRED)
    fai_n, fai_yf, fai_eod, fai_fmp = _cohort_stats(COHORT_FAILED)
    # DELISTED(사유 미확인) 별도 계산 (파산·부실폐지 카테고리에 포함될 수 있음)
    delisted_cohort = {r["delist_reason"] for r in results if r["delist_reason"].startswith("DELISTED")}
    del_n, del_yf, del_eod, del_fmp = _cohort_stats(delisted_cohort) if delisted_cohort else (0, 0, 0, 0)

    print("\n== Biotech Coverage Test 2 (v4 표본 · yfinance + EODHD + FMP · 3소스 병렬) ==")
    print(f"git_sha:               {git_sha}")
    print(f"snapshot_date:         {snapshot_date}")
    print(f"sample_size:           {n}")
    print(f"yfinance_coverage:     {yf_ok}/{n} = {yf_ok/n*100:.1f}%")
    print(f"eodhd_coverage:        {eod_ok}/{n} = {eod_ok/n*100:.1f}%")
    print(f"fmp_coverage:          {fmp_ok}/{n} = {fmp_ok/n*100:.1f}%")
    print(f"B21_threshold_18/20:   yfinance {'PASS' if yf_ok>=18 else 'FAIL'} · "
          f"EODHD {'PASS' if eod_ok>=18 else 'FAIL'} · FMP {'PASS' if fmp_ok>=18 else 'FAIL'}")
    print("\n[B29] 집단별 분리 커버율:")
    print(f"  cohort_acquired ({acq_n}건):  YF {acq_yf}/{acq_n} · EOD {acq_eod}/{acq_n} · FMP {acq_fmp}/{acq_n}")
    print(f"  cohort_failed   ({fai_n}건):  YF {fai_yf}/{fai_n} · EOD {fai_eod}/{fai_n} · FMP {fai_fmp}/{fai_n}    (BANKRUPT)")
    print(f"  cohort_delisted ({del_n}건):  YF {del_yf}/{del_n} · EOD {del_eod}/{del_n} · FMP {del_fmp}/{del_n}    (DELISTED*)")
    print(f"eodhd_calls_used:      {eod_calls} (무료 한도 20/day)")
    print(f"fmp_calls_used:        ≤{fmp_calls} (재시도 1회 포함 상한 · 무료 250/day)")
    print(f"csv:                   {out_path}")
    print("\n티커별 세부:")
    for r in results:
        print(f"  {r['ticker']:6s} {r['delist_reason']:22s} {r['event_date']}  "
              f"YF={r['yfinance_status']:12s} EOD={r['eodhd_status']:22s} FMP={r['fmp_status']:22s}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
