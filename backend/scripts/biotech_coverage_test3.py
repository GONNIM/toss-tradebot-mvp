"""Biotech 커버율 실측 · 3소스 (Tiingo · Alpha Vantage · SimFin) · B58 승격 준비.

전제 (B80 신 기준 · 2026-09-04):
- 응답 시계열이 `(event_date-365 ~ event_date)` 창을 실제 커버해야 커버 인정
- first_bar ≤ event-365 AND last_bar ≥ event
- 창 커버 ≥ 18/20 = PASS

3소스 (Fable · EODHD PASS 철회 후 승격 후보):
- Tiingo (무료 1,000 req/day · 500 unique symbols/월 · $30/mo Power)
- Alpha Vantage (무료 25 req/day · $ TBD)
- SimFin (무료 5,000 US 종목 · 5년 history · 500 credits/월 · $15/mo Start)

키 (env):
- TIINGO_API_KEY
- ALPHAVANTAGE_API_KEY
- SIMFIN_API_KEY

FETCH_ERROR (B79): 응답 성공이지만 date 필드 부재 → 별도 분류

실행:
    TIINGO_API_KEY=... ALPHAVANTAGE_API_KEY=... SIMFIN_API_KEY=... \\
        python -m backend.scripts.biotech_coverage_test3
    python -m backend.scripts.biotech_coverage_test3 --dry-run
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging  # noqa: F401

import csv
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

LOG = logging.getLogger("biotech_coverage3")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

V4_SAMPLES_CSV_PREFIX = "biotech_coverage_samples_v4"

# 무료 티어 한도 (페이지 표기)
TIINGO_DAILY = 1000
ALPHAVANTAGE_DAILY = 25
SIMFIN_MONTHLY = 500

# B80 통과선
WINDOW_COVER_THRESHOLD = 18


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
                k = k.strip(); v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1]
                if k and k not in os.environ:
                    os.environ[k] = v
        except Exception:
            pass


def _load_v4_samples() -> list[dict]:
    candidates = sorted(DATA_DIR.glob(f"{V4_SAMPLES_CSV_PREFIX}_*.csv"))
    if not candidates:
        raise SystemExit(f"v4 표본 CSV 부재 · 기대: {DATA_DIR}/{V4_SAMPLES_CSV_PREFIX}_*.csv")
    latest = candidates[-1]
    with open(latest) as f:
        rows = [r for r in csv.DictReader(f) if r.get("verified", "").lower() == "true"]
    return rows


def _window_range(event_date: str) -> tuple[str, str]:
    ev = datetime.strptime(event_date, "%Y-%m-%d")
    return (ev - timedelta(days=365)).strftime("%Y-%m-%d"), event_date


def _judge_coverage(first: str, last: str, win_start: str, win_end: str) -> tuple[bool, str]:
    """B80 신 기준 · first ≤ win_start AND last ≥ win_end."""
    if not first or not last:
        return False, "date_missing (FETCH_ERROR 후보)"
    try:
        fd = datetime.strptime(first, "%Y-%m-%d")
        ld = datetime.strptime(last, "%Y-%m-%d")
        ws = datetime.strptime(win_start, "%Y-%m-%d")
        we = datetime.strptime(win_end, "%Y-%m-%d")
    except ValueError:
        return False, "date_parse_fail"
    covered = fd <= ws and ld >= we
    return covered, f"first={first} last={last} vs win=[{win_start}..{win_end}]"


def test_tiingo(ticker: str, start: str, end: str, api_key: str | None) -> dict:
    """Tiingo daily prices · https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate=&endDate=&token="""
    if not api_key:
        return {"status": "SIGNUP_REQUIRED", "first": "", "last": "", "n": 0}
    url = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices"
    try:
        r = httpx.get(url, params={"startDate": start, "endDate": end, "token": api_key}, timeout=20.0)
        if r.status_code == 401:
            return {"status": "INVALID_KEY_401", "first": "", "last": "", "n": 0}
        if r.status_code == 404:
            return {"status": "NOT_FOUND", "first": "", "last": "", "n": 0}
        if r.status_code == 429:
            return {"status": "RATE_LIMIT_429", "first": "", "last": "", "n": 0}
        if r.status_code != 200:
            return {"status": f"HTTP_{r.status_code}", "first": "", "last": "", "n": 0}
        data = r.json()
        if not isinstance(data, list) or not data:
            return {"status": "EMPTY", "first": "", "last": "", "n": 0}
        # Tiingo date 형식: "2020-05-01T00:00:00.000Z"
        first_raw = data[0].get("date", "")[:10] if isinstance(data[0], dict) else ""
        last_raw = data[-1].get("date", "")[:10] if isinstance(data[-1], dict) else ""
        if not first_raw or not last_raw:
            return {"status": "FETCH_ERROR", "first": "", "last": "", "n": len(data)}
        return {"status": "AVAILABLE", "first": first_raw, "last": last_raw, "n": len(data)}
    except Exception as e:
        return {"status": f"ERR_{type(e).__name__}", "first": "", "last": "", "n": 0}


def test_alpha_vantage(ticker: str, start: str, end: str, api_key: str | None) -> dict:
    """Alpha Vantage TIME_SERIES_DAILY · outputsize=full 로 전 기간.
    B86 · 비정상 응답 본문 200자 보관 (Note/Information 구분용) · 키 마스킹 setup_secure_logging 로 자동.
    """
    if not api_key:
        return {"status": "SIGNUP_REQUIRED", "first": "", "last": "", "n": 0, "body_preview": ""}
    url = "https://www.alphavantage.co/query"
    try:
        r = httpx.get(url, params={
            "function": "TIME_SERIES_DAILY",
            "symbol": ticker, "outputsize": "full", "datatype": "json", "apikey": api_key,
        }, timeout=25.0)
        body_preview = (r.text or "")[:200].replace("\n", " ").strip()
        if r.status_code != 200:
            return {"status": f"HTTP_{r.status_code}", "first": "", "last": "", "n": 0, "body_preview": body_preview}
        data = r.json()
        if "Note" in data:
            return {"status": "NOTE_RATE_LIMIT", "first": "", "last": "", "n": 0, "body_preview": body_preview}
        if "Information" in data:
            return {"status": "INFORMATION_TIER", "first": "", "last": "", "n": 0, "body_preview": body_preview}
        ts = data.get("Time Series (Daily)")
        if not isinstance(ts, dict) or not ts:
            return {"status": "EMPTY", "first": "", "last": "", "n": 0, "body_preview": body_preview}
        dates_in_range = sorted(d for d in ts.keys() if start <= d <= end)
        if not dates_in_range:
            return {"status": "EMPTY_IN_WINDOW", "first": "", "last": "", "n": 0, "body_preview": body_preview}
        return {"status": "AVAILABLE", "first": dates_in_range[0], "last": dates_in_range[-1], "n": len(dates_in_range), "body_preview": ""}
    except Exception as e:
        return {"status": f"ERR_{type(e).__name__}", "first": "", "last": "", "n": 0, "body_preview": ""}


def test_simfin(ticker: str, start: str, end: str, api_key: str | None) -> dict:
    """SimFin v3 API · https://backend.simfin.com/api/v3/companies/prices/compact
    Auth: `Authorization: api-key <key>` header (B82 · 2026-09-04 문서 확인)
    """
    if not api_key:
        return {"status": "SIGNUP_REQUIRED", "first": "", "last": "", "n": 0}
    url = "https://backend.simfin.com/api/v3/companies/prices/compact"
    try:
        r = httpx.get(
            url,
            params={"ticker": ticker, "start": start, "end": end},
            headers={"Authorization": f"api-key {api_key}"},
            timeout=20.0,
        )
        if r.status_code == 401:
            return {"status": "INVALID_KEY_401", "first": "", "last": "", "n": 0}
        if r.status_code == 429:
            return {"status": "RATE_LIMIT_429", "first": "", "last": "", "n": 0}
        if r.status_code == 404:
            return {"status": "NOT_FOUND", "first": "", "last": "", "n": 0}
        if r.status_code != 200:
            return {"status": f"HTTP_{r.status_code}", "first": "", "last": "", "n": 0}
        data = r.json()
        # v3 응답 스키마 정확 확인 위해 여러 형태 지원
        # 후보 1: list[{"columns": [...], "data": [[...]]}]
        # 후보 2: {"columns": [...], "data": [[...]]}
        entry = None
        if isinstance(data, list) and data:
            entry = data[0]
        elif isinstance(data, dict):
            entry = data
        if not entry:
            return {"status": "EMPTY", "first": "", "last": "", "n": 0}
        cols = entry.get("columns", [])
        rows_ = entry.get("data", [])
        if not cols or not rows_:
            return {"status": "EMPTY", "first": "", "last": "", "n": 0}
        # Date 컬럼 찾기
        di = None
        for i, c in enumerate(cols):
            if c and "date" in str(c).lower():
                di = i; break
        if di is None:
            return {"status": "FETCH_ERROR", "first": "", "last": "", "n": len(rows_)}
        dates_in_range = sorted(str(r_[di])[:10] for r_ in rows_ if r_[di] and start <= str(r_[di])[:10] <= end)
        if not dates_in_range:
            return {"status": "EMPTY_IN_WINDOW", "first": "", "last": "", "n": 0}
        return {"status": "AVAILABLE", "first": dates_in_range[0], "last": dates_in_range[-1], "n": len(dates_in_range)}
    except Exception as e:
        return {"status": f"ERR_{type(e).__name__}", "first": "", "last": "", "n": 0}


def main() -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # B44 보안 경로
    from backend.services import config as _config  # noqa: F401

    dry_run = "--dry-run" in sys.argv
    git_sha = _git_sha()
    snapshot_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    _load_dotenv()
    tiingo_key = os.environ.get("TIINGO_API_KEY")
    av_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    sim_key = os.environ.get("SIMFIN_API_KEY")
    LOG.info("tiingo status: %s · av status: %s · simfin status: %s",
             "SET" if tiingo_key else "MISSING",
             "SET" if av_key else "MISSING",
             "SET" if sim_key else "MISSING")

    samples = _load_v4_samples()
    out_path = DATA_DIR / f"biotech_coverage_test3_{git_sha}_{snapshot_date}.csv"

    if dry_run:
        print(f"\n== DRY-RUN B58 3소스 커버율 · B80 신 기준 ==")
        print(f"samples: {len(samples)}")
        print(f"TIINGO_API_KEY: {'SET' if tiingo_key else 'MISSING'}")
        print(f"ALPHAVANTAGE_API_KEY: {'SET' if av_key else 'MISSING'}")
        print(f"SIMFIN_API_KEY: {'SET' if sim_key else 'MISSING'}")
        print(f"통과선 (B80): {WINDOW_COVER_THRESHOLD}/20")
        print(f"호출 계획:")
        print(f"  Tiingo: 1 call × {len(samples)} = {len(samples)} calls (한도 {TIINGO_DAILY}/day · 여유)")
        print(f"  AV:     1 call × {len(samples)} = {len(samples)} calls (한도 {ALPHAVANTAGE_DAILY}/day · 표본 20 = 1일 소진 임박)")
        print(f"  SimFin: 1 call × {len(samples)} = {len(samples)} credits (한도 {SIMFIN_MONTHLY}/월 · 여유)")
        print(f"planned_csv: {out_path}")
        return 0

    # 본 실행 (키 있을 때만 호출 · 없으면 SIGNUP_REQUIRED 기록)
    results = []
    counts = {"tiingo": [0, 0, 0], "av": [0, 0, 0], "sim": [0, 0, 0]}  # [covered, uncovered, error]
    for i, s in enumerate(samples, 1):
        tkr = s["ticker"]
        event = s["event_date"]
        start, end = _window_range(event)
        LOG.info("[%d/%d] %s (event %s · win %s..%s)", i, len(samples), tkr, event, start, end)
        tr = test_tiingo(tkr, start, end, tiingo_key)
        ar = test_alpha_vantage(tkr, start, end, av_key)
        sr = test_simfin(tkr, start, end, sim_key)
        # 커버 판정
        t_cov, t_reason = _judge_coverage(tr["first"], tr["last"], start, end) if tr["status"] == "AVAILABLE" else (False, tr["status"])
        a_cov, a_reason = _judge_coverage(ar["first"], ar["last"], start, end) if ar["status"] == "AVAILABLE" else (False, ar["status"])
        s_cov, s_reason = _judge_coverage(sr["first"], sr["last"], start, end) if sr["status"] == "AVAILABLE" else (False, sr["status"])
        for src, cov, res in [("tiingo", t_cov, tr), ("av", a_cov, ar), ("sim", s_cov, sr)]:
            if cov:
                counts[src][0] += 1
            elif res["status"] == "AVAILABLE":
                counts[src][1] += 1
            else:
                counts[src][2] += 1
        results.append({
            "ticker": tkr, "event_date": event, "win_start": start, "win_end": end,
            "tiingo_status": tr["status"], "tiingo_first": tr["first"], "tiingo_last": tr["last"], "tiingo_n": tr["n"], "tiingo_covered": t_cov,
            "av_status": ar["status"], "av_first": ar["first"], "av_last": ar["last"], "av_n": ar["n"], "av_covered": a_cov,
            "av_body_preview": ar.get("body_preview", ""),  # B86 · 비정상 응답 첫 200자 보관
            "sim_status": sr["status"], "sim_first": sr["first"], "sim_last": sr["last"], "sim_n": sr["n"], "sim_covered": s_cov,
        })

    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader(); w.writerows(results)

    n = len(samples)
    print(f"\n== B58 3소스 커버율 (B80 신 기준 · 창 커버) · {snapshot_date} ==")
    print(f"samples: {n}")
    for src, label in [("tiingo", "Tiingo"), ("av", "Alpha Vantage"), ("sim", "SimFin")]:
        cov, unc, err = counts[src]
        pct = cov / n * 100 if n else 0
        verdict = "PASS" if cov >= WINDOW_COVER_THRESHOLD else "FAIL"
        print(f"  {label:14s} covered={cov}/{n} ({pct:.1f}%) · uncovered={unc} · error/missing={err} · B80({WINDOW_COVER_THRESHOLD}/{n}) {verdict}")
    print(f"csv: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
