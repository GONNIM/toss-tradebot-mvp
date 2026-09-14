"""WP17-4 · H5 백테스트 엔진 (biotech_h3_backtest 동결 · H5 파라미터화 사본).

용도:
- 이벤트 = (해외 촉매 D-day KST × H5 매핑 종목) 곱집합
- 창 3구간 (D-5~D-1 사전 · D+1~D+5 즉시 · D+1~D+20 지속)
- 시장별 벤치 (KOSPI 종목→KS200 · KOSDAQ→KOSDAQ 전체 대체)
- 비용 왕복 0.5% · 양방향 부호 검정 (B8 대립가설)
- **본 실행 금지 (관문 1 통과 전)** · dry-run 만 허용

원칙:
- 사후 조정 금지 (H5-design v2.1 사전 커밋 승계)
- point-in-time: 이벤트 quarter 가 pit_entry_quarter 이상인 종목만 포함
- 매핑 부재 · 가격 부재 표본 제외 + 카운트
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import csv
import json
import logging
import subprocess
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h5_backtest")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

WINDOWS = {
    "pre_D-5_D-1": (-5, -1),
    "imm_D+1_D+5": (1, 5),
    "sus_D+1_D+20": (1, 20),
}
COST_BPS = 50  # 0.5% 왕복


def git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def load_mapping(sha: str) -> list[dict]:
    with (DATA_DIR / f"h5_kr_mapping_v2_{sha}.csv").open() as f:
        return list(csv.DictReader(f))


def load_catalysts(sha: str) -> list[dict]:
    """v3 (WP21 · A/B grade) 우선 → v2 → v1 fallback."""
    p3 = DATA_DIR / f"h5_catalysts_v3_{sha}.csv"
    p2 = DATA_DIR / f"h5_catalysts_v2_{sha}.csv"
    p1 = DATA_DIR / f"h5_catalysts_{sha}.csv"
    p = p3 if p3.exists() else (p2 if p2.exists() else p1)
    with p.open() as f:
        return list(csv.DictReader(f))


def merge_close_events(cross_events: list[dict], stock_prices_map: dict, window_bars: int = 20) -> tuple[list[dict], int]:
    """WP19 v2 · 동일 종목 20 거래일 내 촉매 다건 → 첫 촉매만 유지.

    각 종목 basis: 촉매 d_day_kst 를 stock 시계열 index 로 근사 (없으면 캘린더일 20일 근사).
    """
    if not cross_events:
        return [], 0
    from collections import defaultdict
    by_stock = defaultdict(list)
    for ev in cross_events:
        by_stock[ev["stock_code"]].append(ev)

    kept = []
    dropped = 0
    for code, evs in by_stock.items():
        evs_sorted = sorted(evs, key=lambda e: e["event_d_day"])
        prices = stock_prices_map.get(code, {})
        # 거래일 index (오름차순)
        trading_days = sorted(prices.keys())
        # d_day → 인덱스 근사 · 없으면 캘린더 기반
        def bar_idx(d: str) -> int:
            # bisect
            import bisect
            i = bisect.bisect_left(trading_days, d)
            return i
        last_kept_bar = -10 ** 9
        for ev in evs_sorted:
            idx = bar_idx(ev["event_d_day"])
            if idx - last_kept_bar >= window_bars:
                kept.append(ev)
                last_kept_bar = idx
            else:
                dropped += 1
    return kept, dropped


def load_prices(sha: str) -> dict[str, dict[str, float]]:
    """ticker → {date_str: close} 매핑."""
    out: dict[str, dict[str, float]] = defaultdict(dict)
    with (DATA_DIR / f"h5_prices_{sha}.csv").open() as f:
        for row in csv.DictReader(f):
            try:
                out[row["ticker"]][row["date"]] = float(row["close"])
            except Exception:
                continue
    return out


def quarter_of(date_str: str) -> str:
    """YYYY-MM-DD → YYYYQq."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return ""
    q = (d.month - 1) // 3 + 1
    return f"{d.year}Q{q}"


def pit_eligible(event_quarter: str, entry_quarter: str) -> bool:
    """entry_quarter ≤ event_quarter?"""
    if not event_quarter or not entry_quarter:
        return False
    return entry_quarter <= event_quarter


def window_return(prices: dict[str, float], d_day: str, offset_start: int, offset_end: int) -> tuple[float | None, str]:
    """d_day 기준 offset_start ~ offset_end 영업일 close 사이 raw return.

    영업일 = 가격 존재 날짜. 창 안 첫/마지막 거래일 사용.
    반환: (return, note). 창 존재 부재 시 (None, reason).
    """
    if not prices:
        return None, "no_prices"
    try:
        base = datetime.strptime(d_day, "%Y-%m-%d").date()
    except Exception:
        return None, "bad_d_day"

    def find_trading(offset: int, direction: int) -> str | None:
        # offset 부터 direction 방향 최대 10일 탐색
        for step in range(0, 10):
            d = base + timedelta(days=offset + step * direction)
            k = d.strftime("%Y-%m-%d")
            if k in prices:
                return k
        return None

    start_key = find_trading(offset_start, 1)
    end_key = find_trading(offset_end, -1)
    if not start_key or not end_key or start_key > end_key:
        return None, "no_window_bars"
    r = prices[end_key] / prices[start_key] - 1.0
    return r, "ok"


