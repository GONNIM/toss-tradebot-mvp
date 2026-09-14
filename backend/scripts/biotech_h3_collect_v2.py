"""H3 가격 수집 v2 (B87·B88·B89 · 2026-09-04).

전제 (Fable 승인 B87 5건 수정):
1-1. 수집 창: `2020-01-01 ~ form25_date+30d` (event-365 창 아님)
1-2. adj_close 컬럼 · Tiingo adjClose · SimFin 조정가 확인 후
1-3. 원장 140 전량 (kept 5 재수집 포함)
1-4. B74 검증 유지 · bar_density 컬럼 (자동 격리 없음 · 식별용)
1-5. tiingo_unique_symbols_used 누계 (월 500)

큐:
- 폐지 140 · 원장 v2 delisted 바이오 전량 (Tiingo 1차 · SimFin 폴백)
- 활성 194 · yfinance auto_adjust=True 재수집 (--refresh-yfinance)

원장 상태 갱신 (B89):
- kept (Tiingo 통과) · simfin_kept (SimFin 통과) · B60_pending (양측 실패) · unrecoverable (원 티커 부재)

산출:
- backend/data/h3_prices_v2_{sha}_{date}_run{N}.csv (스키마: ticker,date,open,high,low,close,adj_close,volume,source)
- backend/data/h3_prices_checkpoint_v2_{sha}_{date}_run{N}.json (6분류 + bar_density_flags + tiingo 누계)

실행:
    python -m backend.scripts.biotech_h3_collect_v2 --dry-run
    python -m backend.scripts.biotech_h3_collect_v2 --active-refresh  # yfinance 194 재수집
    python -m backend.scripts.biotech_h3_collect_v2 --delisted  # Tiingo → SimFin 폐지 수집
    python -m backend.scripts.biotech_h3_collect_v2 --all  # 활성 + 폐지 순차
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
from datetime import datetime, timedelta
from pathlib import Path

import httpx

LOG = logging.getLogger("biotech_h3_v2")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

FIELDS = ["ticker", "date", "open", "high", "low", "close", "adj_close", "volume", "source"]

TIINGO_MONTHLY_LIMIT = 500  # unique symbols


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


def compute_start_date() -> str:
    return "2020-01-01"


def compute_end_date(form25_date: str) -> str:
    """B87-1-1 · form25_date+30d 로 절단."""
    try:
        fd = datetime.strptime(form25_date, "%Y-%m-%d")
        return (fd + timedelta(days=30)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return datetime.now().strftime("%Y-%m-%d")


def collect_yfinance(ticker: str, start: str, end: str | None = None) -> list[dict]:
    """B88 · yfinance auto_adjust=True · adj_close 포함."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        # auto_adjust=True 는 Close 를 adj close 로 대체
        df = t.history(start=start, end=end, auto_adjust=False)
        if df is None or df.empty:
            return []
        rows = []
        for idx, row in df.iterrows():
            adj = float(row.get("Adj Close", row["Close"])) if "Adj Close" in df.columns else float(row["Close"])
            rows.append({
                "ticker": ticker, "date": str(idx.date()),
                "open": float(row["Open"]) if row["Open"] == row["Open"] else 0.0,
                "high": float(row["High"]) if row["High"] == row["High"] else 0.0,
                "low": float(row["Low"]) if row["Low"] == row["Low"] else 0.0,
                "close": float(row["Close"]) if row["Close"] == row["Close"] else 0.0,
                "adj_close": adj if adj == adj else 0.0,
                "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
                "source": "yfinance",
            })
        return rows
    except Exception as e:
        LOG.debug("yfinance fail %s: %s", ticker, e)
        return []


def collect_tiingo(ticker: str, start: str, end: str, api_key: str) -> list[dict]:
    """Tiingo 일별 · adjClose 포함."""
    if not api_key:
        return []
    url = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices"
    try:
        r = httpx.get(url, params={"startDate": start, "endDate": end, "token": api_key}, timeout=25.0)
        if r.status_code != 200:
            return []
        data = r.json()
        if not isinstance(data, list) or not data:
            return []
        rows = []
        for d in data:
            if not isinstance(d, dict): continue
            date_str = d.get("date", "")[:10]
            if not date_str: continue
            rows.append({
                "ticker": ticker, "date": date_str,
                "open": float(d.get("open") or 0), "high": float(d.get("high") or 0),
                "low": float(d.get("low") or 0), "close": float(d.get("close") or 0),
                "adj_close": float(d.get("adjClose") or d.get("close") or 0),
                "volume": int(d.get("volume") or 0), "source": "tiingo",
            })
        return rows
    except Exception:
        return []


