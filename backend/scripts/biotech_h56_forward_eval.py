"""WP56 · 60일 전향 평가 (배포 후 60일 자동 실행 대상).

**규칙 (사전 커밋 · 실행 전 고정)**:
- 매주 저장된 레이더 CSV 의 A 상태 (뉴스 예정) 종목 스캔
- 가상 규칙: "저장일 +1 매수 · 예정일 전날 청산"
- 벤치마크: XBI (바이오 ETF)
- 비용: 왕복 1.0%
- 날짜 클러스터 CI (신뢰구간) 95%
- 임계: mean ≥ +2%p AND CI 하한 > 0 (WP54 규칙 준용)

**리포트 창**:
- 60일 리포트 (배포일 + 60일)
- 6개월 리포트 (배포일 + 180일)

**trades_manual.csv 대조**:
- 사용자 실전 기록 (매수/청산 실체) 을 같은 창으로 집계
- 가상 규칙 vs 실전 대조 → 쉬운 말 리포트

**출력**: `docs/plans/biotech/verification/forward/forward-{60d|180d}-{YYYY-MM-DD}.md`

**실행 시점**:
- 크론 등록 (11월 13일 = 배포일 2026-09-14 + 60일 · 이후 매월 15일 회고)
- 스크립트는 오늘 실행하면 표본 부족 (레이더 저장 이력 필요) · 정상 · 60일 후 자동 활성화
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_h43_h8_h1b import (
    git_sha, load_prices, load_bench, load_cik_ticker,
    net_excess, bootstrap_ci,
)

import argparse
import csv
import glob
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h56_forward_eval")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

DEPLOYMENT_ANCHOR = "2026-09-14"  # Phase A 종결 배포일 (사전 커밋)
COST_BPS = 100
ALPHA_THRESHOLD = 0.02


def parse_days_from_note(note: str) -> int | None:
    """state_note_v50 에서 D-N 추출 (음수 = 미래)."""
    m = re.search(r"D-(\d+)", note or "")
    return -int(m.group(1)) if m else None


def load_radar_snapshots() -> list[dict]:
    """매주 저장된 레이더 CSV 로드 · [{save_date, ticker, expected_days_at_save, ...}]."""
    files = sorted(glob.glob(str(DATA_DIR / "biotech" / "candidates" / "radar_v1_3_*.csv")))
    out = []
    for f in files:
        m = re.search(r"radar_v1_3_(\d{8})\.csv", f)
        if not m:
            continue
        save_dt = datetime.strptime(m.group(1), "%Y%m%d").date()
        with open(f) as fp:
            for r in csv.DictReader(fp):
                if r.get("time_state") != "A":
                    continue
                # radar CSV 에는 D-N 대신 why_easy 또는 state_note 참조 필요 · v1.3 은 why_easy 에 예정일 표기
                why = r.get("why_easy", "")
                m2 = re.search(r"D-(\d+)", why)
                if not m2:
                    continue
                d_ahead = int(m2.group(1))
                expected_dt = save_dt + timedelta(days=d_ahead)
                out.append({
                    "save_date": save_dt.strftime("%Y-%m-%d"),
                    "ticker": r["ticker"],
                    "expected_date": expected_dt.strftime("%Y-%m-%d"),
                    "days_ahead_at_save": d_ahead,
                    "score": float(r.get("score", 0) or 0),
                    "mcap": r.get("mcap", ""),
                })
    return out


def evaluate_virtual_rule(snapshots: list[dict], prices: dict, bench: dict, cutoff_date: str) -> dict:
    """가상 규칙 "저장일+1 매수 · 예정일 전날 청산" 평가."""
    rows = []
    for s in snapshots:
        # 이미 청산일이 지난 것만 (전향 평가)
        if s["expected_date"] > cutoff_date:
            continue
        sp = prices.get(s["ticker"], {})
        if not sp:
            continue
        # 저장일 +1 매수 · 예정일 -1 청산
        try:
            buy_dt = (datetime.strptime(s["save_date"], "%Y-%m-%d").date() + timedelta(days=1))
            sell_dt = (datetime.strptime(s["expected_date"], "%Y-%m-%d").date() + timedelta(days=-1))
        except Exception:
            continue
        if sell_dt <= buy_dt:
            continue
        # 실제 계산: buy_dt 종가 vs sell_dt 종가 (근사)
        buy_key = buy_dt.strftime("%Y-%m-%d")
        sell_key = sell_dt.strftime("%Y-%m-%d")
        # 가장 가까운 거래일
        def _nearest(k, dp):
            keys = sorted(dp.keys())
            for kk in keys:
                if kk >= k:
                    return dp[kk]
            return None
        buy_p = _nearest(buy_key, sp)
        sell_p = _nearest(sell_key, sp)
        buy_b = _nearest(buy_key, bench)
        sell_b = _nearest(sell_key, bench)
        if not (buy_p and sell_p and buy_b and sell_b):
            continue
        r_stock = sell_p / buy_p - 1.0
        r_bench = sell_b / buy_b - 1.0
        net = r_stock - r_bench - (COST_BPS / 10000.0)
        rows.append({**s, "net_excess": round(net, 4)})

    if not rows:
        return {"n": 0, "mean": None, "ci95": (None, None), "alpha_pass": False, "rows": []}
    vals = [r["net_excess"] for r in rows]
    dates = [r["save_date"] for r in rows]
    ci = bootstrap_ci(vals, dates)
    m = round(mean(vals), 4)
    alpha_pass = (m >= ALPHA_THRESHOLD and ci[0] > 0)
    return {"n": len(rows), "mean": m, "ci95": ci, "alpha_pass": alpha_pass, "rows": rows}


def load_trades_manual() -> list[dict]:
    """trades_manual.csv 실전 기록 로드."""
    p = DATA_DIR / "biotech" / "trades" / "trades_manual.csv"
    if not p.exists():
        return []
    with p.open() as f:
        return [r for r in csv.DictReader(f) if (r.get("status", "").upper() == "CLOSED")]


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--window", choices=["60d", "180d"], default="60d")
    args = parser.parse_args()

    sha = git_sha()
    anchor = datetime.strptime(DEPLOYMENT_ANCHOR, "%Y-%m-%d").date()
    today = datetime.now(timezone.utc).date()
    window_days = 60 if args.window == "60d" else 180
    cutoff = anchor + timedelta(days=window_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    LOG.info("anchor=%s window=%s cutoff=%s today=%s", anchor, args.window, cutoff_str, today)

    if today < cutoff:
        LOG.warning("아직 창 미도달 · 표본 부분 실행 (today %s < cutoff %s)", today, cutoff_str)

    snapshots = load_radar_snapshots()
    LOG.info("radar snapshots (A state · with D-N): %d", len(snapshots))

    prices = load_prices(sha)
    bench = load_bench(sha)

    virtual = evaluate_virtual_rule(snapshots, prices, bench, cutoff_str)
    trades = load_trades_manual()

    # 실전 기록: 같은 창 청산 · net_excess 근사 (사용자 입력 금액 기준)
    trades_in_window = [t for t in trades if (t.get("timestamp_utc", "") >= DEPLOYMENT_ANCHOR and t.get("timestamp_utc", "") <= cutoff_str + "T23:59:59Z")]

    report_dir = PROJECT_ROOT / "docs" / "plans" / "biotech" / "verification" / "forward"
    report_dir.mkdir(parents=True, exist_ok=True)

    ci_str = f"[{virtual['ci95'][0]*100:.2f}%, {virtual['ci95'][1]*100:.2f}%]" if virtual['ci95'][0] is not None else "[표본 없음]"
    mean_str = f"{virtual['mean']*100:.2f}%" if virtual['mean'] is not None else "N/A"

    report = [
        f"# 60일 전향 평가 리포트 · window {args.window} · cutoff {cutoff_str} (WP56)",
        "",
        "> 📖 [`GLOSSARY.md`](../../GLOSSARY.md) · 코드 · 상태 · 가설 뜻",
        "",
        "## 사전 커밋 (실행 전 규칙 · WP56)",
        "",
        f"- 배포 앵커일: **{DEPLOYMENT_ANCHOR}** (Phase A 종결)",
        f"- 창: **{args.window}** (cutoff = {cutoff_str})",
        "- 가상 규칙: 저장일 +1 매수 · 예정일 전날 청산",
        "- 벤치: XBI (바이오 ETF) · 비용 왕복 1.0%",
        "- 임계: mean ≥ +2%p AND CI (신뢰구간) 하한 > 0",
        "",
        "## 가상 규칙 결과",
        "",
        f"- 레이더 스냅샷 총 A 상태 (뉴스 예정) 이벤트: {len(snapshots)}",
        f"- 창 도달 표본 (n): **{virtual['n']}**",
        f"- 평균 net excess: **{mean_str}**",
        f"- CI 95%: **{ci_str}**",
        f"- alpha_pass (임계 통과): **{virtual['alpha_pass']}**",
        "",
        "## 실전 기록 대조 (trades_manual.csv)",
        "",
        f"- 창 내 CLOSED 거래 수: **{len(trades_in_window)}**",
    ]
    if trades_in_window:
        report.append("")
        report.append("| # | ticker | 청산일 | rationale_source | linked_report |")
        report.append("|---|---|---|---|---|")
        for i, t in enumerate(trades_in_window[:20], 1):
            report.append(f"| {i} | {t.get('ticker','')} | {t.get('timestamp_utc','')} | {t.get('rationale_source','')} | {t.get('linked_report','')} |")
    else:
        report.append("- 없음 (실전 기록 대기)")

    report += [
        "",
        "## 쉬운 말 5줄",
        "",
        f"1. 배포 {DEPLOYMENT_ANCHOR} 이후 {args.window} 창 (마감 {cutoff_str}) 의 레이더 A 상태 종목 전향 관찰.",
        f"2. 가상 규칙 '저장일 +1 매수 · 예정일 전날 청산' 표본 n={virtual['n']} · 평균 {mean_str} · CI {ci_str}.",
        f"3. 임계 통과 (mean ≥ +2%p AND CI 하한 > 0): **{virtual['alpha_pass']}**.",
        f"4. 실전 기록 (trades_manual.csv) CLOSED 거래 {len(trades_in_window)}건 대조.",
        "5. 이 리포트는 자동 생성 · 60일·6개월 창 각 1회 (사용자 검토 후 Phase C 재조정).",
        "",
        "## 가능성 지도 (3줄 · WP36 필수)",
        "",
        f"1. 가장 밝은 자리 = {'가상 규칙 alpha_pass · 실전 배포 규칙 확정' if virtual['alpha_pass'] else '표본 확대 및 CI 축소'}",
        "2. 죽은 자리 = 창 미도달 표본 (다음 리포트에서 회수) · 채널 부분 (Phase C 완비 대기)",
        f"3. 다음에 팔 자리 = {'6개월 리포트 재실행 (window=180d)' if args.window == '60d' else '연간 전체 회고 · Phase D KR 트랙 판단'}",
    ]

    out_path = report_dir / f"forward-{args.window}-{cutoff_str}.md"
    out_path.write_text("\n".join(report))

    summary = {
        "git_sha": sha,
        "anchor": DEPLOYMENT_ANCHOR,
        "window": args.window,
        "cutoff": cutoff_str,
        "today": today.strftime("%Y-%m-%d"),
        "snapshots_a_state": len(snapshots),
        "virtual_n": virtual["n"],
        "virtual_mean": virtual["mean"],
        "virtual_ci95": virtual["ci95"],
        "virtual_alpha_pass": virtual["alpha_pass"],
        "trades_in_window": len(trades_in_window),
        "report_path": str(out_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
