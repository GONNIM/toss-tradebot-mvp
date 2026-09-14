"""WP54 · 신호 유무 검정 (사전 등록 · 완주 풀 1회 실행).

가설 (사전 커밋):
- 발표 전 D-180~D-31 에 소문 채널 (13D 신규 · Form 4 P · 테마 소속 증가 ·
  가능 시 CT.gov 상태 변경) 신호가 **1개 이상 있는 이벤트** 는
  **신호 없는 이벤트보다 D-30~D-1 순초과수익이 높다**.

규칙 (실행 전 고정):
- 두 집단 평균 차이 · 날짜 클러스터 CI (신뢰구간) 하한 > 0 이면 지지
- 임계 차이 ≥ +1.0%p (사전 고정)
- 채널 부분이면 "채널 n종" 명시
- WP53 관찰 (신호 있음 861건 +3~4% vs 전체 +1.4%) 의 정식 판정

이번 실행 채널 (부분 자료 명시):
- 채널 1: 13D 신규 (h3_events)
- 채널 2: Form 4 P (F4_buy · 있으면)
- 채널 3: 테마 소속 (h6_membership · 소속 flag)
- 채널 4/5: PubMed · bioRxiv · 회사별 조회 부담 → 미포함 (부분)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_h43_h8_h1b import (
    git_sha, load_events, load_prices, load_bench, load_cik_ticker,
    net_excess, bootstrap_ci,
)

import csv
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h54_signal_presence")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

THRESHOLD_DIFF = 0.010  # +1.0%p 사전 고정


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    events = load_events(sha)
    prices = load_prices(sha)
    bench = load_bench(sha)
    cik2tk = load_cik_ticker(sha)

    # 채널 1: 13D 신규 (h3_events · CIK 별 date list)
    ch1_dates_by_cik = defaultdict(list)
    p1 = DATA_DIR / f"h3_events_{sha}.csv"
    with p1.open() as f:
        for r in csv.DictReader(f):
            cik = (r.get("target_cik") or "").zfill(10)
            d = r.get("event_date", "")
            if cik and d:
                ch1_dates_by_cik[cik].append(d)

    # 채널 2: Form 4 P (F4_buy · h3_events 에서 event_type 로 필터 · 있으면)
    ch2_dates_by_cik = defaultdict(list)
    with p1.open() as f:
        for r in csv.DictReader(f):
            et = r.get("event_type", "")
            if et in ("F4_buy", "F4_P", "F4 P"):
                cik = (r.get("target_cik") or "").zfill(10)
                d = r.get("event_date", "")
                if cik and d:
                    ch2_dates_by_cik[cik].append(d)

    # 채널 3: 테마 소속 (h6_membership · ticker flag)
    memb_tk = set()
    mp = DATA_DIR / f"h6_membership_{sha}.csv"
    if mp.exists():
        with mp.open() as f:
            for r in csv.DictReader(f):
                for t in (r.get("tiingo_matched_tickers") or "").split("|"):
                    if t.strip():
                        memb_tk.add(t.strip())

    # 이벤트별 신호 유무 판정 · D-30~D-1 net excess 계산
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

        # 채널 1: 이 창에 13D 신호 있음
        ch1_hit = any(d180 <= dt <= d31 for dt in ch1_dates_by_cik.get(cik, []))
        # 채널 2: 이 창에 F4_buy 신호 있음
        ch2_hit = any(d180 <= dt <= d31 for dt in ch2_dates_by_cik.get(cik, []))
        # 채널 3: 테마 소속 (시점 무관 · 부분 근사)
        ch3_hit = tk in memb_tk

        has_signal = ch1_hit or ch2_hit or ch3_hit

        sp = prices.get(tk, {})
        if not sp:
            continue
        pre = net_excess(sp, bench, d_day, -30, -1)
        if pre is None:
            continue

        row = {"cik": cik, "ticker": tk, "d_day": d_day, "pre": pre,
               "ch1_13D": ch1_hit, "ch2_F4P": ch2_hit, "ch3_memb": ch3_hit}
        if has_signal:
            with_signal.append(row)
        else:
            without_signal.append(row)

    LOG.info("with_signal: %d · without_signal: %d", len(with_signal), len(without_signal))

    ws_pre = [r["pre"] for r in with_signal]
    ws_dates = [r["d_day"] for r in with_signal]
    wo_pre = [r["pre"] for r in without_signal]
    wo_dates = [r["d_day"] for r in without_signal]

    ws_ci = bootstrap_ci(ws_pre, ws_dates)
    wo_ci = bootstrap_ci(wo_pre, wo_dates)

    # 차이 · 날짜 클러스터 CI (차이의 CI 는 pooled diff bootstrap)
    import random
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
    diff_ci = (round(diffs[int(0.025 * len(diffs))], 4),
               round(diffs[int(0.975 * len(diffs))], 4)) if diffs else (None, None)

    ws_mean = round(mean(ws_pre), 4) if ws_pre else None
    wo_mean = round(mean(wo_pre), 4) if wo_pre else None
    diff = round(ws_mean - wo_mean, 4) if (ws_mean is not None and wo_mean is not None) else None

    supported = (diff is not None and diff >= THRESHOLD_DIFF and diff_ci[0] is not None and diff_ci[0] > 0)

    seal = {
        "git_sha": sha,
        "rule_precommit": "발표 전 D-180~D-31 소문 채널 신호 유무 로 두 집단 · D-30~D-1 순초과수익 차이 · 임계 +1.0%p · CI 하한 > 0 지지",
        "channels_used": [
            "ch1_13D_new (h3_events)",
            "ch2_F4_P (h3_events event_type F4_buy)",
            "ch3_h6_membership_flag (h6_membership · 시점 무관 · 부분 근사)",
        ],
        "channels_missing_note": "PubMed 게재 증가율 · bioRxiv · CT.gov 상태 변경 · 회사별 조회 부담 미포함 · 부분 3/5",
        "threshold_diff": THRESHOLD_DIFF,
        "with_signal": {"n": len(with_signal), "unique_dates": len(set(ws_dates)),
                        "mean_pre": ws_mean, "ci95": ws_ci},
        "without_signal": {"n": len(without_signal), "unique_dates": len(set(wo_dates)),
                           "mean_pre": wo_mean, "ci95": wo_ci},
        "diff_with_minus_without": diff,
        "diff_ci95_bootstrap": diff_ci,
        "supported": supported,
        "note_relation_to_WP53": "WP53 관찰 (신호 있음 861건 +3.87%) 대비 · 채널 정의 유사 (13D+membership · F4 추가) · 완주 풀 정식 판정",
    }

    out_dir = DATA_DIR / "biotech" / "seals"
    out_dir.mkdir(parents=True, exist_ok=True)
    seal_path = out_dir / f"h54_signal_presence_seal_{sha}.json"
    seal_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2))

    report_dir = PROJECT_ROOT / "docs" / "plans" / "biotech" / "verification" / "H8"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = [
        f"# H8 · 신호 유무 검정 리포트 (WP54 · 2026-09-14 · git_sha {sha})",
        "",
        "> 📖 [`GLOSSARY.md`](../../GLOSSARY.md) · 코드 · 상태 · 가설 뜻",
        "",
        "## 사전 등록 (실행 전 규칙 고정)",
        "",
        "- **가설**: 발표 전 D-180~D-31 에 소문 채널 (13D (5% 지분 신고) · Form 4 P (임원 매수) · 테마 소속) 신호가 1개 이상인 이벤트는 신호 없는 이벤트보다 D-30~D-1 순초과수익이 높다.",
        "- **규칙**: 두 집단 평균 차이 · 날짜 클러스터 CI (신뢰구간) 하한 > 0 이면 지지 · 임계 차이 ≥ +1.0%p (사전 고정)",
        "- **관계**: WP53 관찰 (신호 있음 861건 +3.87%) 의 완주 풀 정식 판정",
        "- **채널 (부분 3/5)**: 13D · F4_P · h6_membership 사용 · PubMed · bioRxiv · CT.gov 상태 변경 미포함",
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
        "## 쉬운 말 5줄",
        "",
        f"1. 소문 채널 3종 (13D · Form 4 매수 · 테마 소속) 로 이벤트를 신호 있음/없음 두 집단으로 나눔 (n = {len(with_signal)} vs {len(without_signal)}).",
        f"2. **신호 있음 그룹 평균 {ws_mean*100:.2f}%** vs **신호 없음 그룹 평균 {wo_mean*100:.2f}%** = 차이 **{diff*100:.2f}%p**.",
        f"3. 차이의 신뢰구간 = [{diff_ci[0]*100:.2f}%p, {diff_ci[1]*100:.2f}%p] · 임계 +1.0%p 및 CI 하한 > 0 판정: **{'지지' if supported else '불지지'}**.",
        f"4. WP53 관찰 (신호 있음 861건 +3.87%) 은 완주 풀 · 채널 확대 시 차이 {'유지' if supported else '축소'} · 채널 3/5 부분.",
        "5. 원 채널 (PubMed · bioRxiv · CT.gov) 확대 시 신호 있음 그룹 표본 감소 · 차이 재확인 필요.",
        "",
        "## 가능성 지도 (3줄 · WP36 필수)",
        "",
        f"1. 가장 밝은 자리 = {'**신호 유무 검정 지지 (+' + f'{diff*100:.2f}' + '%p)** · Phase C 확정 신호' if supported else '**차이 관측만** · 임계 미달 · 채널 완비 후 재검'}",
        "2. 죽은 자리 = 채널 3/5 (PubMed/bioRxiv/CT.gov 상태 미포함) · 표본 편향 가능",
        "3. 다음에 팔 자리 = 채널 확장 (PubMed 회사 조회 · bioRxiv API) · WP54-2 재실행 · 알파 확정 후 실전 규칙 반영",
    ]
    report_path = report_dir / "H8-signal-presence-20260914.md"
    report_path.write_text("\n".join(report))

    print(json.dumps({
        "git_sha": sha,
        "seal_path": str(seal_path),
        "report_path": str(report_path),
        "with_signal_n": seal["with_signal"]["n"],
        "without_signal_n": seal["without_signal"]["n"],
        "with_signal_mean": ws_mean,
        "without_signal_mean": wo_mean,
        "diff": diff,
        "diff_ci95": diff_ci,
        "supported": supported,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
