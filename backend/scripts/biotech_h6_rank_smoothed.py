"""WP22-2 · H6 순위 잡음 억제 (사전 커밋).

신호 = 직전 4분기 합계의 전년 동기 대비 증가율.
- rolling_sum_4q(theme, y, q) = sum(edat[y,q-3..q]) · CT 동일 (분기 인덱스 -3..0)
- growth = (rolling_sum_now - rolling_sum_prev_year) / max(rolling_sum_prev_year, 1)
- z-점수 60/40 → 3분위
- 기존 단일 분기 증가율 (h6_rank_growth) 과 비만 진입 분기·교체 수 비교
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import subprocess
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h6_rank_smoothed")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

MAIN = [
    "obesity_glp1", "hair_loss", "longevity_rejuvenation",
    "meal_replacement_metabolic", "hibernation_hypothermia", "cognitive_memory",
]


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def zscore(vals: list[float]) -> list[float]:
    if not vals:
        return []
    m = mean(vals)
    s = pstdev(vals) or 1.0
    return [(v - m) / s for v in vals]


def qkey(y: int, q: int) -> int:
    return y * 4 + (q - 1)


def qkey_inv(k: int) -> tuple[int, int]:
    return k // 4, k % 4 + 1


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    edat: dict[tuple[str, int, int], int] = {}
    with (DATA_DIR / f"h6_theme_edat_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            try:
                edat[(r["theme"], int(r["year"]), int(r["quarter"]))] = int(r["pubmed_edat"])
            except Exception:
                continue

    ct: dict[tuple[str, int, int], int] = {}
    with (DATA_DIR / f"h6_membership_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            try:
                ct[(r["theme"], int(r["year"]), int(r["quarter"]))] = int(r["sponsors_raw_count"])
            except Exception:
                continue

    quarters = sorted({(y, q) for (_, y, q) in list(edat.keys()) + list(ct.keys())})

    # rolling 4q sum
    def rolling(source: dict, theme: str, y: int, q: int) -> int | None:
        base = qkey(y, q)
        total = 0
        for offset in range(4):
            yy, qq = qkey_inv(base - offset)
            v = source.get((theme, yy, qq))
            if v is None:
                return None
            total += v
        return total

    rows = []
    first_top: dict[str, str] = {}
    prev_top: set[str] = set()
    switches = []
    for (y, q) in quarters:
        pm_vals, ct_vals, present = [], [], []
        for theme in MAIN:
            pm_now = rolling(edat, theme, y, q)
            pm_prev = rolling(edat, theme, y - 1, q)
            ct_now = rolling(ct, theme, y, q)
            ct_prev = rolling(ct, theme, y - 1, q)
            if None in (pm_now, pm_prev, ct_now, ct_prev):
                continue
            g_pm = (pm_now - pm_prev) / max(pm_prev, 1)
            g_ct = (ct_now - ct_prev) / max(ct_prev, 1)
            pm_vals.append(g_pm)
            ct_vals.append(g_ct)
            present.append(theme)
        if len(present) < 3:
            continue
        z_pm = zscore(pm_vals)
        z_ct = zscore(ct_vals)
        combined = [(present[i], 0.6 * z_pm[i] + 0.4 * z_ct[i]) for i in range(len(present))]
        combined.sort(key=lambda x: -x[1])
        n = len(combined)
        top_n = max(1, n // 3)
        top_set = {t for t, _ in combined[:top_n]}
        for rank_idx, (theme, score) in enumerate(combined, 1):
            tercile = "top" if theme in top_set else ("bot" if rank_idx > n - top_n else "mid")
            rows.append({
                "year": y, "quarter": q, "theme": theme,
                "smooth_growth_pm": round(dict(zip(present, pm_vals))[theme], 4),
                "smooth_growth_ct": round(dict(zip(present, ct_vals))[theme], 4),
                "score_60pm_40ct": round(score, 3),
                "rank": rank_idx, "tercile": tercile,
            })
            if theme in top_set and theme not in first_top:
                first_top[theme] = f"{y}Q{q}"
        added = top_set - prev_top
        switches.append({"quarter": f"{y}Q{q}", "switched_in": len(added), "top_size": len(top_set)})
        prev_top = top_set

    out_path = DATA_DIR / f"h6_rank_smoothed_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["year", "quarter", "theme", "smooth_growth_pm", "smooth_growth_ct", "score_60pm_40ct", "rank", "tercile"])
        w.writeheader()
        w.writerows(rows)

    # 기존 h6_rank_growth 와 비교
    old = list(csv.DictReader((DATA_DIR / f"h6_rank_growth_{sha}.csv").open()))
    old_first = {}
    old_top_prev = set()
    old_switches = 0
    for r in old:
        if r["tercile"] == "top" and r["theme"] not in old_first:
            old_first[r["theme"]] = f"{r['year']}Q{r['quarter']}"

    total_switch_after_first = sum(s["switched_in"] for s in switches[1:])
    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "quarters_ranked": len(switches),
        "single_quarter_growth": {
            "obesity_glp1_first_top": old_first.get("obesity_glp1"),
        },
        "smoothed_4q_growth": {
            "obesity_glp1_first_top": first_top.get("obesity_glp1"),
            "first_top_by_theme": first_top,
            "total_switch_after_first_top": total_switch_after_first,
        },
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
