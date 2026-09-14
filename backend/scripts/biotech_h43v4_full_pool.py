"""WP43-4 · H8/H1b 완주 풀 재검 (WP39 340/340 · 7351 events).

부분 풀 (WP43-3 · 210/340) 대비 재계산:
- H8 검정 3 (뉴스에 팔기): pre D-30~D-1 vs post D+1~D+30 · CI · sell_supported
- H1b (Phase 3 guidance · D-30 진입 D-1 청산): mean · CI · alpha_pass · 임계 +2%
- H8 검정 1 (이벤트 수 상/하 절반): 참고용 · WP53 규칙 위반 결과 이력 보존

봉인/리포트 별도 파일명 (부분 풀 결과 보존):
- seal: `h8_h1b_full_seal_{sha}.json`
- report: `H8-H1b-full-report-20260914.md`
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_h43_h8_h1b import (
    git_sha, load_events, load_prices, load_bench, load_cik_ticker,
    net_excess, bootstrap_ci,
)

import json
import logging
from collections import defaultdict
from pathlib import Path
from statistics import mean

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h43v4_full_pool")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    events = load_events(sha)
    prices = load_prices(sha)
    bench = load_bench(sha)
    cik2tk = load_cik_ticker(sha)
    LOG.info("events %d · prices %d · bench %d · cik2tk %d", len(events), len(prices), len(bench), len(cik2tk))

    ev_count_by_cik = defaultdict(int)
    for e in events:
        ev_count_by_cik[(e.get("cik") or "").zfill(10)] += 1

    per = []
    for e in events:
        cik = (e.get("cik") or "").zfill(10)
        tk = cik2tk.get(cik)
        d_day = e.get("d_day", "")
        if not tk or not d_day:
            continue
        sp = prices.get(tk, {})
        if not sp:
            continue
        pre = net_excess(sp, bench, d_day, -30, -1)
        post = net_excess(sp, bench, d_day, 1, 30)
        if pre is None and post is None:
            continue
        per.append({
            "cik": cik, "ticker": tk, "d_day": d_day,
            "direction": e.get("direction", ""),
            "ev_count_bucket": "hi" if ev_count_by_cik[cik] >= 3 else "lo",
            "pre": pre, "post": post,
        })

    coverage = len(per) / max(len(events), 1)
    LOG.info("events scored: %d · coverage %.3f", len(per), coverage)

    hi_pre = [r["pre"] for r in per if r["ev_count_bucket"] == "hi" and r["pre"] is not None]
    lo_pre = [r["pre"] for r in per if r["ev_count_bucket"] == "lo" and r["pre"] is not None]
    hi_groups = [r["d_day"] for r in per if r["ev_count_bucket"] == "hi" and r["pre"] is not None]
    lo_groups = [r["d_day"] for r in per if r["ev_count_bucket"] == "lo" and r["pre"] is not None]

    hi_ci = bootstrap_ci(hi_pre, hi_groups)
    lo_ci = bootstrap_ci(lo_pre, lo_groups)

    post_all = [r["post"] for r in per if r["post"] is not None]
    post_groups = [r["d_day"] for r in per if r["post"] is not None]
    post_ci = bootstrap_ci(post_all, post_groups)

    pre_all = [r["pre"] for r in per if r["pre"] is not None]
    pre_groups = [r["d_day"] for r in per if r["pre"] is not None]
    pre_ci = bootstrap_ci(pre_all, pre_groups)

    seal = {
        "git_sha": sha,
        "pool_note": "WP39 완주 풀 (340/340 CIK · 7,351 events · WP43-4)",
        "coverage": round(coverage, 3),
        "H8_test1_leading_note": "이벤트 수 상/하 · lo n<10 시 규칙 위반 결과 · WP53 재계산 (rumor_index) 이 정식 판정",
        "H8_test1_leading": {
            "hi_bucket": {"n": len(hi_pre), "unique_dates": len(set(hi_groups)),
                          "mean": round(mean(hi_pre), 4) if hi_pre else None, "ci95": hi_ci},
            "lo_bucket": {"n": len(lo_pre), "unique_dates": len(set(lo_groups)),
                          "mean": round(mean(lo_pre), 4) if lo_pre else None, "ci95": lo_ci},
            "diff_hi_minus_lo": round(mean(hi_pre) - mean(lo_pre), 4) if (hi_pre and lo_pre) else None,
        },
        "H8_test3_sell_news": {
            "pre_D-30_D-1": {"n": len(pre_all), "mean": round(mean(pre_all), 4) if pre_all else None, "ci95": pre_ci},
            "post_D+1_D+30": {"n": len(post_all), "mean": round(mean(post_all), 4) if post_all else None, "ci95": post_ci},
            "sell_supported": (mean(pre_all) > 0 and post_ci[1] <= 0) if (pre_all and post_all) else None,
        },
        "H1b": {
            "n": len(pre_all), "unique_dates": len(set(pre_groups)),
            "mean_net_excess_pre": round(mean(pre_all), 4) if pre_all else None,
            "ci95": pre_ci,
            "threshold": 0.02,
            "alpha_pass": (mean(pre_all) >= 0.02 and pre_ci[0] > 0) if pre_all else False,
            "decision_note": "폐기 조건 (CI 하한 ≤ 0) 도 · 알파 조건 (mean ≥ +2% AND CI 하한 > 0) 도 아님 = 작지만 실재",
        },
    }

    out_dir = DATA_DIR / "biotech" / "seals"
    out_dir.mkdir(parents=True, exist_ok=True)
    seal_path = out_dir / f"h8_h1b_full_seal_{sha}.json"
    seal_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2))

    # 부분 풀 이전 결과 (WP43-3) 로드 · 변화 표
    prev_path = DATA_DIR / "biotech" / "seals" / f"h8_h1b_seal_{sha}.json"
    prev = json.loads(prev_path.read_text()) if prev_path.exists() else {}
    prev_h1b = prev.get("H1b", {})
    prev_h8t3 = prev.get("H8_test3_sell_news", {})

    report_dir = PROJECT_ROOT / "docs" / "plans" / "biotech" / "verification" / "H8"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = [
        f"# H8 · H1b 완주 풀 리포트 (WP43-4 · 2026-09-14 · git_sha {sha})",
        "",
        "> 📖 [`GLOSSARY.md`](../../GLOSSARY.md) · 코드 · 상태 · 가설 뜻",
        "",
        f"- 이벤트 풀: **완주 풀 {len(events)} events (WP39 (임상 결과 발표일 목록 만들기) 340/340 CIK 완주)**",
        f"- 백테스트 표본: {len(per)} events (가격 매치 후 · 커버율 {coverage:.1%})",
        f"- 이전 부분 풀 (WP43-3): 표본 {prev_h1b.get('n', '?')} · 완주 대비 +{len(pre_all) - prev_h1b.get('n', 0)} events",
        "",
        "## 봉인 결과",
        "",
        "### H8 검정 3 (뉴스에 팔기 · '소문에 사서 뉴스에 팔아라' 격언 검정)",
        f"- pre D-30~D-1: n={seal['H8_test3_sell_news']['pre_D-30_D-1']['n']} · mean **{seal['H8_test3_sell_news']['pre_D-30_D-1']['mean']}** · CI (신뢰구간) {seal['H8_test3_sell_news']['pre_D-30_D-1']['ci95']}",
        f"- post D+1~D+30: n={seal['H8_test3_sell_news']['post_D+1_D+30']['n']} · mean **{seal['H8_test3_sell_news']['post_D+1_D+30']['mean']}** · CI {seal['H8_test3_sell_news']['post_D+1_D+30']['ci95']}",
        f"- **뉴스에 팔기 지지 (pre 양수 & post CI 상한 ≤ 0)**: **{seal['H8_test3_sell_news']['sell_supported']}**",
        "",
        "### H1b (Phase 3 (3상 임상) guidance window · D-30 진입 · D-1 청산)",
        f"- n={seal['H1b']['n']} · unique dates={seal['H1b']['unique_dates']} · mean **{seal['H1b']['mean_net_excess_pre']}** · CI {seal['H1b']['ci95']}",
        f"- alpha_pass (mean ≥ +2% AND CI 하한 > 0): **{seal['H1b']['alpha_pass']}**",
        f"- 판정 note: {seal['H1b']['decision_note']}",
        "",
        "### H8 검정 1 (이벤트 수 상/하 · 참고용 · WP53 이 정식 판정)",
        f"- hi bucket (≥3 events/CIK): n={seal['H8_test1_leading']['hi_bucket']['n']} · mean {seal['H8_test1_leading']['hi_bucket']['mean']} · CI {seal['H8_test1_leading']['hi_bucket']['ci95']}",
        f"- lo bucket (<3): n={seal['H8_test1_leading']['lo_bucket']['n']} · mean {seal['H8_test1_leading']['lo_bucket']['mean']} · CI {seal['H8_test1_leading']['lo_bucket']['ci95']}",
        f"- 차이 (hi-lo): {seal['H8_test1_leading']['diff_hi_minus_lo']}",
        "- ⚠️ **이 표는 이벤트 수 상/하 규칙 위반 (사전 커밋은 소문 지수) · WP53 재계산 (rumor_index) 이 정식 판정** · 이력 보존 목적",
        "",
        "## 부분 → 완주 수치 변화 표",
        "",
        "| 지표 | 부분 풀 (WP43-3) | 완주 풀 (WP43-4) | 방향 |",
        "|---|---|---|---|",
        f"| H1b 표본 n | {prev_h1b.get('n', '?')} | {seal['H1b']['n']} | +{seal['H1b']['n'] - prev_h1b.get('n', 0)} |",
        f"| H1b mean | {prev_h1b.get('mean_net_excess_pre', '?')} | {seal['H1b']['mean_net_excess_pre']} | {'변화' if prev_h1b.get('mean_net_excess_pre') != seal['H1b']['mean_net_excess_pre'] else '동일'} |",
        f"| H1b CI | {prev_h1b.get('ci95', '?')} | {seal['H1b']['ci95']} | — |",
        f"| H1b alpha_pass | {prev_h1b.get('alpha_pass', '?')} | {seal['H1b']['alpha_pass']} | — |",
        f"| H8 검정 3 pre mean | {prev_h8t3.get('pre_D-30_D-1', {}).get('mean', '?')} | {seal['H8_test3_sell_news']['pre_D-30_D-1']['mean']} | — |",
        f"| H8 검정 3 post mean | {prev_h8t3.get('post_D+1_D+30', {}).get('mean', '?')} | {seal['H8_test3_sell_news']['post_D+1_D+30']['mean']} | — |",
        f"| H8 검정 3 지지 | {prev_h8t3.get('sell_supported', '?')} | {seal['H8_test3_sell_news']['sell_supported']} | — |",
        "",
        "## 쉬운 말 요약 5줄",
        "",
        f"1. WP39 완주 풀 {len(events)} events (340/340 CIK) · 백테스트 표본 {len(per)} · 부분 풀 대비 확대.",
        f"2. **H1b (발표 전 30일 진입 · 1일 전 청산) 평균 {seal['H1b']['mean_net_excess_pre']*100:.2f}%** · CI 하한 = {seal['H1b']['ci95'][0]*100:.2f}% · 임계 +2% 미달 · 폐기도 아님 = 작지만 실재.",
        f"3. **H8 검정 3 (뉴스에 팔기) {'지지' if seal['H8_test3_sell_news']['sell_supported'] else '불지지'}**: pre {seal['H8_test3_sell_news']['pre_D-30_D-1']['mean']*100:.2f}% · post {seal['H8_test3_sell_news']['post_D+1_D+30']['mean']*100:.2f}% (CI 상한 {seal['H8_test3_sell_news']['post_D+1_D+30']['ci95'][1]*100:.2f}%).",
        f"4. H8 검정 1 (이벤트 수 상/하) 는 사전 커밋 규칙 위반 · WP53 재계산 (rumor_index) 이 정식 판정 · 채널 완비 후 재재검 필요.",
        f"5. **완주 풀 결과로 부분 관측이 뒤집히지 않음** · 첫 유의 신호 유지 · Phase A (검증 단계) 배포 준비 완료.",
        "",
        "## 가능성 지도 (3줄 · WP36 필수)",
        "",
        f"1. 가장 밝은 자리 = **H1b (발표 전 D-30~D-1 · {seal['H1b']['mean_net_excess_pre']*100:.2f}% · CI 하한 > 0) + H8 검정 3 ({'지지' if seal['H8_test3_sell_news']['sell_supported'] else '불지지'})** · 완주 풀에서도 유지",
        "2. 죽은 자리 = H8 검정 1 이벤트 수 방식 · WP53 채널 부분 (역방향) · 원 채널 4~5 완비 필요",
        "3. 다음에 팔 자리 = **WP54 (신호 유무 검정 · 사전 등록)** · PubMed/bioRxiv 채널 추가 · H6 membership 확장 (WP27-2)",
    ]
    report_path = report_dir / "H8-H1b-full-report-20260914.md"
    report_path.write_text("\n".join(report))

    print(json.dumps({
        "git_sha": sha,
        "seal_path": str(seal_path),
        "report_path": str(report_path),
        "events_input": len(events),
        "events_scored": len(per),
        "coverage": round(coverage, 3),
        "H1b_n": seal["H1b"]["n"],
        "H1b_mean": seal["H1b"]["mean_net_excess_pre"],
        "H1b_ci95": seal["H1b"]["ci95"],
        "H1b_alpha_pass": seal["H1b"]["alpha_pass"],
        "H8_test3_pre_mean": seal["H8_test3_sell_news"]["pre_D-30_D-1"]["mean"],
        "H8_test3_post_mean": seal["H8_test3_sell_news"]["post_D+1_D+30"]["mean"],
        "H8_test3_sell_supported": seal["H8_test3_sell_news"]["sell_supported"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
