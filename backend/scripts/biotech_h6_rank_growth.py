"""WP22 · H6 순위 변화율 전환 · 사전 커밋.

신호 = 테마별 EDAT 논문 수와 CT.gov 신규 등록 수의 전년 동기 대비 증가율.
- growth_pubmed(theme,y,q) = (edat(y,q) - edat(y-1,q)) / max(edat(y-1,q), 1)
- growth_ct(theme,y,q) = (ct(y,q) - ct(y-1,q)) / max(ct(y-1,q), 1)
- 분기 내 8세트 (주 6 + 대조군 2) 간 z-점수 (PubMed 60% · CT 40%) → 3분위
- 수준 기반 순위표는 이력 보존 (h6_rank_add7af7.csv 그대로 유지 · 별도 파일)
- 대조군 2 는 순위 산정 제외 · 주 6 만 3분위 (n=6 → top 2)
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
LOG = logging.getLogger("biotech_h6_rank_growth")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

MAIN = [
    "obesity_glp1", "hair_loss", "longevity_rejuvenation",
    "meal_replacement_metabolic", "hibernation_hypothermia", "cognitive_memory",
]
CONTROLS = ["control_nash", "control_amyloid"]
ALL_THEMES = MAIN + CONTROLS


def git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def zscore(vals: list[float]) -> list[float]:
    if not vals:
        return []
    m = mean(vals)
    s = pstdev(vals) or 1.0
    return [(v - m) / s for v in vals]


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    LOG.info("git_sha=%s", sha)

    edat_path = DATA_DIR / f"h6_theme_edat_{sha}.csv"
    memb_path = DATA_DIR / f"h6_membership_{sha}.csv"

    # EDAT per (theme, y, q)
    edat: dict[tuple[str, int, int], int] = {}
    with edat_path.open() as f:
        for r in csv.DictReader(f):
            try:
                edat[(r["theme"], int(r["year"]), int(r["quarter"]))] = int(r["pubmed_edat"])
            except Exception:
                continue

    # CT.gov new registrations per (theme, y, q) · 스폰서 raw 카운트로 근사
    ct: dict[tuple[str, int, int], int] = {}
    with memb_path.open() as f:
        for r in csv.DictReader(f):
            try:
                ct[(r["theme"], int(r["year"]), int(r["quarter"]))] = int(r["sponsors_raw_count"])
            except Exception:
                continue

    quarters = sorted({(y, q) for (_, y, q) in list(edat.keys()) + list(ct.keys())})
    LOG.info("quarters loaded: %d", len(quarters))

    # 증가율 산출 (전년 동기 대비)
    growth = {}  # (theme, y, q) → (g_pm, g_ct)
    for theme in ALL_THEMES:
        for (y, q) in quarters:
            pm = edat.get((theme, y, q))
            pm_prev = edat.get((theme, y - 1, q))
            ct_v = ct.get((theme, y, q))
            ct_prev = ct.get((theme, y - 1, q))
            if pm is None or pm_prev is None or ct_v is None or ct_prev is None:
                continue
            g_pm = (pm - pm_prev) / max(pm_prev, 1)
            g_ct = (ct_v - ct_prev) / max(ct_prev, 1)
            growth[(theme, y, q)] = (g_pm, g_ct)

    # 분기별 순위표 (주 6 만)
    rank_rows = []
    first_top_by_theme: dict[str, str] = {}
    prev_top: set[str] = set()
    switches_per_quarter = []
    for (y, q) in quarters:
        pm_vals, ct_vals, themes = [], [], []
        for theme in MAIN:
            if (theme, y, q) in growth:
                g_pm, g_ct = growth[(theme, y, q)]
                pm_vals.append(g_pm)
                ct_vals.append(g_ct)
                themes.append(theme)
        if len(themes) < 3:
            continue
        z_pm = zscore(pm_vals)
        z_ct = zscore(ct_vals)
        combined = [(themes[i], 0.6 * z_pm[i] + 0.4 * z_ct[i]) for i in range(len(themes))]
        combined.sort(key=lambda x: -x[1])
        n = len(combined)
        top_n = max(1, n // 3)
        top_set = {t for t, _ in combined[:top_n]}
        for rank_idx, (theme, score) in enumerate(combined, 1):
            tercile = "top" if theme in top_set else ("bot" if rank_idx > n - top_n else "mid")
            rank_rows.append({
                "year": y, "quarter": q, "theme": theme,
                "growth_pm": round(dict(zip(themes, pm_vals))[theme], 4),
                "growth_ct": round(dict(zip(themes, ct_vals))[theme], 4),
                "z_growth_pm": round(z_pm[themes.index(theme)], 3),
                "z_growth_ct": round(z_ct[themes.index(theme)], 3),
                "score_60pm_40ct": round(score, 3),
                "rank": rank_idx,
                "tercile": tercile,
            })
            if theme in top_set and theme not in first_top_by_theme:
                first_top_by_theme[theme] = f"{y}Q{q}"
        added = top_set - prev_top
        switches_per_quarter.append({"quarter": f"{y}Q{q}", "switched_in": len(added), "top_size": len(top_set)})
        prev_top = top_set

    out_path = DATA_DIR / f"h6_rank_growth_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "year", "quarter", "theme",
            "growth_pm", "growth_ct", "z_growth_pm", "z_growth_ct",
            "score_60pm_40ct", "rank", "tercile",
        ])
        w.writeheader()
        w.writerows(rank_rows)

    total_switches = sum(s["switched_in"] for s in switches_per_quarter[1:])
    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "quarters_ranked": len(switches_per_quarter),
        "obesity_glp1_first_top_quarter": first_top_by_theme.get("obesity_glp1"),
        "first_top_by_theme": first_top_by_theme,
        "total_switch_in_top_after_first": total_switches,
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
