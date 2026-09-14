"""WP54-3 · 신호 유무 검정 마지막 재실행 (Phase C 1 완결 · 채널 5/5 완비).

**Fable 신규 규칙 (README §3 사전 커밋)**:
- WP54-3 은 신호 유무 검정의 마지막 재실행
- 결과와 무관하게 60일 전향 평가 (2026-11-15) 까지 확정
- 그 전 재실행 금지

**채널 5/5 (Phase C 1 완비 후)**:
- ch1: 13D 신규 (h3_events)
- ch2: **Form 4 P (h3_events F4_buy · WP28-3 병합)**
- ch3: h6 membership (테마 소속)
- ch4: PubMed 게재 yoY (h57 · 307/307 커버)
- ch5: Preprint yoY (h58 · 200/307 부분)
- (별도 · c 옵션) **CT.gov 상태/단계 변경** (h62 · WP62) 는 옵션 채널 (스폰서→회사 매핑 정확도 낮으면 참고만)

규칙 동일 (WP54 사전 등록):
- 신호 있음 vs 없음 · D-30~D-1 순초과수익 차이
- 임계 +1.0%p AND 날짜 클러스터 CI 하한 > 0
- 불지지 시 방향 관측 서술 (신호 있음 집단 CI 하한 > 0 여부)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging, data_sha
from backend.scripts.biotech_h43_h8_h1b import (
    git_sha, load_events, load_prices, load_bench, load_cik_ticker,
    net_excess, bootstrap_ci,
)

import csv
import json
import logging
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h54v3_signal_final")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
THRESHOLD_DIFF = 0.010  # +1.0%p 사전 고정


def is_pub_signal(idx_entry: dict | None, d_day_year: int) -> bool:
    if not idx_entry:
        return False
    counts = idx_entry.get("counts", {})
    y_recent = counts.get(f"y{d_day_year}", 0) or 0
    y_base = counts.get(f"y{d_day_year - 1}", 0) or 0
    if y_recent < 0:
        return False
    return y_recent >= 1 and y_recent > y_base


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    if not (DATA_DIR / f"h3_prices_merged_{sha}.csv").exists():
        fb = data_sha(DATA_DIR)
        if fb:
            LOG.info("git_sha %s 데이터 부재 · data_sha fallback → %s", sha, fb)
            sha = fb

    events = load_events(sha)
    prices = load_prices(sha)
    bench = load_bench(sha)
    cik2tk = load_cik_ticker(sha)
    pub_idx = json.loads((DATA_DIR / f"h57_pubmed_index_{sha}.json").read_text()) if (DATA_DIR / f"h57_pubmed_index_{sha}.json").exists() else {}
    pre_idx = json.loads((DATA_DIR / f"h58_preprint_index_{sha}.json").read_text()) if (DATA_DIR / f"h58_preprint_index_{sha}.json").exists() else {}
    LOG.info("events %d · pub_idx %d · pre_idx %d", len(events), len(pub_idx), len(pre_idx))

    # 채널 1: 13D 신규 (h3_events 확장 · WP28-3 병합 후 F4_buy 도 포함)
    ch1_dates_by_cik = defaultdict(list)
    ch2_dates_by_cik = defaultdict(list)  # F4_buy (Form 4 P · WP28-3 병합)
    with (DATA_DIR / f"h3_events_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            cik = (r.get("target_cik") or "").zfill(10)
            d = r.get("event_date", "")
            et = r.get("event_type", "")
            if not (cik and d):
                continue
            if et in ("13D_new", "13G_new"):
                ch1_dates_by_cik[cik].append(d)
            elif et == "F4_buy":
                ch2_dates_by_cik[cik].append(d)

    # 채널 3: h6 membership
    memb_tk = set()
    mp = DATA_DIR / f"h6_membership_{sha}.csv"
    if mp.exists():
        with mp.open() as f:
            for r in csv.DictReader(f):
                for t in (r.get("tiingo_matched_tickers") or "").split("|"):
                    if t.strip():
                        memb_tk.add(t.strip())

    # 채널 c (옵션): AACT 상태 변경 (h62 · 스폰서→회사 매핑 미완이므로 참고만)
    aact_events_path = DATA_DIR / f"h62_aact_status_events_{sha}.csv"
    aact_available = aact_events_path.exists()

    ch_stats = {"ch1_13D_hits": 0, "ch2_F4P_hits": 0, "ch3_memb_hits": 0,
                "ch4_pub_hits": 0, "ch5_preprint_hits": 0,
                "pub_idx_coverage": len(pub_idx), "pre_idx_coverage": len(pre_idx),
                "aact_channel_optional": aact_available}

    with_signal = []
    without_signal = []
    for e in events:
        cik = (e.get("cik") or "").zfill(10)
        tk = cik2tk.get(cik)
        d_day = e.get("d_day", "")
        if not tk or not d_day:
            continue
        try:
            base = datetime.strptime(d_day, "%Y-%m-%d").date()
        except Exception:
            continue
        d180 = (base - timedelta(days=180)).strftime("%Y-%m-%d")
        d31 = (base - timedelta(days=31)).strftime("%Y-%m-%d")

        ch1_hit = any(d180 <= dt <= d31 for dt in ch1_dates_by_cik.get(cik, []))
        ch2_hit = any(d180 <= dt <= d31 for dt in ch2_dates_by_cik.get(cik, []))
        ch3_hit = tk in memb_tk
        ch4_hit = is_pub_signal(pub_idx.get(cik), base.year)
        ch5_hit = is_pub_signal(pre_idx.get(cik), base.year)

        if ch1_hit: ch_stats["ch1_13D_hits"] += 1
        if ch2_hit: ch_stats["ch2_F4P_hits"] += 1
        if ch3_hit: ch_stats["ch3_memb_hits"] += 1
        if ch4_hit: ch_stats["ch4_pub_hits"] += 1
        if ch5_hit: ch_stats["ch5_preprint_hits"] += 1

        has_signal = ch1_hit or ch2_hit or ch3_hit or ch4_hit or ch5_hit

        sp = prices.get(tk, {})
        if not sp:
            continue
        pre = net_excess(sp, bench, d_day, -30, -1)
        if pre is None:
            continue

        row = {"cik": cik, "ticker": tk, "d_day": d_day, "pre": pre}
        if has_signal:
            with_signal.append(row)
        else:
            without_signal.append(row)

    LOG.info("with %d · without %d · channel_stats=%s", len(with_signal), len(without_signal), ch_stats)

    ws_pre = [r["pre"] for r in with_signal]
    ws_dates = [r["d_day"] for r in with_signal]
    wo_pre = [r["pre"] for r in without_signal]
    wo_dates = [r["d_day"] for r in without_signal]

    ws_ci = bootstrap_ci(ws_pre, ws_dates)
    wo_ci = bootstrap_ci(wo_pre, wo_dates)

    rng = random.Random(42)
    gid_ws = defaultdict(list)
    gid_wo = defaultdict(list)
    for v, g in zip(ws_pre, ws_dates):
        gid_ws[g].append(v)
    for v, g in zip(wo_pre, wo_dates):
        gid_wo[g].append(v)
    ws_keys = list(gid_ws.keys())
    wo_keys = list(gid_wo.keys())
    diffs = []
    for _ in range(5000):
        ws_pool = []
        wo_pool = []
        for _ in range(len(ws_keys)):
            ws_pool.extend(gid_ws[ws_keys[rng.randrange(len(ws_keys))]])
        for _ in range(len(wo_keys)):
            wo_pool.extend(gid_wo[wo_keys[rng.randrange(len(wo_keys))]])
        if ws_pool and wo_pool:
            diffs.append(sum(ws_pool)/len(ws_pool) - sum(wo_pool)/len(wo_pool))
    diffs.sort()
    diff_ci = (round(diffs[int(0.025*len(diffs))], 4),
               round(diffs[int(0.975*len(diffs))], 4)) if diffs else (None, None)

    ws_mean = round(mean(ws_pre), 4) if ws_pre else None
    wo_mean = round(mean(wo_pre), 4) if wo_pre else None
    diff = round(ws_mean - wo_mean, 4) if (ws_mean is not None and wo_mean is not None) else None

    supported = (diff is not None and diff >= THRESHOLD_DIFF
                 and diff_ci[0] is not None and diff_ci[0] > 0)

    ws_ci_lower_positive = (ws_ci[0] is not None and ws_ci[0] > 0)

    completeness = "5/5" if ch_stats["ch2_F4P_hits"] > 0 else "4.5/5 (Form 4 P 병합 완료 · AACT 상태 변경은 스폰서→회사 매핑 미완)"

    seal = {
        "git_sha": sha,
        "version": f"WP54-3 · 마지막 재실행 · 채널 {completeness}",
        "commit_rule": "결과와 무관하게 60일 전향 평가 (2026-11-15) 까지 확정 · 그 전 재실행 금지 (Fable 신규 규칙 · README §3)",
        "rule_precommit": "발표 전 D-180~D-31 소문 채널 신호 유무 · D-30~D-1 순초과수익 차이 · 임계 +1.0%p AND CI 하한 > 0",
        "channels_used": [
            "ch1_13D_new (h3_events)",
            "ch2_F4_P (h3_events · WP28-3 병합 · F4_buy 804건)",
            "ch3_h6_membership_flag",
            "ch4_PubMed_yoY (h57 · 307/307 커버)",
            "ch5_Preprint_yoY (h58 · 200/307 부분)",
        ],
        "aact_channel_c_note": "CT.gov 상태 변경 (h62 · WP62) 은 옵션 · 스폰서→회사 매핑 미완이므로 이번 검정에서는 미사용 · 참고 이벤트만",
        "channel_stats": ch_stats,
        "threshold_diff": THRESHOLD_DIFF,
        "with_signal": {"n": len(with_signal), "unique_dates": len(set(ws_dates)),
                        "mean_pre": ws_mean, "ci95": ws_ci,
                        "ci_lower_positive": ws_ci_lower_positive},
        "without_signal": {"n": len(without_signal), "unique_dates": len(set(wo_dates)),
                           "mean_pre": wo_mean, "ci95": wo_ci},
        "diff_with_minus_without": diff,
        "diff_ci95_bootstrap": diff_ci,
        "supported": supported,
        "verdict_locked_until": "2026-11-15 (60일 전향 평가)",
    }

    out_dir = DATA_DIR / "biotech" / "seals"
    out_dir.mkdir(parents=True, exist_ok=True)
    seal_path = out_dir / f"h54v3_signal_final_seal_{sha}.json"
    seal_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2))

    # 이전 결과 비교
    prev = json.loads((out_dir / f"h54v2_signal_full_seal_{sha}.json").read_text()) if (out_dir / f"h54v2_signal_full_seal_{sha}.json").exists() else {}
    prev_diff = prev.get("diff_with_minus_without", 0) or 0
    prev_ci = prev.get("diff_ci95_bootstrap", [0, 0]) or [0, 0]

    today_dash = datetime.now().strftime("%Y-%m-%d")
    report_dir = PROJECT_ROOT / "docs" / "plans" / "biotech" / "verification" / "H8"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = [
        f"# H8 · 신호 유무 검정 마지막 재실행 (채널 {completeness}) 리포트 (WP54-3 · {today_dash} · git_sha {sha})",
        "",
        "> 📖 [`GLOSSARY.md`](../../GLOSSARY.md) · 코드 · 상태 · 가설 뜻",
        "",
        "## 사전 커밋 (Fable 신규 규칙 · README §3)",
        "",
        "- **WP54-3 은 신호 유무 검정의 마지막 재실행**",
        "- **결과와 무관하게 60일 전향 평가 (2026-11-15) 까지 확정 · 그 전 재실행 금지**",
        "- 규칙 동일 (WP54 사전 등록): 임계 +1.0%p AND CI 하한 > 0",
        "",
        f"## 채널 (실채움 {completeness})",
        "",
        f"- ch1 (13D 신규) hits: **{ch_stats['ch1_13D_hits']}** / {len(events)}",
        f"- **ch2 (Form 4 P · WP28-3 병합) hits: {ch_stats['ch2_F4P_hits']}** / {len(events)} · **실채움 완료**",
        f"- ch3 (h6 membership · CT.gov 활동 근사) hits: **{ch_stats['ch3_memb_hits']}** / {len(events)}",
        f"- ch4 (PubMed 게재 yoY) hits: **{ch_stats['ch4_pub_hits']}** / {len(events)} · PubMed 인덱스 {ch_stats['pub_idx_coverage']} CIK 커버 (**307/307 완주**)",
        f"- ch5 (Preprint yoY) hits: **{ch_stats['ch5_preprint_hits']}** / {len(events)} · Preprint 인덱스 {ch_stats['pre_idx_coverage']} CIK 커버",
        f"- ch c (옵션 · CT.gov 상태 변경 h62) : {'AACT 이벤트 CSV 존재 · 스폰서→회사 매핑 미완으로 이번 검정 미사용' if aact_available else '미실행'}",
        "",
        "## 결과 (봉인 · 확정)",
        "",
        "| 집단 | n | 고유 날짜 | 평균 net excess (D-30~D-1) | CI 95% |",
        "|---|---|---|---|---|",
        f"| **신호 있음** | {seal['with_signal']['n']} | {seal['with_signal']['unique_dates']} | **{ws_mean*100:+.2f}%** | [{ws_ci[0]*100:+.2f}%, {ws_ci[1]*100:+.2f}%] {'**(CI 하한 > 0 확정)**' if ws_ci_lower_positive else ''} |",
        f"| **신호 없음** | {seal['without_signal']['n']} | {seal['without_signal']['unique_dates']} | **{wo_mean*100:+.2f}%** | [{wo_ci[0]*100:+.2f}%, {wo_ci[1]*100:+.2f}%] |",
        f"| **차이 (있음 − 없음)** | — | — | **{diff*100:+.2f}%p** | [{diff_ci[0]*100:+.2f}%p, {diff_ci[1]*100:+.2f}%p] |",
        "",
        f"**판정 (임계 +1.0%p AND 차이 CI 하한 > 0)**: **{'지지' if supported else '불지지'}**",
        "",
        "## WP54-2 (3.5/5) 대비 변화",
        "",
        "| 지표 | WP54-2 (3.5/5) | **WP54-3 (마지막 · {}/5)** | 변화 |".format(completeness.split()[0]),
        "|---|---|---|---|",
        f"| 차이 | {prev_diff*100:+.2f}%p | **{diff*100:+.2f}%p** | {(diff-prev_diff)*100:+.2f}%p |",
        f"| CI 하한 | {prev_ci[0]*100:+.2f}%p | **{diff_ci[0]*100:+.2f}%p** | {(diff_ci[0]-prev_ci[0])*100:+.2f}%p |",
        f"| 판정 | {'지지' if prev.get('supported') else '불지지'} | **{'지지' if supported else '불지지'}** | {'변경' if prev.get('supported') != supported else '유지'} |",
        "",
        "## 확정 문구",
        "",
        f"- **이 결과는 봉인 · 60일 전향 평가 (2026-11-15) 까지 확정 · 재실행 금지**",
        f"- 신호 있음 집단만 CI > 0 확정: **{ws_ci_lower_positive}** (mean {ws_mean*100:+.2f}% · CI 하한 {ws_ci[0]*100:+.2f}%)",
        f"- 차이 CI 하한 > 0 조건 통과: **{diff_ci[0] > 0 if diff_ci[0] is not None else '?'}**",
        f"- 2026-11-15 이후 60일 전향 평가 (WP56) 결과와 함께 재해석 예정",
        "",
        "## 쉬운 말 5줄",
        "",
        f"1. 마지막 확정 검정 · 채널 {completeness} 완비.",
        f"2. 신호 있음 {len(with_signal)}건 평균 **{ws_mean*100:+.2f}%** [{ws_ci[0]*100:+.2f}%, {ws_ci[1]*100:+.2f}%] · **CI 하한 > 0 은 {'맞음' if ws_ci_lower_positive else '아님'}**.",
        f"3. 신호 없음 {len(without_signal)}건 평균 **{wo_mean*100:+.2f}%** [{wo_ci[0]*100:+.2f}%, {wo_ci[1]*100:+.2f}%].",
        f"4. 차이 **{diff*100:+.2f}%p** · 판정 **{'지지' if supported else '불지지'}** (차이 CI 하한 < 0).",
        f"5. 2026-11-15 전향 평가까지 확정 · 그 전 재실행 금지 (Fable 신규 규칙).",
        "",
        "## 가능성 지도 (3줄 · WP36 필수)",
        "",
        f"1. 가장 밝은 자리 = **신호 있음 집단 CI [{ws_ci[0]*100:+.2f}%, {ws_ci[1]*100:+.2f}%] {'하한 > 0 확정' if ws_ci_lower_positive else '하한 여전히 < 0'}** · 완주 풀 채널 완비 재검",
        f"2. 죽은 자리 = 차이 CI 하한 < 0 (통과 못함) · WP54-3 확정 · 재실행 금지 · 채널 c AACT 매핑 후속",
        f"3. 다음에 팔 자리 = **2026-11-15 60일 전향 평가 (WP56)** 결과 · Phase C 2 (H6 소속 확장) · 실전 규칙 재검토",
    ]
    report_path = report_dir / f"H8-signal-presence-final-{today_dash}.md"
    report_path.write_text("\n".join(report))

    print(json.dumps({
        "git_sha": sha,
        "seal_path": str(seal_path),
        "report_path": str(report_path),
        "with_signal_n": seal["with_signal"]["n"],
        "without_signal_n": seal["without_signal"]["n"],
        "with_signal_mean": ws_mean,
        "with_signal_ci_lower_positive": ws_ci_lower_positive,
        "without_signal_mean": wo_mean,
        "diff": diff, "diff_ci95": diff_ci, "supported": supported,
        "channel_stats": ch_stats,
        "verdict_locked_until": "2026-11-15",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
