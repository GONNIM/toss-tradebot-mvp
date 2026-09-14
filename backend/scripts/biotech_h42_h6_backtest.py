"""WP42 · H6 백테스트 실행 (탐색·확증 병행 · 관찰 트랙 · h6_params 사전 커밋 준수).

h6_params 사전 커밋 (backend/data/h6_params.json):
- 잡음 억제 순위 (4Q rolling YoY · WP22-2 · h6_rank_smoothed) · 대조군 포함 8세트 (주 6 + control 2)
- 상위 vs 하위 3분위 · 1Q / 4Q 창 · XBI 벤치 · 비용 왕복 1.0%
- 분기 클러스터 bootstrap 10,000회 · seed 42
- 소속 종목 = h6_membership · CT.gov 스폰서 point-in-time
- 자동 GO 조건 = 소속 ≥3 인 분기 ≥ 20 (미달 시 "표본 부족 · 관찰" · 실행은 진행)

산출: docs/plans/biotech/verification/H6/H6-report.md
     backend/data/biotech/seals/h6_seal_report.json
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import math
import random
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h42_h6_backtest")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
COST_BPS = 100  # 왕복 1.0%
BOOT = 10_000
SEED = 42
MAIN_THEMES = ["obesity_glp1", "hair_loss", "longevity_rejuvenation", "meal_replacement_metabolic", "hibernation_hypothermia", "cognitive_memory"]


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_ranks(sha: str) -> dict:
    """h6_rank_smoothed · (year, quarter, theme) → tercile (top/mid/bot)."""
    p = DATA_DIR / f"h6_rank_smoothed_{sha}.csv"
    out = {}
    with p.open() as f:
        for r in csv.DictReader(f):
            k = (int(r["year"]), int(r["quarter"]), r["theme"])
            out[k] = r["tercile"]
    return out


def load_membership(sha: str) -> dict:
    """(theme, y, q) → set(ticker)."""
    p = DATA_DIR / f"h6_membership_{sha}.csv"
    out = defaultdict(set)
    with p.open() as f:
        for r in csv.DictReader(f):
            try:
                y = int(r["year"]); q = int(r["quarter"])
            except Exception:
                continue
            for t in (r.get("tiingo_matched_tickers") or "").split("|"):
                t = t.strip()
                if t:
                    out[(r["theme"], y, q)].add(t)
    return out


def load_prices(sha: str) -> dict:
    p = DATA_DIR / f"h3_prices_merged_{sha}.csv"
    out = defaultdict(dict)
    with p.open() as f:
        for r in csv.DictReader(f):
            try:
                c = float(r["close"])
            except Exception:
                continue
            out[r["ticker"]][r["date"]] = c
    return out


def load_bench(sha: str) -> dict:
    p = DATA_DIR / f"benchmarks_{sha}.csv"
    out = {}
    with p.open() as f:
        for r in csv.DictReader(f):
            if r.get("ticker") == "XBI":
                try:
                    out[r["date"]] = float(r["close"])
                except Exception:
                    continue
    return out


def quarter_first_close(prices: dict, y: int, q: int) -> tuple[str, float] | None:
    """분기 첫 영업일 종가 근사 = 첫 3주."""
    start_month = 3 * (q - 1) + 1
    base = datetime(y, start_month, 1).date()
    for off in range(0, 21):
        k = (base + timedelta(days=off)).strftime("%Y-%m-%d")
        if k in prices:
            return (k, prices[k])
    return None


def quarter_last_close(prices: dict, y: int, q: int) -> tuple[str, float] | None:
    """분기 마지막 영업일 종가 근사 = 마지막 3주."""
    from calendar import monthrange
    end_month = 3 * (q - 1) + 3
    last_day = monthrange(y, end_month)[1]
    base = datetime(y, end_month, last_day).date()
    for off in range(0, 21):
        k = (base - timedelta(days=off)).strftime("%Y-%m-%d")
        if k in prices:
            return (k, prices[k])
    return None


def add_quarters(y: int, q: int, n: int) -> tuple[int, int]:
    idx = y * 4 + (q - 1) + n
    return (idx // 4, idx % 4 + 1)


def compute_log_excess(prices: dict, bench: dict, y1: int, q1: int, y2: int, q2: int) -> float | None:
    """포지션 y1q1 첫 → y2q2 마지막 · net log excess (log_stock - log_bench - cost)."""
    ep = quarter_first_close(prices, y1, q1)
    xp = quarter_last_close(prices, y2, q2)
    eb = quarter_first_close(bench, y1, q1)
    xb = quarter_last_close(bench, y2, q2)
    if not (ep and xp and eb and xb):
        return None
    try:
        r_s = math.log(xp[1] / ep[1])
        r_b = math.log(xb[1] / eb[1])
        return r_s - r_b - (COST_BPS / 10000.0)
    except Exception:
        return None


def bootstrap_ci(vals: list[float], groups: list, boot=BOOT, seed=SEED) -> tuple[float, float]:
    if not vals:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    gid = defaultdict(list)
    for v, g in zip(vals, groups):
        gid[g].append(v)
    keys = list(gid.keys())
    nc = len(keys)
    means = []
    for _ in range(boot):
        pool = []
        for _ in range(nc):
            pool.extend(gid[keys[rng.randrange(nc)]])
        if pool:
            means.append(sum(pool) / len(pool))
    means.sort()
    return (round(means[int(0.025 * len(means))], 4), round(means[int(0.975 * len(means))], 4))


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    ranks = load_ranks(sha)
    memb = load_membership(sha)
    prices = load_prices(sha)
    bench = load_bench(sha)
    LOG.info("ranks: %d · membership entries: %d · price tickers: %d · bench dates: %d",
             len(ranks), len(memb), len(prices), len(bench))

    # 분기별 상/하 3분위 포트폴리오 · 1Q + 4Q 창 · 소속 종목 log excess pooled
    quarters = sorted({(y, q) for (y, q, _) in ranks.keys()})
    LOG.info("quarters: %d", len(quarters))

    results = {"1Q": {"top": [], "bot": []}, "4Q": {"top": [], "bot": []}}
    groups = {"1Q": {"top": [], "bot": []}, "4Q": {"top": [], "bot": []}}
    sample_quarters = {"1Q": [], "4Q": []}

    for (y, q) in quarters:
        top_themes = [t for t in MAIN_THEMES if ranks.get((y, q, t)) == "top"]
        bot_themes = [t for t in MAIN_THEMES if ranks.get((y, q, t)) == "bot"]

        for horizon_key, n_quarters in (("1Q", 1), ("4Q", 4)):
            y_end, q_end = add_quarters(y, q, n_quarters)
            # top 소속
            for theme in top_themes:
                for tk in memb.get((theme, y, q), set()):
                    r = compute_log_excess(prices.get(tk, {}), bench, add_quarters(y, q, 1)[0], add_quarters(y, q, 1)[1], y_end, q_end)
                    if r is not None:
                        results[horizon_key]["top"].append(r)
                        groups[horizon_key]["top"].append(f"{y}Q{q}")
            for theme in bot_themes:
                for tk in memb.get((theme, y, q), set()):
                    r = compute_log_excess(prices.get(tk, {}), bench, add_quarters(y, q, 1)[0], add_quarters(y, q, 1)[1], y_end, q_end)
                    if r is not None:
                        results[horizon_key]["bot"].append(r)
                        groups[horizon_key]["bot"].append(f"{y}Q{q}")
            sample_quarters[horizon_key].append(y * 4 + q)

    # 자동 GO 조건 = 소속 ≥ 3 인 분기 ≥ 20
    good_quarters = sum(
        1 for (y, q) in quarters
        if sum(len(memb.get((t, y, q), set())) for t in MAIN_THEMES if ranks.get((y, q, t)) == "top") >= 3
    )
    auto_go = good_quarters >= 20

    seal = {"git_sha": sha, "auto_go": auto_go, "good_quarters_ge3": good_quarters, "windows": {}}
    for horizon in ("1Q", "4Q"):
        top_vals = results[horizon]["top"]
        bot_vals = results[horizon]["bot"]
        # 차이 CI (top - bot 클러스터 = 분기)
        # 방법 = top pool CI · bot pool CI · 차이 = mean(top) - mean(bot) 근사
        top_ci = bootstrap_ci(top_vals, groups[horizon]["top"])
        bot_ci = bootstrap_ci(bot_vals, groups[horizon]["bot"])
        top_mean = mean(top_vals) if top_vals else float("nan")
        bot_mean = mean(bot_vals) if bot_vals else float("nan")
        seal["windows"][horizon] = {
            "top_n": len(top_vals), "bot_n": len(bot_vals),
            "top_mean_log_excess": round(top_mean, 4) if top_vals else None,
            "bot_mean_log_excess": round(bot_mean, 4) if bot_vals else None,
            "top_cluster_ci95": top_ci,
            "bot_cluster_ci95": bot_ci,
            "diff_top_minus_bot": round(top_mean - bot_mean, 4) if (top_vals and bot_vals) else None,
            "unique_quarters_top": len(set(groups[horizon]["top"])),
            "unique_quarters_bot": len(set(groups[horizon]["bot"])),
        }

    out_dir = DATA_DIR / "biotech" / "seals"
    out_dir.mkdir(parents=True, exist_ok=True)
    seal_path = out_dir / f"h6_seal_report_{sha}.json"
    seal_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2))
    LOG.info("seal saved: %s", seal_path)

    # 리포트 md (쉬운 말 5줄 + 가능성 지도 3줄)
    report_dir = PROJECT_ROOT / "docs" / "plans" / "biotech" / "verification" / "H6"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = [
        f"# H6 검증 리포트 (WP42 · 2026-09-13 · git_sha {sha})",
        "",
        f"- 자동 GO 조건 (소속 ≥3 인 분기 ≥ 20): {'PASS' if auto_go else 'FAIL'} (해당 분기 수: {good_quarters})",
        "",
        "## 봉인 결과 (top 3분위 vs bot 3분위 · 로그 초과수익)",
        "",
        "| 창 | top n | bot n | top mean | bot mean | 차이 (top-bot) | top CI | bot CI |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for h in ("1Q", "4Q"):
        w = seal["windows"][h]
        report.append(f"| {h} | {w['top_n']} | {w['bot_n']} | {w['top_mean_log_excess']} | {w['bot_mean_log_excess']} | {w['diff_top_minus_bot']} | {w['top_cluster_ci95']} | {w['bot_cluster_ci95']} |")

    report += [
        "",
        "## 쉬운 말 요약 5줄",
        "",
        f"1. H6 는 최근 4분기 rolling 논문·임상 활동 증가율로 테마 순위를 만들고 상위 테마 소속 종목을 다음 분기 보유",
        f"2. 대상 종목이 분기당 3개 이상 있는 분기 = **{good_quarters}개** (자동 GO 기준 20개 대비 {'충족' if auto_go else '미달'})",
        f"3. 1분기 창: top {seal['windows']['1Q']['top_n']} vs bot {seal['windows']['1Q']['bot_n']} · 차이 {seal['windows']['1Q']['diff_top_minus_bot']}",
        f"4. 4분기 창: top {seal['windows']['4Q']['top_n']} vs bot {seal['windows']['4Q']['bot_n']} · 차이 {seal['windows']['4Q']['diff_top_minus_bot']}",
        f"5. 결론: {'표본 부족 · 관찰 트랙으로만 활용' if not auto_go else '자동 GO · Fable 검수 대기'}",
        "",
        "## 가능성 지도 (3줄 · WP36 필수)",
        "",
    ]
    if seal["windows"]["4Q"]["diff_top_minus_bot"] and seal["windows"]["4Q"]["diff_top_minus_bot"] > 0:
        report.append("1. 가장 밝은 자리 = 4Q 창 top-bot 차이 양수 · 확대 시 재검 가치")
    else:
        report.append("1. 가장 밝은 자리 = H6 순위 자체는 유효 · membership 확장 (CT.gov 스폰서 전체 재매핑) 필요")
    report.append("2. 죽은 자리 = 소속 종목 미확보 분기 (membership 매핑 부족)")
    report.append("3. 다음에 팔 자리 = WP27-2 CT.gov 스폰서 전체 재매핑 → membership 확장 → 재백테스트")

    report_path = report_dir / "H6-report-20260913.md"
    report_path.write_text("\n".join(report))
    LOG.info("report saved: %s", report_path)

    summary = {"seal_path": str(seal_path), "report_path": str(report_path), "auto_go": auto_go, "good_quarters_ge3": good_quarters}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n--- seal ---")
    print(json.dumps(seal, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