def collect_simfin(ticker: str, start: str, end: str, api_key: str) -> list[dict]:
    """SimFin v3 · Authorization header.
    B90 파서 수정 (2026-09-04) · 컬럼 이름 exact 매핑 (부분 매치 금지 · close∉closing 버그 해결).
    v3 compact columns (9): Date · Dividend Paid · Common Shares Outstanding ·
      Last Closing Price · Adjusted Closing Price · Highest Price · Lowest Price ·
      Opening Price · Trading Volume
    """
    if not api_key:
        return []
    url = "https://backend.simfin.com/api/v3/companies/prices/compact"
    try:
        r = httpx.get(url,
                     params={"ticker": ticker, "start": start, "end": end},
                     headers={"Authorization": f"api-key {api_key}"},
                     timeout=25.0)
        if r.status_code != 200:
            return []
        data = r.json()
        entry = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)
        if not entry: return []
        cols = entry.get("columns", [])
        rows_raw = entry.get("data", [])
        if not cols or not rows_raw: return []
        # B90 · exact 이름 매핑 (v3 compact 확정)
        COL_MAP = {
            "date": "Date",
            "open": "Opening Price",
            "high": "Highest Price",
            "low": "Lowest Price",
            "close": "Last Closing Price",
            "adj_close": "Adjusted Closing Price",
            "volume": "Trading Volume",
        }
        idx = {}
        for k, name in COL_MAP.items():
            idx[k] = cols.index(name) if name in cols else None
        if idx["date"] is None: return []
        rows = []
        for r_ in rows_raw:
            d = str(r_[idx["date"]])[:10]
            def get(key):
                i = idx.get(key)
                if i is None: return None
                v = r_[i]
                return v if v is not None else None
            close_v = get("close"); adj_v = get("adj_close")
            rows.append({
                "ticker": ticker, "date": d,
                "open": float(get("open")) if get("open") is not None else 0.0,
                "high": float(get("high")) if get("high") is not None else 0.0,
                "low": float(get("low")) if get("low") is not None else 0.0,
                "close": float(close_v) if close_v is not None else 0.0,
                "adj_close": float(adj_v) if adj_v is not None else (float(close_v) if close_v is not None else 0.0),
                "volume": int(get("volume")) if get("volume") is not None else 0,
                "source": "simfin",
            })
        return rows
    except Exception:
        return []


def validate_b74(rows: list[dict], form25_date: str) -> tuple[bool, str, list[dict], int]:
    """B74 검증 유지 · first ≤ form25-90d + form25+30d 절단."""
    from datetime import datetime, timedelta
    if not rows: return False, "no_data", [], 0
    if not form25_date: return False, "form25_missing", [], 0
    try:
        f25 = datetime.strptime(form25_date, "%Y-%m-%d")
        first = min(rows, key=lambda r: r["date"])["date"]
        fd = datetime.strptime(first, "%Y-%m-%d")
    except (ValueError, KeyError):
        return False, "date_parse_fail", [], 0
    if fd > f25 - timedelta(days=90):
        return False, f"no_pre_delisting_coverage (first {first} > form25-90d)", [], 0
    cutoff = f25 + timedelta(days=30)
    kept = []; trunc = 0
    for r in rows:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d")
        except (ValueError, KeyError):
            continue
        if d <= cutoff: kept.append(r)
        else: trunc += 1
    return True, "", kept, trunc


def compute_bar_density(rows: list[dict], form25_date: str) -> float:
    """B87-1-4 · 바 수 / 기간 거래일 추정 (252/365 factor)."""
    if not rows or not form25_date: return 0.0
    try:
        first = datetime.strptime(min(r["date"] for r in rows), "%Y-%m-%d")
        f25 = datetime.strptime(form25_date, "%Y-%m-%d")
        cutoff = f25 + timedelta(days=30)
        last = min(datetime.strptime(max(r["date"] for r in rows), "%Y-%m-%d"), cutoff)
        total_days = (last - first).days
        est_biz_days = total_days * 252 / 365
        return len(rows) / est_biz_days if est_biz_days > 0 else 0.0
    except (ValueError, KeyError):
        return 0.0


