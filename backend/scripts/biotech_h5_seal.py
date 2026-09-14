"""WP21-2 봉인 보고 · h5_backtest dry-run 표본 → bootstrap 클러스터+iid CI → 봉인 결과.

자동 GO 후에만 실행 (호출자 검증).

봉인 항목 (창별 · A/B 병기):
- n (표본 이벤트 수 · 병합 후)
- 클러스터 수 (촉매 날짜 · unique_catalyst_dates)
- mean net excess
- 클러스터 bootstrap 95% CI (촉매 날짜 재추출 · 1차)
- iid bootstrap 95% CI (이벤트 재추출 · 병기)
- 히트율 (net > 0 비율)
- 부호 (+/-)
- 기계 판정 (mean ≥ 임계 AND 클러스터 CI 하한 > 0)
- git_sha

임계 (h5_params · 3구간): pre +2% · imm +3% · sus +5%
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts import biotech_h5_backtest as bt

import csv
import json
import logging
import random
import subprocess
from collections import defaultdict
from pathlib import Path
from statistics import mean

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h5_seal")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

WINDOWS = ["pre_D-5_D-1", "imm_D+1_D+5", "sus_D+1_D+20"]
THRESHOLDS = {"pre_D-5_D-1": 0.02, "imm_D+1_D+5": 0.03, "sus_D+1_D+20": 0.05}
BOOT = 10_000
SEED = 42


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_v3_catalyst_grade(sha: str) -> dict[tuple[str, str, str], str]:
    """(app_no, sub_no, sub_date) → grade A/B."""
    p = DATA_DIR / f"h5_catalysts_v3_{sha}.csv"
    out = {}
    with p.open() as f:
        for r in csv.DictReader(f):
            k = (r["application_number"], r["submission_number"], r["submission_status_date_us"])
            out[k] = r["grade"]
    return out


def bootstrap_mean_ci(vals: list[float], groups: list[str] | None, boot: int, seed: int) -> tuple[float, float]:
    """95% CI · groups 제공 시 클러스터 재추출 · 아니면 iid.

    반환 (lo, hi).
    """
    if not vals:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    if groups is None:
        n = len(vals)
        means = []
        for _ in range(boot):
            sample = [vals[rng.randrange(n)] for _ in range(n)]
            means.append(sum(sample) / n)
    else:
        # 클러스터: unique 그룹 뽑아 각 그룹의 이벤트들을 통째로 재추출
        gid = defaultdict(list)
        for v, g in zip(vals, groups):
            gid[g].append(v)
        keys = list(gid.keys())
        nc = len(keys)
        means = []
        for _ in range(boot):
            pool = []
            for _ in range(nc):
                key = keys[rng.randrange(nc)]
                pool.extend(gid[key])
            if pool:
                means.append(sum(pool) / len(pool))
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[int(0.975 * len(means))]
    return (lo, hi)


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    # dry-run 재실행 (병합 후 표본 얻기)
    dry = bt.run_dry_run(sha)
    LOG.info("dry_run summary: %s", json.dumps(dry, ensure_ascii=False, indent=2))

    # 병합 후 표본 로드
    v2_path = Path(dry.get("sample_csv_v2", ""))
    if not v2_path.exists():
        LOG.error("sample_v2 not found")
        return
    rows = list(csv.DictReader(v2_path.open()))
    LOG.info("merged sample rows: %d", len(rows))

    grade_map = load_v3_catalyst_grade(sha)

    seal = {"git_sha": sha, "windows": {}}
    for win in WINDOWS:
        seal["windows"][win] = {}
        for grade_key in ("ALL", "A", "B"):
            per = []
            groups = []
            for r in rows:
                status = r.get(f"{win}_status", "")
                if status != "ok":
                    continue
                app = r.get("app_no", "")
                sub = r.get("sub_no", "")
                d_us = ""  # v3-catalysts 매핑 필요 · d_day_kst 로 근사
                dday = r.get("event_d_day", "")
                # grade 매핑 · (app, sub, ??)  → grade_map 은 (app, sub, sub_date) 키
                # sample_v2 에는 sub_date 없음 · dday 로부터 역추정 불가 · grade_map 재구성 (app, sub) 로 축약
                # → grade_by_app_sub 사전 생성 (main 밖에서 재사용)
                grade = None
                for k, g in grade_map.items():
                    if k[0] == app and k[1] == sub:
                        grade = g
                        break
                if grade_key != "ALL" and grade != grade_key:
                    continue
                try:
                    v = float(r.get(f"{win}_net_excess", ""))
                except Exception:
                    continue
                per.append(v)
                groups.append(dday)
            if not per:
                seal["windows"][win][grade_key] = {"n": 0}
                continue
            m = mean(per)
            hits = sum(1 for v in per if v > 0)
            clu_lo, clu_hi = bootstrap_mean_ci(per, groups, BOOT, SEED)
            iid_lo, iid_hi = bootstrap_mean_ci(per, None, BOOT, SEED)
            unique_clusters = len(set(groups))
            thr = THRESHOLDS[win]
            alpha = (m >= thr) and (clu_lo > 0)
            seal["windows"][win][grade_key] = {
                "n": len(per),
                "unique_catalyst_dates": unique_clusters,
                "mean_net_excess": round(m, 4),
                "cluster_ci95_lo": round(clu_lo, 4),
                "cluster_ci95_hi": round(clu_hi, 4),
                "iid_ci95_lo": round(iid_lo, 4),
                "iid_ci95_hi": round(iid_hi, 4),
                "hit_rate": round(hits / len(per), 3),
                "sign": "+" if m > 0 else ("-" if m < 0 else "0"),
                "threshold": thr,
                "alpha_pass_machine": alpha,
            }

    seal["fable_review"] = "pending"
    seal["disclaimer"] = "본 실행은 자동 GO 5/5 충족 확인 후 · Fable 검수 대기"

    out_path = DATA_DIR / f"h5_seal_report_{sha}.json"
    out_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2))
    LOG.info("seal saved: %s", out_path)
    print(json.dumps(seal, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
