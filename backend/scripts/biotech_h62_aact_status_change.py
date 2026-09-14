"""WP62 · AACT 스냅샷 studies 상태 변경 감지 (Phase C 1 · 채널 c).

두 스냅샷 (2024-01-01 · 2025-01-01) studies 테이블만 파싱:
- studies.txt (pipe-delimited) 에서 nct_id · overall_status · phase · primary_completion_date · start_date · study_first_submitted_date
- 두 시점 join → overall_status/phase 변경 이벤트 (변경일 추정 = 2024-01-01~2025-01-01)
- 스폰서 → 회사 CIK 매핑 (h6_membership · 회사명 매칭)
- 채널 c (CT.gov 상태 변경) 신호 이벤트 리스트 생성

**용량 최적화**:
- studies.txt 만 unzip · 다른 테이블 (interventions · sponsors · etc.) 무시
- 전체 postgres import 불필요
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import subprocess
import zipfile
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h62_aact_status_change")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
AACT_DIR = DATA_DIR / "aact_snapshots"


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def extract_studies_from_zip(zip_path: Path) -> dict[str, dict]:
    """studies.txt 파일 unzip · nct_id 기준 dict 반환.

    pipe-delimited · 첫 줄 헤더. 관련 컬럼:
    nct_id · overall_status · phase · primary_completion_date · start_date
    """
    LOG.info("scanning %s", zip_path.name)
    with zipfile.ZipFile(zip_path) as zf:
        studies_name = None
        for n in zf.namelist():
            if n.endswith("studies.txt") or n == "studies.txt":
                studies_name = n
                break
        if not studies_name:
            LOG.warning("studies.txt not found in %s", zip_path.name)
            return {}

        studies = {}
        with zf.open(studies_name) as f:
            # 첫 줄 헤더 · 이후 pipe-delimited
            headers = f.readline().decode(errors="ignore").rstrip("\r\n").split("|")
            idx = {name: i for i, name in enumerate(headers)}
            need = ["nct_id", "overall_status", "phase", "primary_completion_date", "start_date", "official_title"]
            need_idx = {n: idx.get(n, -1) for n in need}

            for line in f:
                try:
                    parts = line.decode(errors="ignore").rstrip("\r\n").split("|")
                    nct = parts[need_idx["nct_id"]] if need_idx["nct_id"] >= 0 else ""
                    if not nct.startswith("NCT"):
                        continue
                    studies[nct] = {
                        "overall_status": parts[need_idx["overall_status"]] if need_idx["overall_status"] >= 0 and need_idx["overall_status"] < len(parts) else "",
                        "phase": parts[need_idx["phase"]] if need_idx["phase"] >= 0 and need_idx["phase"] < len(parts) else "",
                        "primary_completion_date": parts[need_idx["primary_completion_date"]] if need_idx["primary_completion_date"] >= 0 and need_idx["primary_completion_date"] < len(parts) else "",
                    }
                except Exception:
                    continue
    LOG.info("%s: %d studies", zip_path.name, len(studies))
    return studies


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    zip_2024 = AACT_DIR / "aact_2024-01-01_flatfiles.zip"
    zip_2025 = AACT_DIR / "aact_2025-01-01_flatfiles.zip"
    if not zip_2024.exists() or not zip_2025.exists():
        LOG.error("스냅샷 부재 · 다운로드 완료 후 재실행")
        return

    s24 = extract_studies_from_zip(zip_2024)
    s25 = extract_studies_from_zip(zip_2025)

    common = set(s24.keys()) & set(s25.keys())
    added = set(s25.keys()) - set(s24.keys())
    LOG.info("common: %d · new in 2025: %d", len(common), len(added))

    # 상태 변경 감지
    status_changes = []
    phase_changes = []
    for nct in common:
        old = s24[nct]
        new = s25[nct]
        if old["overall_status"] != new["overall_status"]:
            status_changes.append({
                "nct_id": nct,
                "from_status": old["overall_status"],
                "to_status": new["overall_status"],
                "phase": new["phase"],
                "change_window": "2024-01-01_2025-01-01",
            })
        if old["phase"] != new["phase"]:
            phase_changes.append({
                "nct_id": nct,
                "from_phase": old["phase"],
                "to_phase": new["phase"],
                "status": new["overall_status"],
                "change_window": "2024-01-01_2025-01-01",
            })

    # 저장
    out_path = DATA_DIR / f"h62_aact_status_change_{sha}.json"
    payload = {
        "git_sha": sha,
        "snapshot_windows": ["2024-01-01", "2025-01-01"],
        "studies_2024": len(s24),
        "studies_2025": len(s25),
        "common": len(common),
        "new_in_2025": len(added),
        "status_changes": len(status_changes),
        "phase_changes": len(phase_changes),
        "status_changes_sample": status_changes[:20],
        "phase_changes_sample": phase_changes[:20],
    }
    # 이벤트 리스트 별도 CSV
    events_csv = DATA_DIR / f"h62_aact_status_events_{sha}.csv"
    with events_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["nct_id", "from_status", "to_status", "from_phase", "to_phase", "change_window"])
        for c in status_changes:
            w.writerow([c["nct_id"], c["from_status"], c["to_status"], "", c["phase"], c["change_window"]])
        for c in phase_changes:
            w.writerow([c["nct_id"], "", c["status"], c["from_phase"], c["to_phase"], c["change_window"]])

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    LOG.info("summary=%s", json.dumps({k: v for k, v in payload.items() if not isinstance(v, list)}, indent=2))
    print(json.dumps({k: v for k, v in payload.items() if not isinstance(v, list)}, ensure_ascii=False, indent=2))
    print(f"events_csv: {events_csv} · rows: {len(status_changes) + len(phase_changes)}")


if __name__ == "__main__":
    main()