def refresh_active(git_sha: str, today: str, run_no: int) -> dict:
    """B88 · 활성 194 yfinance adj_close 재수집."""
    q_yf = list(csv.DictReader(open(DATA_DIR / f"queue_yfinance_{git_sha}.csv")))
    prices_path = DATA_DIR / f"h3_prices_v2_{git_sha}_{today}_run{run_no}_active.csv"
    stats = {"queue": len(q_yf), "success": 0, "empty": 0}
    with open(prices_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for i, row in enumerate(q_yf, 1):
            tkr = row["ticker"]
            if i % 20 == 0: LOG.info("yfinance %d/%d", i, len(q_yf))
            data = collect_yfinance(tkr, "2020-01-01", None)
            if data:
                w.writerows(data)
                stats["success"] += 1
            else:
                stats["empty"] += 1
    stats["prices_csv"] = str(prices_path)
    return stats


def collect_delisted(git_sha: str, today: str, run_no: int,
                     tiingo_key: str, simfin_key: str) -> dict:
    """B89 · 폐지 140 Tiingo 1차 → SimFin 폴백."""
    # 원장 v2 로드
    ledger_path = sorted(DATA_DIR.glob("h3_delisted_ledger_v*_*.csv"))[-1]
    with open(ledger_path) as f:
        ledger = list(csv.DictReader(f))
    LOG.info("원장 로드 %s · %d rows", ledger_path.name, len(ledger))

    # 대상 = 전 원장 140 · target_cik → 첫 시도 티커 = SEC 원 티커
    # v2 targets 에서 원 티커 조회
    targets_v2 = {r["target_cik"]: r for r in csv.DictReader(open(DATA_DIR / "h3_targets_v2_add7af7.csv")) if r["target_cik"]}

    prices_path = DATA_DIR / f"h3_prices_v2_{git_sha}_{today}_run{run_no}_delisted.csv"
    stats = {
        "total": len(ledger),
        "kept": [], "simfin_kept": [], "B60_pending": [], "unrecoverable": [],
        "bar_density_low": [],  # <0.85 (거래일 대비 낮은 밀도)
        "truncated_bars_total": 0,
        "tiingo_unique_symbols": set(),
        "tiingo_calls": 0, "simfin_calls": 0,
    }

    with open(prices_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for i, row in enumerate(ledger, 1):
            cik = row["target_cik"]
            form25 = row.get("form25_date", "")
            tgt = targets_v2.get(cik, {})
            # 원 티커 (SEC submissions.tickers)
            ticker = tgt.get("ticker", "") or row.get("final_symbol", "")
            if not ticker:
                stats["unrecoverable"].append(cik)
                continue
            end_date = compute_end_date(form25)
            if i % 10 == 0: LOG.info("delisted %d/%d %s", i, len(ledger), ticker)

            # Tiingo 1차
            stats["tiingo_calls"] += 1
            stats["tiingo_unique_symbols"].add(ticker)
            data = collect_tiingo(ticker, "2020-01-01", end_date, tiingo_key)
            source_used = "tiingo"

            # SimFin 폴백
            if not data:
                stats["simfin_calls"] += 1
                data = collect_simfin(ticker, "2020-01-01", end_date, simfin_key)
                source_used = "simfin"

            if not data:
                stats["B60_pending"].append({"cik": cik, "ticker": ticker, "reason": "both sources empty"})
                continue

            # B74 검증
            ok, reason, kept_rows, trunc = validate_b74(data, form25)
            if not ok:
                stats["B60_pending"].append({"cik": cik, "ticker": ticker, "reason": f"B74: {reason}"})
                continue

            # 통과 · 적재
            w.writerows(kept_rows)
            stats["truncated_bars_total"] += trunc
            density = compute_bar_density(kept_rows, form25)
            if density < 0.85:
                stats["bar_density_low"].append({"cik": cik, "ticker": ticker, "density": round(density, 3), "rows": len(kept_rows)})
            entry = {"cik": cik, "ticker": ticker, "rows": len(kept_rows), "density": round(density, 3), "trunc": trunc}
            if source_used == "tiingo":
                stats["kept"].append(entry)
            else:
                stats["simfin_kept"].append(entry)

    stats["prices_csv"] = str(prices_path)
    stats["tiingo_unique_symbols_used"] = len(stats["tiingo_unique_symbols"])
    stats["tiingo_unique_symbols"] = sorted(stats["tiingo_unique_symbols"])  # 직렬화 위해
    return stats


def update_ledger_v3(stats: dict) -> str:
    """B89 · 원장 상태 초기화 후 재분류 (kept/simfin_kept/B60_pending/unrecoverable)."""
    ledger_path = sorted(DATA_DIR.glob("h3_delisted_ledger_v*_*.csv"))[-1]
    with open(ledger_path) as f:
        rows = list(csv.DictReader(f))

    # cik → new status 매핑
    cik_to_status = {}
    for x in stats["kept"]:
        cik_to_status[x["cik"]] = ("kept", f"B89 Tiingo · rows={x['rows']} · density={x['density']}")
    for x in stats["simfin_kept"]:
        cik_to_status[x["cik"]] = ("simfin_kept", f"B89 SimFin 폴백 · rows={x['rows']} · density={x['density']}")
    for x in stats["B60_pending"]:
        cik_to_status[x["cik"]] = ("B60_pending", f"B89 양소스 실패: {x.get('reason', '')}")
    for cik in stats["unrecoverable"]:
        cik_to_status[cik] = ("unrecoverable", "B89 원 티커 없음")

    # 원장 갱신
    for r in rows:
        cik = r["target_cik"]
        if cik in cik_to_status:
            new_status, new_reason = cik_to_status[cik]
            r["status"] = new_status
            r["status_reason"] = new_reason

    # v3 원장 신설
    new_path = DATA_DIR / f"h3_delisted_ledger_v3_{stats.get('git_sha', 'unknown')}.csv"
    fields = list(rows[0].keys())
    with open(new_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    return str(new_path)


def main() -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from backend.services import config as _config  # noqa: F401

    dry_run = "--dry-run" in sys.argv
    do_active = "--active-refresh" in sys.argv or "--all" in sys.argv
    do_delisted = "--delisted" in sys.argv or "--all" in sys.argv

    _load_dotenv()
    tiingo_key = os.environ.get("TIINGO_API_KEY")
    simfin_key = os.environ.get("SIMFIN_API_KEY")
    LOG.info("tiingo status: %s · simfin status: %s",
             "SET" if tiingo_key else "MISSING", "SET" if simfin_key else "MISSING")

    git_sha = _git_sha()
    today = datetime.now().strftime("%Y-%m-%d")
    run_no = 1
    while list(DATA_DIR.glob(f"h3_prices_v2_{git_sha}_{today}_run{run_no}_*.csv")):
        run_no += 1

    if dry_run:
        print(f"\n== DRY-RUN B87·B88·B89 ==")
        print(f"git_sha: {git_sha} · date: {today} · run: {run_no}")
        print(f"TIINGO/SIMFIN 키: {'SET' if tiingo_key else 'MISSING'} / {'SET' if simfin_key else 'MISSING'}")
        print(f"--active-refresh: {do_active}")
        print(f"--delisted: {do_delisted}")
        return 0

    total_report = {}

    if do_active:
        LOG.info("=== B88 활성 194 재수집 ===")
        stats_a = refresh_active(git_sha, today, run_no)
        total_report["active"] = stats_a

    if do_delisted:
        LOG.info("=== B89 폐지 140 수집 ===")
        stats_d = collect_delisted(git_sha, today, run_no, tiingo_key, simfin_key)
        stats_d["git_sha"] = git_sha
        total_report["delisted"] = stats_d
        # 원장 갱신
        ledger_path = update_ledger_v3(stats_d)
        total_report["ledger_v3"] = ledger_path

    # 체크포인트
    ck_path = DATA_DIR / f"h3_prices_checkpoint_v2_{git_sha}_{today}_run{run_no}.json"
    with open(ck_path, "w") as f:
        json.dump(total_report, f, indent=2, ensure_ascii=False, default=str)

    # 요약
    print(f"\n== B87·B88·B89 실행 · {today} run{run_no} ==")
    if "active" in total_report:
        a = total_report["active"]
        print(f"활성 (B88): queue {a['queue']} · success {a['success']} · empty {a['empty']}")
    if "delisted" in total_report:
        d = total_report["delisted"]
        print(f"폐지 (B89): total {d['total']}")
        print(f"  kept (Tiingo):     {len(d['kept'])}")
        print(f"  simfin_kept:       {len(d['simfin_kept'])}")
        print(f"  B60_pending:       {len(d['B60_pending'])}")
        print(f"  unrecoverable:     {len(d['unrecoverable'])}")
        print(f"  합계 대사:          {len(d['kept'])+len(d['simfin_kept'])+len(d['B60_pending'])+len(d['unrecoverable'])} vs {d['total']}")
        print(f"  bar_density < 0.85: {len(d['bar_density_low'])}")
        print(f"  truncated_bars:    {d['truncated_bars_total']}")
        print(f"  tiingo unique:     {d['tiingo_unique_symbols_used']}/{TIINGO_MONTHLY_LIMIT}")
        print(f"  ledger v3:          {total_report['ledger_v3']}")
    print(f"checkpoint: {ck_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
