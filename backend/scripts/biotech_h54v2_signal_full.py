"""WP54-2 · 신호 유무 검정 재실행 · 채널 5/5 완비 (Phase C 1).

WP54 (채널 3/5 부분 · 차이 +1.61%p · CI 하한 < 0 방향만) 의 후속.
채널 완비 (PubMed h57 + Preprint h58 추가) 후 동일 규칙 재판정.

**사전 커밋 규칙 (WP54 동일 · 실행 전 고정)**:
- 발표 전 D-180~D-31 소문 채널 신호 있음 vs 없음 두 집단
- D-30~D-1 순초과수익 차이 · 임계 +1.0%p AND 날짜 클러스터 CI 하한 > 0 이면 지지
- 채널 5종 = ch1 13D 신규 · ch2 Form 4 P · ch3 h6 membership · ch4 PubMed 게재 · ch5 Preprint (bioRxiv/medRxiv)
- ch4/ch5 : 이벤트 D-day 소속 연도 대비 이전 연도 게재 수 증가 판정

**출력**:
- 봉인: `h54v2_signal_full_seal_{sha}.json`
- 리포트: `verification/H8/H8-signal-presence-full-YYYY-MM-DD.md`
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
LOG = logging.getLogger("biotech_h54v2_signal_full")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
THRESHOLD_DIFF = 0.010  # +1.0%p 사전 고정 (WP54 동일)


def load_pub_index(sha: str) -> dict:
    p = DATA_DIR / f"h57_pubmed_index_{sha}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def load_preprint_index(sha: str) -> dict:
    p = DATA_DIR / f"h58_preprint_index_{sha}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def is_pub_signal(idx_entry: dict | None, d_day_year: int) -> bool:
    """PubMed/Preprint 신호 유무 판정.

    사전 커밋: D-day 년도의 게재 수가 이전 년도 대비 증가 (>0 인 상태에서 증가)
    · 이전 년도 = D-day 년도 - 1
    · 판정 = recent > baseline 이고 recent >= 1
    """
    if not idx_entry:
        return False
    counts = idx_entry.get("counts", {})
    y_recent = counts.get(f"y{d_day_year}", 0) or 0
    y_base = counts.get(f"y{d_day_year - 1}", 0) or 0
    if y_recent < 0:  # 오류
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
    pub_idx = load_pub_index(sha)
    pre_idx = load_preprint_index(sha)
    LOG.info("events %d · pub_idx %d · pre_idx %d", len(events), len(pub_idx), len(pre_idx))

    # 채널 1: 13D 신규
    ch1_dates_by_cik = defaultdict(list)
    with (DATA_DIR / f"h3_events_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            cik = (r.get("target_cik") or "").zfill(10)
            d = r.get("event_date", "")
            if cik and d:
                ch1_dates_by_cik[cik].append(d)

    # 채널 2: F4_P (동일 파일 · event_type 필터)
    ch2_dates_by_cik = defaultdict(list)
    with (DATA_DIR / f"h3_events_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            et = r.get("event_type", "")
            if et in ("F4_buy", "F4_P", "F4 P"):
                cik = (r.get("target_cik") or "").zfill(10)
                d = r.get("event_date", "")
                if cik and d:
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

    # 채널 커버율 통계
    ch_stats = {"ch1_13D_hits": 0, "ch2_F4P_hits": 0, "ch3_memb_hits": 0,
                "ch4_pub_hits": 0, "ch5_preprint_hits": 0,
                "pub_idx_coverage": len(pub_idx), "pre_idx_coverage": len(pre_idx)}

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

        row = {"cik": cik, "ticker": tk, "d_day": d_day, "pre": pre,
               "ch1": ch1_hit, "ch2": ch2_hit, "ch3": ch3_hit, "ch4": ch4_hit, "ch5": ch5_hit}
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

    # 차이 CI (WP54 방식 · pooled diff bootstrap)
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

    seal = {
        "git_sha": sha,
        "version": "WP54-2 · 채널 5/5 완비",
        "rule_precommit": "발표 전 D-180~D-31 소문 채널 신호 유무 · D-30~D-1 순초과수익 차이 · 임계 +1.0%p AND CI 하한 > 0",
        "channels_used": [
            "ch1_13D_new (h3_events)",
            "ch2_F4_P (h3_events event_type)",
            "ch3_h6_membership_flag",
            "ch4_PubMed_publication_yoY (h57)",
            "ch5_Preprint_yoY (h58)",
        ],
        "channel_stats": ch_stats,
        "threshold_diff": THRESHOLD_DIFF,
        "with_signal": {"n": len(with_signal), "unique_dates": len(set(ws_dates)),
                        "mean_pre": ws_mean, "ci95": ws_ci},
        "without_signal": {"n": len(without_signal), "unique_dates": len(set(wo_dates)),
                           "mean_pre": wo_mean, "ci95": wo_ci},
        "diff_with_minus_without": diff,
        "diff_ci95_bootstrap": diff_ci,
        "supported": supported,
    }

    out_dir = DATA_DIR / "biotech" / "seals"
    out_dir.mkdir(parents=True, exist_ok=True)
    seal_path = out_dir / f"h54v2_signal_full_seal_{sha}.json"
    seal_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2))

    # 이전 WP54 결과 로드 (비교)
    prev_path = out_dir / f"h54_signal_presence_seal_{sha}.json"
    prev = json.loads(prev_path.read_text()) if prev_path.exists() else {}
    prev_diff = prev.get("diff_with_minus_without")
    prev_ci = prev.get("diff_ci95_bootstrap", [None, None])
    prev_ws_mean = prev.get("with_signal", {}).get("mean_pre")
    prev_wo_mean = prev.get("without_signal", {}).get("mean_pre")
    prev_ws_n = prev.get("with_signal", {}).get("n", 0)
    prev_wo_n = prev.get("without_signal", {}).get("n", 0)

    today_dash = datetime.now().strftime("%Y-%m-%d")
    report_dir = PROJECT_ROOT / "docs" / "plans" / "biotech" / "verification" / "H8"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = [
        f"# H8 · 신호 유무 검정 (채널 5/5 완비) 리포트 (WP54-2 · {today_dash} · git_sha {sha})",
        "",
        "> 📖 [`GLOSSARY.md`](../../GLOSSARY.md) · 코드 · 상태 · 가설 뜻",
        "",
        "## 사전 등록 (WP54 동일 · 실행 전 고정)",
        "",
        "- **가설**: 발표 전 D-180~D-31 소문 채널 신호 1개 이상 있는 이벤트는 없는 이벤트보다 D-30~D-1 순초과수익이 높다.",
        "- **규칙**: 두 집단 평균 차이 · 날짜 클러스터 CI (신뢰구간) 95% 하한 > 0 이면 지지 · 임계 차이 ≥ +1.0%p",
        "- **채널 (5/5 완비)**: 13D · F4_P · h6 membership + **PubMed 게재 (h57 · Phase C 1)** + **Preprint (h58 · Phase C 1)**",
        "",
        "## 채널 커버 통계",
        "",
        f"- ch1 (13D 신규) hits: **{ch_stats['ch1_13D_hits']}** / {len(events)}",
        f"- ch2 (F4_P) hits: **{ch_stats['ch2_F4P_hits']}** / {len(events)}",
        f"- ch3 (h6 membership) hits: **{ch_stats['ch3_memb_hits']}** / {len(events)}",
        f"- **ch4 (PubMed 게재 yoY) hits: {ch_stats['ch4_pub_hits']}** / {len(events)} · PubMed 인덱스 {ch_stats['pub_idx_coverage']} CIK 커버",
        f"- **ch5 (Preprint yoY) hits: {ch_stats['ch5_preprint_hits']}** / {len(events)} · Preprint 인덱스 {ch_stats['pre_idx_coverage']} CIK 커버",
        "",
        "## 결과",
        "",
        "| 집단 | n | 고유 날짜 | 평균 net excess (D-30~D-1) | CI 95% |",
        "|---|---|---|---|---|",
        f"| **신호 있음** | {seal['with_signal']['n']} | {seal['with_signal']['unique_dates']} | **{ws_mean*100:.2f}%** | [{ws_ci[0]*100:.2f}%, {ws_ci[1]*100:.2f}%] |",
        f"| **신호 없음** | {seal['without_signal']['n']} | {seal['without_signal']['unique_dates']} | **{wo_mean*100:.2f}%** | [{wo_ci[0]*100:.2f}%, {wo_ci[1]*100:.2f}%] |",
        f"| **차이 (있음 − 없음)** | — | — | **{diff*100:.2f}%p** | [{diff_ci[0]*100:.2f}%p, {diff_ci[1]*100:.2f}%p] |",
        "",
        f"**판정 (임계 +1.0%p AND CI 하한 > 0)**: **{'지지' if supported else '불지지'}**",
        "",
        "## WP54 (채널 3/5 부분) 대비 변화 표",
        "",
        "| 지표 | WP54 (채널 3/5 부분) | **WP54-2 (채널 5/5 완비)** | 변화 |",
        "|---|---|---|---|",
        f"| 신호 있음 n | {prev_ws_n} | {seal['with_signal']['n']} | {'+' if seal['with_signal']['n'] > prev_ws_n else ''}{seal['with_signal']['n'] - prev_ws_n} |",
        f"| 신호 있음 mean | {prev_ws_mean*100:.2f}% | {ws_mean*100:.2f}% | {(ws_mean-prev_ws_mean)*100:+.2f}%p |",
        f"| 신호 없음 n | {prev_wo_n} | {seal['without_signal']['n']} | {'+' if seal['without_signal']['n'] > prev_wo_n else ''}{seal['without_signal']['n'] - prev_wo_n} |",
        f"| 신호 없음 mean | {prev_wo_mean*100:.2f}% | {wo_mean*100:.2f}% | {(wo_mean-prev_wo_mean)*100:+.2f}%p |",
        f"| 차이 | {prev_diff*100:.2f}%p | **{diff*100:.2f}%p** | {(diff-prev_diff)*100:+.2f}%p |",
        f"| CI 하한 | {prev_ci[0]*100:.2f}%p | **{diff_ci[0]*100:.2f}%p** | {(diff_ci[0]-prev_ci[0])*100:+.2f}%p |",
        f"| 판정 | {'지지' if prev.get('supported') else '불지지'} | **{'지지' if supported else '불지지'}** | {'변경' if prev.get('supported') != supported else '유지'} |",
        "",
        "## 쉬운 말 5줄",
        "",
        f"1. 소문 채널 완비 (5개 = 13D · Form 4 매수 · 테마 소속 + **PubMed 게재 · 프리프린트**) 로 재판정.",
        f"2. 신호 있음 {len(with_signal)}건 평균 **{ws_mean*100:.2f}%** vs 신호 없음 {len(without_signal)}건 평균 **{wo_mean*100:.2f}%** = 차이 **{diff*100:.2f}%p**.",
        f"3. 차이의 신뢰구간 = [{diff_ci[0]*100:.2f}%p, {diff_ci[1]*100:.2f}%p] · 판정: **{'지지' if supported else '불지지'}**.",
        f"4. WP54 (채널 3/5 · 차이 {prev_diff*100:.2f}%p · 불지지) 대비 채널 추가 효과 = 차이 {(diff-prev_diff)*100:+.2f}%p · 판정 {'변경' if prev.get('supported') != supported else '유지'}.",
        "5. 채널 확대 = 정의 확장 · 사전 커밋 규칙 (임계 · CI 규칙) 동일 유지.",
        "",
        "## 가능성 지도 (3줄 · WP36 필수)",
        "",
        f"1. 가장 밝은 자리 = {'**신호 유무 검정 지지** · Phase C 실전 규칙 확정 후보' if supported else '**차이 관측 · CI 하한 여전히 < 0**' if diff and diff > 0 else '차이 축소 · 채널 추가 효과 미미'}",
        "2. 죽은 자리 = 채널 4/5 인덱스 커버율 (PubMed h57 · Preprint h58) 완주 여부 · 회사명 매칭 노이즈",
        "3. 다음에 팔 자리 = CT.gov 상태 변경 채널 (AACT 스냅샷 · Phase C 1 후반) · 회사명 매칭 정확도 개선 (DB xref)",
    ]
    report_path = report_dir / f"H8-signal-presence-full-{today_dash}.md"
    report_path.write_text("\n".join(report))

    print(json.dumps({
        "git_sha": sha, "seal_path": str(seal_path), "report_path": str(report_path),
        "with_signal_n": seal["with_signal"]["n"],
        "without_signal_n": seal["without_signal"]["n"],
        "with_signal_mean": ws_mean, "without_signal_mean": wo_mean,
        "diff": diff, "diff_ci95": diff_ci, "supported": supported,
        "channel_stats": ch_stats,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