def market_bench(stock_code: str) -> str:
    """대략 판정: KOSPI200 vs KOSDAQ 전체."""
    # h5_prices FDR 데이터에서 종목이 KOSPI/KOSDAQ 어디에 있는지 사전 정보 없음.
    # 임시 규칙: stock_code 첫 자리로 판정 (완전 정확 X · v2 로 개선 대상).
    # 실제로는 pykrx.stock.get_market_ticker_list 로 확정 · 별건.
    # 여기선 fallback = 두 벤치 모두 산출 · reporting.
    return "both"


def run_dry_run(sha: str) -> dict:
    mapping = load_mapping(sha)
    catalysts = load_catalysts(sha)
    prices = load_prices(sha)

    stock_prices = {m["stock_code"]: prices.get(m["stock_code"], {}) for m in mapping}
    bench_prices = {"KS200": prices.get("KS200", {}), "KOSDAQ": prices.get("KOSDAQ", {})}

    events_total = 0
    excluded_pit = 0
    excluded_no_stock_prices = 0
    excluded_no_bench = 0
    excluded_no_window = 0
    eligible_by_window = {k: 0 for k in WINDOWS}

    sample = []

    for cat in catalysts:
        d_day = cat.get("d_day_kst", "")
        if not d_day:
            continue
        eq = quarter_of(d_day)
        for m in mapping:
            events_total += 1
            eq_entry = m.get("pit_entry_quarter", "")
            if not pit_eligible(eq, eq_entry):
                excluded_pit += 1
                continue
            sp = stock_prices.get(m["stock_code"], {})
            if not sp:
                excluded_no_stock_prices += 1
                continue
            if not bench_prices["KS200"] and not bench_prices["KOSDAQ"]:
                excluded_no_bench += 1
                continue

            per_window = {}
            for wname, (o_s, o_e) in WINDOWS.items():
                r_stock, note_s = window_return(sp, d_day, o_s, o_e)
                # bench dual (KS200 · KOSDAQ) · 실제 시장 판정은 별건 · 여기선 KS200 우선
                r_bench, note_b = window_return(bench_prices["KS200"], d_day, o_s, o_e)
                if r_stock is None or r_bench is None:
                    per_window[wname] = {"status": "no_bars", "s": note_s, "b": note_b}
                    continue
                # net = raw excess - cost
                net = r_stock - r_bench - (COST_BPS / 10000.0)
                per_window[wname] = {"status": "ok", "raw_excess": r_stock - r_bench, "net_excess": net}
                eligible_by_window[wname] += 1

            if any(v.get("status") == "ok" for v in per_window.values()):
                sample.append({
                    "event_d_day": d_day,
                    "ingredient": cat.get("ingredient"),
                    "app_no": cat.get("application_number"),
                    "sub_no": cat.get("submission_number"),
                    "stock_code": m["stock_code"],
                    "name": m["candidate_name"],
                    "pit_entry": eq_entry,
                    **{f"{k}_status": v["status"] for k, v in per_window.items()},
                    **{f"{k}_net_excess": round(v.get("net_excess", 0), 4) for k, v in per_window.items() if v["status"] == "ok"},
                })
            else:
                excluded_no_window += 1

    # 저장
    out_path = DATA_DIR / f"h5_dryrun_sample_{sha}.csv"
    if sample:
        with out_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(sample[0].keys()))
            w.writeheader()
            w.writerows(sample)

    # WP19 v2 병합 (동일 종목 20 거래일 내 촉매 다건 → 1)
    merged_sample, merged_dropped = merge_close_events(sample, stock_prices)
    merged_by_window = {k: sum(1 for r in merged_sample if r.get(f"{k}_status") == "ok") for k in WINDOWS}
    unique_catalyst_dates = len({r["event_d_day"] for r in merged_sample})

    # 병합 후 표본 저장 (v2)
    v2_path = DATA_DIR / f"h5_dryrun_sample_v2_{sha}.csv"
    if merged_sample:
        with v2_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(merged_sample[0].keys()))
            w.writeheader()
            w.writerows(merged_sample)

    return {
        "events_total_cross": events_total,
        "excluded_pit_ineligible": excluded_pit,
        "excluded_no_stock_prices": excluded_no_stock_prices,
        "excluded_no_bench_prices": excluded_no_bench,
        "excluded_no_window_bars": excluded_no_window,
        "eligible_by_window": eligible_by_window,
        "sample_rows_pre_merge": len(sample),
        "sample_csv_pre_merge": str(out_path) if sample else "(empty)",
        "merged_sample_rows": len(merged_sample),
        "merged_dropped_within_20bars": merged_dropped,
        "merged_by_window": merged_by_window,
        "unique_catalyst_dates_after_merge": unique_catalyst_dates,
        "sample_csv_v2": str(v2_path) if merged_sample else "(empty)",
        "bootstrap_note": "재추출 단위 = 촉매 날짜 (클러스터 · 1차 판정) · iid 병기 · 유효 표본 = unique_catalyst_dates_after_merge · 본 실행은 관문 1 통과 후",
    }


def main():
    require_secure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True, help="dry-run 만 허용 (본 실행 금지 · 관문 1 통과 후)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    LOG.info("git_sha=%s · mode=dry-run", sha)

    result = run_dry_run(sha)
    result["git_sha"] = sha
    result["note"] = "관문 1 (H5) 검수 요청 · 백테스트 본 실행 금지"
    LOG.info("summary=%s", json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
