"""WP63-2 · Form 4 매수 추종 재실행 (사전 커밋 · 시총 필터 + $1 필터 + 극단값 표).

WP63 (v1) 무효 (시총 필터 미적용 · 극단값 포함) → v2 사전 커밋 규칙:
- 시총 필터: $50M~$5B (h3_mcap · 부재 발행사 제외 · n 보고)
- 진입가 (D+1 종가) < $1 제외
- 실행 전 극단값 점검: 병합 후 30d/180d 원시 수익 상위 5건 표 (종목·날짜·진입·청산·원인)
- 판정: §2 H3 임계 동일 (30d +5% · 180d +15% · hit ≥ 35% · CI 하한 > 0)
- WP64 안전장치 자동 발동 · 격리 발생 시 alpha_pass_machine=held_for_review

봉인: h3f4_v2_seal_{sha}.json
리포트: verification/H3/H3-F4-report-v2-YYYYMMDD.md (v1 무효 이력 보존)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging, data_sha
from backend.scripts.biotech_h3_backtest import (
    run_backtest, load_prices, BENCHMARK_TICKER,
)
from backend.scripts.biotech_h63_f4_backtest import (
    git_sha, load_cik_ticker, merge_20d_first,
)

import csv
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h63v2_f4_backtest")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

MCAP_MIN = 50_000_000  # $50M
MCAP_MAX = 5_000_000_000  # $5B


def load_mcap_lookup(sha: str, prices: dict) -> dict:
    """CIK → shares · asof 날짜 종가 * shares = mcap (개략).

    h3_mcap.csv 는 shares 만 · shares × 그 시점 종가 로 mcap 근사.
    """
    m = {}
    p = DATA_DIR / f"h3_mcap_{sha}.csv"
    cik2tk = load_cik_ticker(sha)
    if not p.exists():
        return m
    with p.open() as f:
        for r in csv.DictReader(f):
            cik = (r.get("cik") or "").zfill(10)
            asof = r.get("asof", "")
            try:
                shares = float(r.get("shares", 0))
            except Exception:
                continue
            tk = cik2tk.get(cik, "")
            if not tk or shares <= 0:
                continue
            sp = prices.get(tk, {})
            # asof 근처 종가
            close = None
            keys = sorted(sp.keys())
            for k in keys:
                if k >= asof:
                    close = sp[k]
                    break
            if close is None and keys:
                close = sp[keys[-1]]
            if close and close > 0:
                m[cik] = shares * close
    return m


def load_entry_price(prices: dict, ticker: str, event_date: str) -> float | None:
    """D+1 근처 종가 (진입 가격 근사)."""
    sp = prices.get(ticker, {})
    if not sp:
        return None
    keys = sorted(sp.keys())
    for k in keys:
        if k >= event_date:
            return sp[k]
    return None


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    if not (DATA_DIR / f"h3_events_{sha}.csv").exists():
        fb = data_sha(DATA_DIR)
        if fb:
            LOG.info("git_sha %s 데이터 부재 · data_sha fallback → %s", sha, fb)
            sha = fb

    # F4_buy 이벤트
    with (DATA_DIR / f"h3_events_{sha}.csv").open() as f:
        all_events = list(csv.DictReader(f))
    f4_events = [e for e in all_events if e.get("event_type") == "F4_buy"]
    LOG.info("F4_buy events: %d", len(f4_events))

    # 20일 첫 건 병합
    merged = merge_20d_first(f4_events)
    cik2tk = load_cik_ticker(sha)
    for e in merged:
        cik = (e.get("target_cik") or "").zfill(10)
        e["ticker"] = cik2tk.get(cik, "")
    merged = [e for e in merged if e.get("ticker")]
    LOG.info("merged with ticker: %d", len(merged))

    prices = load_prices(DATA_DIR / f"h3_prices_merged_{sha}.csv")
    bench_all = load_prices(DATA_DIR / f"benchmarks_{sha}.csv")
    bench_prices = bench_all.get(BENCHMARK_TICKER, {})

    # 시총 필터
    mcap_lookup = load_mcap_lookup(sha, prices)
    LOG.info("mcap_lookup: %d CIKs", len(mcap_lookup))

    filtered_events = []
    filter_stats = {"total_merged": len(merged), "no_mcap": 0, "mcap_out_of_range": 0,
                    "entry_price_lt_1": 0, "no_entry_price": 0, "no_prices": 0}
    for e in merged:
        cik = (e.get("target_cik") or "").zfill(10)
        tk = e.get("ticker", "")
        mcap = mcap_lookup.get(cik)
        if mcap is None:
            filter_stats["no_mcap"] += 1
            continue
        if not (MCAP_MIN <= mcap <= MCAP_MAX):
            filter_stats["mcap_out_of_range"] += 1
            continue
        # 진입가 $1 필터
        entry_p = load_entry_price(prices, tk, e.get("event_date", ""))
        if entry_p is None:
            filter_stats["no_entry_price"] += 1
            continue
        if entry_p < 1.0:
            filter_stats["entry_price_lt_1"] += 1
            continue
        e["_entry_price"] = entry_p
        e["_mcap"] = mcap
        filtered_events.append(e)

    LOG.info("filtered (시총 $50M~$5B + $1 filter): %d · stats=%s", len(filtered_events), filter_stats)

    # 극단값 점검 (30d/180d 원시 수익) · 상위 5건 표
    extreme_top5 = []
    for e in filtered_events:
        tk = e["ticker"]
        d_day = e.get("event_date", "")
        entry_p = e["_entry_price"]
        for h in [30, 180]:
            sp = prices.get(tk, {})
            keys = sorted(sp.keys())
            target_key = None
            from datetime import datetime, timedelta
            try:
                base = datetime.strptime(d_day, "%Y-%m-%d").date()
            except Exception:
                continue
            target_date = (base + timedelta(days=h)).strftime("%Y-%m-%d")
            for k in keys:
                if k >= target_date:
                    target_key = k
                    break
            if not target_key:
                continue
            exit_p = sp[target_key]
            raw_ret = (exit_p / entry_p - 1) * 100  # percentage
            extreme_top5.append({
                "ticker": tk, "event_date": d_day, "horizon": h,
                "entry_price": round(entry_p, 4), "exit_price": round(exit_p, 4),
                "raw_return_pct": round(raw_ret, 2),
                "cause_hint": "data_error" if abs(raw_ret) > 500 else "extreme_move" if abs(raw_ret) > 300 else "normal",
            })

    extreme_top5.sort(key=lambda x: -abs(x["raw_return_pct"]))
    extreme_top5 = extreme_top5[:5]
    LOG.info("extreme top 5: %s", json.dumps(extreme_top5, ensure_ascii=False))

    # SIC lookup
    sic_lookup = {}
    with (DATA_DIR / f"h3_targets_v2_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            cik = (r.get("target_cik") or "").zfill(10)
            sic = r.get("sic", "")
            if cik and sic:
                sic_lookup[cik] = sic

    # 백테 실행 (WP64 안전장치 자동 발동)
    result = run_backtest(filtered_events, prices, bench_prices, mcap_lookup, sic_lookup, seed=42)
    summary = result["summary"]

    # 판정 (WP64 held_for_review 반영)
    alpha_info = summary.get("alpha_confirmed", {})
    extreme_count = summary.get("extreme_review", {}).get("count", 0)

    thresholds = {"h_30d": 5.0, "h_180d": 15.0}
    per_horizon = {}
    for h_key, h_result in summary.get("horizons", {}).items():
        if not h_result or h_result.get("n", 0) == 0:
            per_horizon[h_key] = {"n": 0}
            continue
        per_horizon[h_key] = {
            "n": h_result.get("n", 0),
            "mean": h_result.get("mean_net_excess", 0),
            "trimmed_mean_1_99": h_result.get("trimmed_mean_1_99", 0),
            "log_return_mean": h_result.get("log_return_mean", 0),
            "hit_pct": h_result.get("hit_rate_pct", 0),
            "ci_block_lo": h_result.get("ci_block_95_lo", 0),
            "ci_block_hi": h_result.get("ci_block_95_hi", 0),
            "extreme_count": h_result.get("extreme_count", 0),
            "threshold": thresholds.get(h_key, 0),
            "alpha_pass_machine": alpha_info.get(f"{h_key}_alpha_pass_machine"),
        }

    deprecation = all((v.get("ci_block_lo", 0) or 0) <= 0 for v in per_horizon.values() if "ci_block_lo" in v)

    seal = {
        "git_sha": sha,
        "version": "WP63-2 · Form 4 매수 추종 (시총 필터 + $1 filter + WP64 안전장치)",
        "principle": "H3 리포트 불변 · Form 4 별도 · WP63 v1 무효 이력 보존",
        "input_f4_events": len(f4_events),
        "merged_20d_first": len(merged),
        "filter_stats": filter_stats,
        "filtered_events": len(filtered_events),
        "backtest_n": summary.get("per_event_count", 0),
        "extreme_review": summary.get("extreme_review", {}),
        "extreme_top5_precheck": extreme_top5,
        "horizons": per_horizon,
        "alpha_confirmed": alpha_info,
        "deprecation_triggered": deprecation,
    }

    out_dir = DATA_DIR / "biotech" / "seals"
    out_dir.mkdir(parents=True, exist_ok=True)
    seal_path = out_dir / f"h3f4_v2_seal_{sha}.json"
    seal_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2))

    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    report_dir = PROJECT_ROOT / "docs" / "plans" / "biotech" / "verification" / "H3"
    h30 = per_horizon.get("h_30d", {})
    h180 = per_horizon.get("h_180d", {})

    def fmt_pct(v):
        return f"{v:+.2f}%" if isinstance(v, (int, float)) else "?"

    report = [
        f"# H3-F4 v2 · Form 4 매수 추종 재실행 (WP63-2 · {today_str} · git_sha {sha})",
        "",
        "> 📖 [`GLOSSARY.md`](../../GLOSSARY.md) · 코드 · 상태 · 가설 뜻",
        "> ⚠️ WP63 v1 은 **무효** (시총 필터 미적용 · 극단값 포함) · 이력 보존",
        "",
        "## 사전 커밋 (v2)",
        "",
        "- 시총 필터: **$50M~$5B** (h3_mcap · 부재 발행사 제외)",
        "- 진입가 (D+1 종가) **< $1 제외**",
        "- WP64 엔진 안전장치 자동 발동: net excess > +300% or < -95% 격리 · alpha_pass_machine=held_for_review",
        "- 판정: §2 H3 임계 동일 (30d +5% · 180d +15% · hit ≥ 35% · CI 하한 > 0)",
        "",
        "## 표본 흐름",
        "",
        f"- 원 F4_buy: **{len(f4_events)}** → 20일 병합: **{len(merged)}** → 티커 매핑",
        f"- 시총 필터 후: **{len(filtered_events)}** · stats: {json.dumps(filter_stats, ensure_ascii=False)}",
        f"- 백테스트 표본 n: **{summary.get('per_event_count', 0)}**",
        f"- WP64 격리 (extreme_review): **{extreme_count}건**",
        "",
        "## 극단값 사전 점검 (원시 수익 상위 5건 · 수동 검토용)",
        "",
        "| ticker | 이벤트일 | 창 | 진입가 | 청산가 | 원시 수익 | 원인 힌트 |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in extreme_top5:
        report.append(f"| **{t['ticker']}** | {t['event_date']} | {t['horizon']}d | ${t['entry_price']} | ${t['exit_price']} | **{t['raw_return_pct']:+.1f}%** | {t['cause_hint']} |")

    report += [
        "",
        "## 결과 표 (엔진 동결 · WP64 안전장치 자동)",
        "",
        "| 창 | n | 평균 net excess | 절사 평균 (1/99) | 로그 평균 | 히트율 | CI 클러스터 하한 | CI 상한 | 격리 | 판정 |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| **30d** | {h30.get('n', '?')} | **{fmt_pct(h30.get('mean', 0))}** | {fmt_pct(h30.get('trimmed_mean_1_99', 0))} | {h30.get('log_return_mean', 0):+.4f} | {h30.get('hit_pct', 0):.1f}% | {fmt_pct(h30.get('ci_block_lo', 0))} | {fmt_pct(h30.get('ci_block_hi', 0))} | {h30.get('extreme_count', 0)} | **{h30.get('alpha_pass_machine', 'n/a')}** |",
        f"| **180d** | {h180.get('n', '?')} | **{fmt_pct(h180.get('mean', 0))}** | {fmt_pct(h180.get('trimmed_mean_1_99', 0))} | {h180.get('log_return_mean', 0):+.4f} | {h180.get('hit_pct', 0):.1f}% | {fmt_pct(h180.get('ci_block_lo', 0))} | {fmt_pct(h180.get('ci_block_hi', 0))} | {h180.get('extreme_count', 0)} | **{h180.get('alpha_pass_machine', 'n/a')}** |",
        "",
        f"**폐기 조건 (양 창 CI 하한 ≤ 0) 발동**: **{deprecation}**",
        "",
        "## 쉬운 말 5줄",
        "",
        f"1. 임원 매수 (Form 4 P) 신호 · 시총 $50M~$5B 필터 + $1 filter 적용 · WP64 안전장치 자동 발동 (극단값 격리 · n={extreme_count}).",
        f"2. 표본 흐름: 원 {len(f4_events)} → 병합 {len(merged)} → 시총 필터 {len(filtered_events)} → 백테 {summary.get('per_event_count', 0)}.",
        f"3. 30d 창: n={h30.get('n', 0)} · 평균 **{fmt_pct(h30.get('mean', 0))}** · 절사 평균 {fmt_pct(h30.get('trimmed_mean_1_99', 0))} · CI 하한 {fmt_pct(h30.get('ci_block_lo', 0))} · alpha_pass_machine=**{h30.get('alpha_pass_machine', 'n/a')}**.",
        f"4. 180d 창: n={h180.get('n', 0)} · 평균 **{fmt_pct(h180.get('mean', 0))}** · 절사 평균 {fmt_pct(h180.get('trimmed_mean_1_99', 0))} · CI 하한 {fmt_pct(h180.get('ci_block_lo', 0))} · alpha_pass_machine=**{h180.get('alpha_pass_machine', 'n/a')}**.",
        f"5. 폐기 조건 발동: **{deprecation}** · H3 리포트와 합산 금지 · v1 무효 이력 보존.",
        "",
        "## 가능성 지도 (3줄 · WP36 필수)",
        "",
        f"1. 가장 밝은 자리 = {'없음 · 양 창 폐기 발동' if deprecation else '30d/180d 중 임계 초과 창 · 다음 조건 재검'}",
        f"2. 죽은 자리 = WP63 v1 무효 (이력 보존) · {'F4 매수 추종 규칙 폐기 완료' if deprecation else '판정 유보 · WP64 held_for_review'}",
        "3. 다음에 팔 자리 = 실전 규칙 재검 (소액) · Phase C 4 (다른 알파 후보 발굴) · WP54-3 (H8 검정 3 + H1b 봉인 유지)",
    ]
    report_path = report_dir / f"H3-F4-report-v2-{today_str}.md"
    report_path.write_text("\n".join(report))

    print(json.dumps({
        "git_sha": sha, "seal_path": str(seal_path), "report_path": str(report_path),
        "filter_stats": filter_stats,
        "filtered_events": len(filtered_events),
        "backtest_n": summary.get("per_event_count", 0),
        "extreme_count": extreme_count,
        "h30": h30, "h180": h180,
        "deprecation_triggered": deprecation,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
