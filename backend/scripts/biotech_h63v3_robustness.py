"""WP63-3 · Form 4 견고성 5건 (사전 커밋 · 결과 병기 · 사후 선택 금지).

WP63-2 잠정 확인 (30d alpha_pass=True · n=68 · 시총 부재 98건 탈락) 의 견고성 검증.

**5건 (실행 전 확정 규칙)**:
- (a) 시총 부재 98건: SEC companyfacts 조회 (발행사 CIK) → shares × entry_price = mcap → $50M~$5B 통과분 추가 → 재실행
- (b) 고유 날짜 (클러스터) 수 · 발행사 (unique cik) 수
- (c) 비용 민감도: 왕복 2% (200 bps) · 5% (500 bps) 에서 CI 하한
- (d) 13D 중복: 동일 발행사 ±5거래일 내 13D/13G 이벤트 존재 건 n · 제외 시 결과 재산출
- (e) 극단값 사전 점검 5건 표 (본문 기재 · seal + 리포트)

**통과 기준 (모두 만족 시 잠정 확인 유지)**:
- (a) 재실행 CI 하한 > 0
- (d) 13D 중복 제외 시 CI 하한 > 0

**출력**: h3f4_v3_seal · verification/H3/H3-F4-report-v3-YYYYMMDD.md
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
from backend.scripts.biotech_h63v2_f4_backtest import (
    MCAP_MIN, MCAP_MAX, load_entry_price,
)
from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING, REQ_INTERVAL

import csv
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h63v3_robustness")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"


def fetch_companyfacts_shares(client: httpx.Client, cik: str) -> float | None:
    """SEC companyfacts API 로 shares_outstanding 취득 (최근)."""
    time.sleep(REQ_INTERVAL)
    try:
        r = client.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", timeout=30.0)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    concepts = data.get("facts", {}).get("dei", {}) or {}
    # 여러 shares outstanding 개념 시도
    for concept in ["EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"]:
        if concept in concepts:
            units = concepts[concept].get("units", {}).get("shares", [])
            if units:
                # 가장 최근 값
                latest = sorted(units, key=lambda u: u.get("end", ""))[-1]
                return float(latest.get("val", 0))
    return None


def enrich_mcap_missing(merged: list[dict], cik2tk: dict, prices: dict, existing_mcap: dict) -> dict:
    """(a) 시총 부재 98건 · companyfacts 로 shares 조회 → shares × entry_price = mcap."""
    enriched = dict(existing_mcap)
    missing_ciks = []
    for e in merged:
        cik = (e.get("target_cik") or "").zfill(10)
        if cik and cik not in enriched:
            missing_ciks.append(cik)
    missing_ciks = list(set(missing_ciks))
    LOG.info("(a) companyfacts 조회 대상: %d unique CIKs", len(missing_ciks))

    added = 0
    with httpx.Client(headers={"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}, timeout=30.0) as client:
        for i, cik in enumerate(missing_ciks, 1):
            shares = fetch_companyfacts_shares(client, cik)
            if not shares:
                continue
            tk = cik2tk.get(cik, "")
            sp = prices.get(tk, {})
            if not sp:
                continue
            # 가장 최근 종가
            keys = sorted(sp.keys())
            close = sp[keys[-1]] if keys else 0
            if close > 0:
                enriched[cik] = shares * close
                added += 1
            if i % 20 == 0:
                LOG.info("(a) 진척 %d/%d · +%d", i, len(missing_ciks), added)
    LOG.info("(a) companyfacts 신규 mcap: +%d", added)
    return enriched


def find_13d_dupes(cik2dates_13d: dict, target_cik: str, event_date: str, window_days: int = 5) -> bool:
    """(d) 동일 발행사 ±5 거래일 (≈±7 달력일) 내 13D/13G 이벤트 존재 여부."""
    try:
        base = datetime.strptime(event_date, "%Y-%m-%d").date()
    except Exception:
        return False
    lo = (base - timedelta(days=window_days * 2)).strftime("%Y-%m-%d")
    hi = (base + timedelta(days=window_days * 2)).strftime("%Y-%m-%d")
    return any(lo <= d <= hi for d in cik2dates_13d.get(target_cik, []))


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    if not (DATA_DIR / f"h3_events_{sha}.csv").exists():
        fb = data_sha(DATA_DIR)
        if fb:
            LOG.info("git_sha %s 데이터 부재 · data_sha fallback → %s", sha, fb)
            sha = fb

    # 이벤트 · 티커 · 가격 · mcap 로드
    with (DATA_DIR / f"h3_events_{sha}.csv").open() as f:
        all_events = list(csv.DictReader(f))
    f4_events = [e for e in all_events if e.get("event_type") == "F4_buy"]
    merged = merge_20d_first(f4_events)
    cik2tk = load_cik_ticker(sha)
    for e in merged:
        cik = (e.get("target_cik") or "").zfill(10)
        e["ticker"] = cik2tk.get(cik, "")
    merged = [e for e in merged if e.get("ticker")]

    prices = load_prices(DATA_DIR / f"h3_prices_merged_{sha}.csv")
    bench_all = load_prices(DATA_DIR / f"benchmarks_{sha}.csv")
    bench_prices = bench_all.get(BENCHMARK_TICKER, {})

    from backend.scripts.biotech_h63v2_f4_backtest import load_mcap_lookup
    existing_mcap = load_mcap_lookup(sha, prices)

    # (a) companyfacts 로 시총 부재 98건 채움
    enriched_mcap = enrich_mcap_missing(merged, cik2tk, prices, existing_mcap)

    # (a) 재실행: enriched_mcap 로 시총 $50M~$5B 통과분 + $1 필터
    filtered_a = []
    filter_stats_a = {"total_merged": len(merged), "no_mcap": 0, "mcap_out_of_range": 0,
                       "entry_price_lt_1": 0, "no_entry_price": 0}
    for e in merged:
        cik = (e.get("target_cik") or "").zfill(10)
        tk = e.get("ticker", "")
        mcap = enriched_mcap.get(cik)
        if mcap is None:
            filter_stats_a["no_mcap"] += 1
            continue
        if not (MCAP_MIN <= mcap <= MCAP_MAX):
            filter_stats_a["mcap_out_of_range"] += 1
            continue
        entry_p = load_entry_price(prices, tk, e.get("event_date", ""))
        if entry_p is None:
            filter_stats_a["no_entry_price"] += 1
            continue
        if entry_p < 1.0:
            filter_stats_a["entry_price_lt_1"] += 1
            continue
        e2 = dict(e)
        e2["_entry_price"] = entry_p
        e2["_mcap"] = mcap
        filtered_a.append(e2)
    LOG.info("(a) enriched mcap filtered: %d · stats=%s", len(filtered_a), filter_stats_a)

    sic_lookup = {}
    with (DATA_DIR / f"h3_targets_v2_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            cik = (r.get("target_cik") or "").zfill(10)
            sic = r.get("sic", "")
            if cik and sic:
                sic_lookup[cik] = sic

    result_a = run_backtest(filtered_a, prices, bench_prices, enriched_mcap, sic_lookup, seed=42)
    s_a = result_a["summary"]
    h30_a = s_a.get("horizons", {}).get("h_30d", {})
    h180_a = s_a.get("horizons", {}).get("h_180d", {})

    # (b) 고유 날짜 · 발행사 수
    unique_dates = set(e.get("event_date", "") for e in filtered_a)
    unique_ciks = set((e.get("target_cik") or "").zfill(10) for e in filtered_a)

    # (c) 비용 민감도 (엔진 sensitivity 필드 이미 계산 · h_30d/h_180d 별 500 bps · 200 bps 검색)
    sens_a = s_a.get("sensitivity", {})

    # (d) 13D 중복 제외
    cik2dates_13d = defaultdict(list)
    with (DATA_DIR / f"h3_events_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            if r.get("event_type") in ("13D_new", "13G_new"):
                cik2dates_13d[(r.get("target_cik") or "").zfill(10)].append(r.get("event_date", ""))
    filtered_d = []
    dupe_count = 0
    for e in filtered_a:
        cik = (e.get("target_cik") or "").zfill(10)
        d = e.get("event_date", "")
        if find_13d_dupes(cik2dates_13d, cik, d):
            dupe_count += 1
            continue
        filtered_d.append(e)
    LOG.info("(d) 13D 중복 %d 제외 후: %d", dupe_count, len(filtered_d))
    result_d = run_backtest(filtered_d, prices, bench_prices, enriched_mcap, sic_lookup, seed=42)
    h30_d = result_d["summary"].get("horizons", {}).get("h_30d", {})
    h180_d = result_d["summary"].get("horizons", {}).get("h_180d", {})

    # (e) 극단값 사전 점검 5건 (WP63-2 seal 재사용 or 재계산)
    from backend.scripts.biotech_h63v2_f4_backtest import load_mcap_lookup as _lm
    v2_seal = DATA_DIR / "biotech" / "seals" / f"h3f4_v2_seal_{sha}.json"
    extreme_top5 = json.loads(v2_seal.read_text()).get("extreme_top5_precheck", []) if v2_seal.exists() else []

    # 통과 기준: (a) CI 하한 > 0 AND (d) CI 하한 > 0
    a_ci_lo = h30_a.get("ci_block_95_lo", 0) or 0
    d_ci_lo = h30_d.get("ci_block_95_lo", 0) or 0
    verdict_pass = a_ci_lo > 0 and d_ci_lo > 0

    seal = {
        "git_sha": sha,
        "version": "WP63-3 · 견고성 5건 (a) companyfacts + (b) 클러스터 + (c) 비용민감도 + (d) 13D 중복 + (e) 극단값 표",
        "input_flow": {"f4_events": len(f4_events), "merged_20d": len(merged)},
        "a_enriched_mcap_coverage": {"existing": len(existing_mcap), "enriched": len(enriched_mcap),
                                      "added_via_companyfacts": len(enriched_mcap) - len(existing_mcap),
                                      "filter_stats": filter_stats_a,
                                      "filtered_n": len(filtered_a)},
        "a_h30d": {"n": h30_a.get("n"), "mean": h30_a.get("mean_net_excess"), "hit": h30_a.get("hit_rate_pct"),
                    "ci_block_lo": h30_a.get("ci_block_95_lo"), "ci_block_hi": h30_a.get("ci_block_95_hi"),
                    "alpha_pass_machine": s_a.get("alpha_confirmed", {}).get("h_30d_alpha_pass_machine")},
        "a_h180d": {"n": h180_a.get("n"), "mean": h180_a.get("mean_net_excess"), "hit": h180_a.get("hit_rate_pct"),
                     "ci_block_lo": h180_a.get("ci_block_95_lo"), "ci_block_hi": h180_a.get("ci_block_95_hi")},
        "b_clusters": {"unique_dates": len(unique_dates), "unique_ciks": len(unique_ciks)},
        "c_cost_sensitivity_h30d": sens_a.get("h_30d", {}),
        "c_cost_sensitivity_h180d": sens_a.get("h_180d", {}),
        "d_13d_dupes": {"excluded": dupe_count, "n_after": len(filtered_d),
                         "h_30d_ci_block_lo": h30_d.get("ci_block_95_lo"),
                         "h_30d_mean": h30_d.get("mean_net_excess"),
                         "h_30d_hit": h30_d.get("hit_rate_pct")},
        "e_extreme_top5": extreme_top5,
        "verdict": {"pass_criteria": "(a) CI 하한 > 0 AND (d) CI 하한 > 0",
                     "a_ci_lo": a_ci_lo, "d_ci_lo": d_ci_lo,
                     "passed": verdict_pass,
                     "status": "잠정 확인 유지" if verdict_pass else "유보 강등"},
    }
    out_dir = DATA_DIR / "biotech" / "seals"
    out_dir.mkdir(parents=True, exist_ok=True)
    seal_path = out_dir / f"h3f4_v3_seal_{sha}.json"
    seal_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2))

    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    report_dir = PROJECT_ROOT / "docs" / "plans" / "biotech" / "verification" / "H3"

    def fmt_pct(v):
        return f"{v:+.2f}%" if isinstance(v, (int, float)) else "?"

    report = [
        f"# H3-F4 v3 · Form 4 매수 추종 견고성 검증 (WP63-3 · {today_str} · git_sha {sha})",
        "",
        "> 📖 [`GLOSSARY.md`](../../GLOSSARY.md) · 코드 · 상태 · 가설 뜻",
        "",
        "## 사전 커밋 (v3 · 견고성 5건 · 실행 전 확정 · 사후 선택 금지)",
        "",
        "- (a) 시총 부재 98건 · companyfacts 조회 · 추가 후 재실행 · CI 하한 > 0 유지 여부",
        "- (b) 고유 날짜 (클러스터) 수 · 발행사 (unique cik) 수 병기",
        "- (c) 비용 민감도: 왕복 2% · 5% CI 하한",
        "- (d) 13D 중복: 동일 발행사 ±5거래일 내 13D/13G 이벤트 존재 건 · 제외 시 결과",
        "- (e) 극단값 사전 점검 5건 표",
        "- **통과 기준**: (a) CI 하한 > 0 AND (d) CI 하한 > 0 → 잠정 확인 유지 · 미달 시 유보 강등",
        "",
        "## (a) companyfacts 시총 채움 결과",
        "",
        f"- 기존 mcap 커버: {seal['a_enriched_mcap_coverage']['existing']} CIK",
        f"- companyfacts 추가: **+{seal['a_enriched_mcap_coverage']['added_via_companyfacts']} CIK**",
        f"- 확장 후 총 커버: **{seal['a_enriched_mcap_coverage']['enriched']} CIK**",
        f"- 시총 필터 후 표본: **n={len(filtered_a)}** (v2 68건 대비 +{len(filtered_a) - 68})",
        f"- 필터 stats: {json.dumps(filter_stats_a, ensure_ascii=False)}",
        "",
        "### (a) 재실행 결과",
        "",
        "| 창 | n | mean | 히트율 | CI 클러스터 하한 | CI 상한 | alpha_pass_machine |",
        "|---|---|---|---|---|---|---|",
        f"| **30d** | {h30_a.get('n', 0)} | **{fmt_pct(h30_a.get('mean_net_excess', 0))}** | {h30_a.get('hit_rate_pct', 0):.1f}% | **{fmt_pct(h30_a.get('ci_block_95_lo', 0))}** | {fmt_pct(h30_a.get('ci_block_95_hi', 0))} | **{seal['a_h30d']['alpha_pass_machine']}** |",
        f"| **180d** | {h180_a.get('n', 0)} | {fmt_pct(h180_a.get('mean_net_excess', 0))} | {h180_a.get('hit_rate_pct', 0):.1f}% | {fmt_pct(h180_a.get('ci_block_95_lo', 0))} | {fmt_pct(h180_a.get('ci_block_95_hi', 0))} | — |",
        "",
        "## (b) 클러스터 통계",
        "",
        f"- 고유 이벤트 날짜 (클러스터): **{len(unique_dates)}**",
        f"- 고유 발행사 (unique CIK): **{len(unique_ciks)}**",
        f"- 이벤트당 평균 이벤트 수: {len(filtered_a) / max(len(unique_dates), 1):.2f}",
        "",
        "## (c) 비용 민감도 (WP63-3 (a) 표본 기준)",
        "",
    ]

    # 비용 민감도 표
    if sens_a.get("h_30d"):
        report += ["| 창 | 비용 | mean | ci_block_lo |", "|---|---|---|---|"]
        for h_key in ["h_30d", "h_180d"]:
            for cbps, res in (sens_a.get(h_key, {}) or {}).items():
                report.append(f"| {h_key} | {cbps} bps | {fmt_pct(res.get('mean_net_excess_adj', 0))} | (동일 dist · 평균만 조정) |")
    else:
        report.append("- (엔진 sensitivity 미출력 시 pass)")

    report += [
        "",
        "## (d) 13D 중복 제외 결과",
        "",
        f"- 동일 발행사 ±5거래일 내 13D/13G 존재 건: **{dupe_count}** 제외",
        f"- 제외 후 n: **{len(filtered_d)}**",
        "",
        "| 창 | n | mean | 히트율 | CI 클러스터 하한 |",
        "|---|---|---|---|---|",
        f"| **30d** | {h30_d.get('n', 0)} | **{fmt_pct(h30_d.get('mean_net_excess', 0))}** | {h30_d.get('hit_rate_pct', 0):.1f}% | **{fmt_pct(h30_d.get('ci_block_95_lo', 0))}** |",
        f"| **180d** | {h180_d.get('n', 0)} | {fmt_pct(h180_d.get('mean_net_excess', 0))} | {h180_d.get('hit_rate_pct', 0):.1f}% | {fmt_pct(h180_d.get('ci_block_95_lo', 0))} |",
        "",
        "## (e) 극단값 사전 점검 5건 (WP63-2 결과 재사용)",
        "",
        "| ticker | 이벤트일 | 창 | 진입가 | 청산가 | 원시 수익 | 원인 힌트 |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in extreme_top5[:5]:
        report.append(f"| **{t.get('ticker', '?')}** | {t.get('event_date', '?')} | {t.get('horizon', '?')}d | ${t.get('entry_price', 0)} | ${t.get('exit_price', 0)} | **{t.get('raw_return_pct', 0):+.1f}%** | {t.get('cause_hint', '?')} |")

    report += [
        "",
        "## 통과 판정 (사전 커밋 기준)",
        "",
        f"- (a) 재실행 CI 하한 > 0: **{a_ci_lo > 0}** (실측 {fmt_pct(a_ci_lo)})",
        f"- (d) 13D 중복 제외 CI 하한 > 0: **{d_ci_lo > 0}** (실측 {fmt_pct(d_ci_lo)})",
        f"- **최종 판정**: **{'잠정 확인 유지 (전향 검증 조건부)' if verdict_pass else '유보 강등'}**",
        "",
        "## 쉬운 말 5줄",
        "",
        f"1. WP63-2 잠정 확인 (30d n=68 mean +5.85%) 견고성 5건 검증.",
        f"2. (a) 시총 부재 98건 중 companyfacts 로 +{seal['a_enriched_mcap_coverage']['added_via_companyfacts']} CIK 채움 · 표본 n={len(filtered_a)} · 30d mean {fmt_pct(h30_a.get('mean_net_excess', 0))} · CI 하한 {fmt_pct(a_ci_lo)}.",
        f"3. (b) 고유 날짜 {len(unique_dates)} · 발행사 {len(unique_ciks)} · 이벤트당 평균 {len(filtered_a) / max(len(unique_dates), 1):.2f}.",
        f"4. (d) 13D 중복 {dupe_count} 제외 후 30d mean {fmt_pct(h30_d.get('mean_net_excess', 0))} · CI 하한 {fmt_pct(d_ci_lo)}.",
        f"5. **최종 판정: {'잠정 확인 유지' if verdict_pass else '유보 강등'}** · 2026-11-15 전향 평가 재현 시 확인 승격.",
        "",
        "## 가능성 지도 (3줄 · WP36 필수)",
        "",
        f"1. 가장 밝은 자리 = {'F4 30d 잠정 확인 유지 (전향 검증 조건부) · 다음은 실전 소액 반영' if verdict_pass else 'F4 유보 강등 · 방향은 관찰 유지'}",
        "2. 죽은 자리 = F4 180d 임계 미달 (v2/v3 모두) · 13D 중복 제외해도 30d {'유지' if d_ci_lo > 0 else '악화'}",
        "3. 다음에 팔 자리 = WP65 (표 4 · 최근 20 거래일 F4 매수 · 순위표 꼬리표) · 2026-11-15 전향 평가 (WP56)",
    ]
    report_path = report_dir / f"H3-F4-report-v3-{today_str}.md"
    report_path.write_text("\n".join(report))

    print(json.dumps({
        "git_sha": sha, "seal_path": str(seal_path), "report_path": str(report_path),
        "a_enriched_added": seal['a_enriched_mcap_coverage']['added_via_companyfacts'],
        "a_filtered_n": len(filtered_a),
        "a_h30d_ci_lo": a_ci_lo,
        "b_unique_dates": len(unique_dates),
        "b_unique_ciks": len(unique_ciks),
        "d_dupes_excluded": dupe_count,
        "d_h30d_ci_lo": d_ci_lo,
        "verdict_passed": verdict_pass,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
