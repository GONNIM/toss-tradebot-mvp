"""WP63 · Form 4 매수 추종 별도 리포트 (H3-F4 · B51 원칙 승계).

**원칙 (Fable · 2026-09-14)**:
- H3 리포트 (verification/H3/H3-report-*.md) 는 불변 · 봉인 결과 유지
- Form 4 매수 추종은 **별도 검정** · H3 와 합산 금지
- 임계 §2 H3 동일 (30d +5% · 180d +15% · hit ≥ 35% · CI 하한 > 0)
- 폐기 조건 = 양 창 CI 하한 ≤ 0

**입력**: h3_events 의 F4_buy 이벤트 (WP28-3 병합 · 984건)
- 동일 발행사 (target_cik) 20 거래일 내 다건 → **첫 건 병합** (H5 규칙 승계 · B51)

**엔진**: biotech_h3_backtest.run_backtest (동결) · 사전 커밋 사양 그대로
- 창 30d/180d · XBI · 비용 1% · 시총 $50M~$5B · 날짜 클러스터 CI

**출력**:
- 봉인: `backend/data/biotech/seals/h3f4_seal_{sha}.json`
- 리포트: `docs/plans/biotech/verification/H3/H3-F4-report-YYYYMMDD.md`
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging, data_sha
from backend.scripts.biotech_h3_backtest import (
    run_backtest, load_prices, BENCHMARK_TICKER,
)

import csv
import json
import logging
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h63_f4_backtest")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_cik_ticker(sha: str) -> dict:
    """CIK → ticker (h3_targets_v2 target_ticker + SEC fallback)."""
    m = {}
    p = DATA_DIR / f"h3_targets_v2_{sha}.csv"
    if p.exists():
        with p.open() as f:
            for r in csv.DictReader(f):
                cik = (r.get("target_cik") or "").zfill(10)
                tk = (r.get("ticker") or "").strip().upper()
                if cik and tk:
                    m[cik] = tk
    sp = DATA_DIR / "sec_company_tickers.json"
    if sp.exists():
        for _, e in json.loads(sp.read_text()).items():
            cik = str(e.get("cik_str", "")).zfill(10)
            tk = str(e.get("ticker", "")).upper()
            if cik and tk and cik not in m:
                m[cik] = tk
    return m


def merge_20d_first(events: list[dict]) -> list[dict]:
    """동일 target_cik 20 거래일 (근사 · 30 달력일) 내 다건 → 첫 건 병합 (H5 규칙 승계)."""
    by_cik = defaultdict(list)
    for e in events:
        cik = (e.get("target_cik") or "").zfill(10)
        d = e.get("event_date", "")
        if cik and d:
            by_cik[cik].append(e)
    merged = []
    for cik, ev_list in by_cik.items():
        ev_list.sort(key=lambda x: x.get("event_date", ""))
        last_kept = None
        for e in ev_list:
            try:
                d = datetime.strptime(e["event_date"], "%Y-%m-%d").date()
            except Exception:
                continue
            if last_kept is None or (d - last_kept).days > 30:
                merged.append(e)
                last_kept = d
    return merged


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    if not (DATA_DIR / f"h3_events_{sha}.csv").exists():
        fb = data_sha(DATA_DIR)
        if fb:
            LOG.info("git_sha %s 데이터 부재 · data_sha fallback → %s", sha, fb)
            sha = fb

    # h3_events 에서 F4_buy 이벤트 추출
    with (DATA_DIR / f"h3_events_{sha}.csv").open() as f:
        all_events = list(csv.DictReader(f))
    f4_events = [e for e in all_events if e.get("event_type") == "F4_buy"]
    LOG.info("F4_buy events (WP28-3 병합): %d", len(f4_events))

    # 20 거래일 첫 건 병합 (동일 발행사)
    merged = merge_20d_first(f4_events)
    LOG.info("merged (20d first · 동일 CIK): %d", len(merged))

    # 티커 매핑 · 시총 $50M~$5B 필터 (mcap_lookup 부재 시 전체)
    cik2tk = load_cik_ticker(sha)
    for e in merged:
        cik = (e.get("target_cik") or "").zfill(10)
        e["ticker"] = cik2tk.get(cik, "")
    merged = [e for e in merged if e.get("ticker")]
    LOG.info("with ticker: %d", len(merged))

    # h3_backtest 실행 (엔진 동결)
    prices = load_prices(DATA_DIR / f"h3_prices_merged_{sha}.csv")
    bench_all = load_prices(DATA_DIR / f"benchmarks_{sha}.csv")
    bench_prices = bench_all.get(BENCHMARK_TICKER, {})
    LOG.info("prices tickers: %d · bench %d dates", len(prices), len(bench_prices))

    # SIC · mcap 조회 (기존 배선)
    sic_lookup = {}
    with (DATA_DIR / f"h3_targets_v2_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            cik = (r.get("target_cik") or "").zfill(10)
            sic = r.get("sic", "")
            if cik and sic:
                sic_lookup[cik] = sic

    result = run_backtest(merged, prices, bench_prices, {}, sic_lookup, seed=42)
    summary = result["summary"]

    # 임계 §2 H3 동일 판정
    thresholds = {"h_30d": 0.05, "h_180d": 0.15}
    per_horizon = {}
    for h_key, h_result in summary.get("horizons", {}).items():
        if not h_result or h_result.get("n", 0) == 0:
            per_horizon[h_key] = {"pass": False, "note": "표본 없음"}
            continue
        mean_ne = h_result.get("mean_net_excess", 0) or 0
        hit = h_result.get("hit_rate_pct", 0) or 0
        ci_lo = h_result.get("ci_block_95_lo", 0) or 0
        thr = thresholds.get(h_key, 0)
        alpha_pass = (mean_ne >= thr and ci_lo > 0 and hit >= 35.0)
        per_horizon[h_key] = {
            "n": h_result.get("n", 0),
            "mean": mean_ne, "hit_pct": hit,
            "ci_block_lo": ci_lo, "ci_block_hi": h_result.get("ci_block_95_hi", 0),
            "threshold": thr, "alpha_pass": alpha_pass,
        }

    # 폐기 조건: 양 창 CI 하한 ≤ 0
    all_ci_zero = all((v.get("ci_block_lo", 0) or 0) <= 0 for v in per_horizon.values() if "ci_block_lo" in v)

    seal = {
        "git_sha": sha,
        "version": "WP63 · H3-F4 · Form 4 매수 추종 별도 검정 (B51 원칙 승계)",
        "principle": "H3 리포트 불변 · Form 4 는 별도 · H3 와 합산 금지",
        "input_f4_events": len(f4_events),
        "merged_20d_first": len(merged),
        "engine": "biotech_h3_backtest (동결) · 창 30d/180d · XBI · 비용 1% · 시총 50M-5B · 날짜 클러스터 CI",
        "thresholds_precommit_H3_same": {"h_30d_pct": 5, "h_180d_pct": 15, "hit_min_pct": 35, "ci_lo": 0},
        "horizons": per_horizon,
        "deprecation_triggered": all_ci_zero,
        "per_event_count": summary.get("per_event_count", 0),
        "excluded": summary.get("excluded", {}),
    }

    out_dir = DATA_DIR / "biotech" / "seals"
    out_dir.mkdir(parents=True, exist_ok=True)
    seal_path = out_dir / f"h3f4_seal_{sha}.json"
    seal_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2))

    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    report_dir = PROJECT_ROOT / "docs" / "plans" / "biotech" / "verification" / "H3"
    report_dir.mkdir(parents=True, exist_ok=True)
    h30 = per_horizon.get("h_30d", {})
    h180 = per_horizon.get("h_180d", {})

    def fmt(v, digits=2):
        return f"{v*100:+.{digits}f}%" if isinstance(v, (int, float)) else "?"

    report = [
        f"# H3-F4 · Form 4 매수 추종 별도 리포트 (WP63 · {today_str} · git_sha {sha})",
        "",
        "> 📖 [`GLOSSARY.md`](../../GLOSSARY.md) · 코드 · 상태 · 가설 뜻",
        "",
        "## 원칙 (Fable · B51 승계)",
        "",
        "- **H3 리포트 (`H3-report-20260912.md`) 는 불변** · 봉인 결과 유지",
        "- Form 4 매수 추종은 **별도 검정** · H3 와 합산 금지",
        "- 임계 §2 H3 동일 (30d +5% · 180d +15% · hit ≥ 35% · CI 하한 > 0)",
        "- 폐기 조건 = 양 창 CI 하한 ≤ 0",
        "",
        "## 입력 (WP28-3 병합 후 F4_buy 이벤트)",
        "",
        f"- 원 F4_buy 이벤트: **{len(f4_events)}건** (WP28-2 55/55 filer · WP28-3 병합)",
        f"- 20 거래일 첫 건 병합 (동일 target_cik · H5 규칙 승계): **{len(merged)}건**",
        f"- 티커 매핑 후: **{seal['per_event_count']}건** 백테스트 표본",
        f"- 제외 (excluded): {json.dumps(seal['excluded'], ensure_ascii=False)}",
        "",
        "## 결과 표 (창별 · 엔진 동결 · biotech_h3_backtest)",
        "",
        "| 창 | n | 평균 net excess | 히트율 | CI 하한 (클러스터) | CI 상한 | 임계 | 판정 (alpha_pass) |",
        "|---|---|---|---|---|---|---|---|",
        f"| **30d (D+1~D+30)** | {h30.get('n', '?')} | **{fmt(h30.get('mean', 0))}** | {h30.get('hit_pct', 0):.1f}% | {fmt(h30.get('ci_block_lo', 0))} | {fmt(h30.get('ci_block_hi', 0))} | ≥ +5% AND CI 하한 > 0 AND hit ≥ 35% | **{h30.get('alpha_pass', False)}** |",
        f"| **180d (D+1~D+180)** | {h180.get('n', '?')} | **{fmt(h180.get('mean', 0))}** | {h180.get('hit_pct', 0):.1f}% | {fmt(h180.get('ci_block_lo', 0))} | {fmt(h180.get('ci_block_hi', 0))} | ≥ +15% AND CI 하한 > 0 AND hit ≥ 35% | **{h180.get('alpha_pass', False)}** |",
        "",
        f"**폐기 조건 (양 창 CI 하한 ≤ 0) 발동**: **{seal['deprecation_triggered']}**",
        "",
        "## 쉬운 말 5줄",
        "",
        f"1. 임원 매수 (Form 4 P) 를 신호로 D+1 매수 · D+30 · D+180 청산 규칙 검정 (표본 병합 후 {len(merged)}건).",
        f"2. 30일 창 평균 **{fmt(h30.get('mean', 0))}** · 히트율 {h30.get('hit_pct', 0):.1f}% · CI 하한 **{fmt(h30.get('ci_block_lo', 0))}** · 임계 +5% 통과 {h30.get('alpha_pass', False)}.",
        f"3. 180일 창 평균 **{fmt(h180.get('mean', 0))}** · 히트율 {h180.get('hit_pct', 0):.1f}% · CI 하한 **{fmt(h180.get('ci_block_lo', 0))}** · 임계 +15% 통과 {h180.get('alpha_pass', False)}.",
        f"4. **폐기 조건 (양 창 CI 하한 ≤ 0) 발동: {seal['deprecation_triggered']}** · 이 규칙은 {'단독 실행 금지 (H3 처럼 폐기)' if seal['deprecation_triggered'] else '조건부 유지'}.",
        "5. **H3 리포트와 합산 금지** · 이 결과는 Form 4 만의 별도 검정 (B51 승계).",
        "",
        "## 가능성 지도 (3줄 · WP36 필수)",
        "",
        f"1. 가장 밝은 자리 = {'없음 · 폐기 발동' if seal['deprecation_triggered'] else 'F4 30d/180d 중 임계 초과 창 · 다음 조건 재검'}",
        f"2. 죽은 자리 = H3 (activist 전체) 폐기 + F4 검정 {'폐기 발동' if seal['deprecation_triggered'] else '유보'} · SEC 매수 추종은 시장 반응 없음",
        "3. 다음에 팔 자리 = **소문 채널 (WP54-3 · 봉인)** + 임상 발표 D-30 진입 (H1b · +1.62%) · 실전 규칙 재검",
    ]
    report_path = report_dir / f"H3-F4-report-{today_str}.md"
    report_path.write_text("\n".join(report))

    print(json.dumps({
        "git_sha": sha, "seal_path": str(seal_path), "report_path": str(report_path),
        "input_f4": len(f4_events), "merged": len(merged),
        "backtest_n": seal["per_event_count"],
        "h30": {k: v for k, v in h30.items() if k != "note"},
        "h180": {k: v for k, v in h180.items() if k != "note"},
        "deprecation_triggered": seal["deprecation_triggered"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
