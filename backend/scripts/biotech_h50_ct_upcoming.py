"""WP50 · A 상태 (뉴스 예정) 판정 · **WP69-3d 재작성**.

CT.gov v2 서버 IP 차단 (WP69-3b 실측 403) → **AACT 주간 스냅샷 JSON 참조** (사용자 결정 2026-09-20).

절차:
- ctgov_snapshot.json 로드 (BIOTECH_RUNTIME_DIR → docs → backend/data 순 · WP69-3b _search_dirs 정합)
- ticker → 예정 primary_completion (days_to > 0) 최근접 1건 매핑
- candidates_v2 → v3: time_state_v50 · state_note_v50 · ctgov_upcoming_count · adcom_upcoming_count 컬럼 추가
- JSON 생성 7일 초과 시 "예정일 자료 오래됨" 경고 노트 (파이프는 진행 · state_note_v50 에 stale 표기)

**보안·규칙**:
- CT.gov API 호출 없음 (외부 네트워크 접근 0)
- biotech_sec_common 상수 참조 불필요 (네트워크 안 씀)
- 우회 금지 (사용자 결정 β·δ 제외)

**호환**:
- 산출 컬럼 스키마는 기존 v3 CSV 와 동일 (frontend/api 무회귀)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import os
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG = logging.getLogger("biotech_h50_ct_upcoming")

# WP69-3g · 경로는 공용 헬퍼 _biotech_paths 사용
from backend.scripts import _biotech_paths as _P
PROJECT_ROOT = _P.PROJECT_ROOT
DATA_DIR = _P.DATA_DIR
RUNTIME_DIR = _P.RUNTIME_DIR
FALLBACK_DIR = _P.DATA_DIR_DOCS

STALE_DAYS = 7  # JSON 이 7일 초과 시 경고


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def _find_snapshot() -> Path | None:
    """ctgov_snapshot.json 조회 · RUNTIME > docs > backend/data."""
    candidates = []
    if RUNTIME_DIR is not None:
        candidates.append(RUNTIME_DIR / "ctgov_snapshot.json")
    candidates.append(FALLBACK_DIR / "ctgov_snapshot.json")
    candidates.append(DATA_DIR / "ctgov_snapshot.json")
    for p in candidates:
        if p.exists():
            return p
    return None


def _find_candidates_v2(today_str: str) -> Path | None:
    """candidates 입력 · v2 > v1 (suffix 없음) 순 · WP69-3h fallback (서버 daily 는 v1 생성)."""
    dirs = []
    if RUNTIME_DIR is not None:
        dirs.append(RUNTIME_DIR / "candidates")
    dirs.append(FALLBACK_DIR)
    dirs.append(DATA_DIR / "biotech" / "candidates")
    # v2 우선 → v1 fallback (같은 스키마 · h48v3_candidates 산출 파일)
    for suffix in ("v2_", ""):
        for d in dirs:
            p = d / f"biotech_candidates_{suffix}{today_str}.csv"
            if p.exists():
                return p
    return None


def _out_path(today_str: str) -> Path:
    """산출 위치 · RUNTIME 우선 · 없으면 backend/data."""
    if RUNTIME_DIR is not None:
        (RUNTIME_DIR / "candidates").mkdir(parents=True, exist_ok=True)
        return RUNTIME_DIR / "candidates" / f"biotech_candidates_v3_{today_str}.csv"
    return DATA_DIR / "biotech" / "candidates" / f"biotech_candidates_v3_{today_str}.csv"


def load_adcom_future(sha: str) -> dict[str, list[dict]]:
    p = DATA_DIR / f"h1a_events_v2_{sha}.csv"
    if not p.exists():
        return {}
    today = datetime.now(timezone.utc).date()
    out: dict[str, list[dict]] = defaultdict(list)
    with p.open() as f:
        for r in csv.DictReader(f):
            md = (r.get("meeting_date") or "").strip()
            if not md:
                continue
            try:
                d = datetime.strptime(md, "%Y-%m-%d").date()
            except Exception:
                continue
            if d > today:
                tk = (r.get("mapped_ticker") or "").strip()
                if tk:
                    out[tk].append({
                        "meeting_date": md,
                        "days_to": (d - today).days,
                        "committee": r.get("committee", ""),
                    })
    return out


def _build_ct_map(snapshot_path: Path) -> tuple[dict[str, list[dict]], str, bool]:
    """ticker → [{nct, date, days_to, phases, status}, ...] · 오래됨 여부."""
    data = json.loads(snapshot_path.read_text())
    generated = data.get("generated_utc") or ""
    snapshot_date = data.get("aact_snapshot_date") or ""
    try:
        gen_dt = datetime.fromisoformat(generated.replace("Z", "+00:00")) if generated else None
    except Exception:
        gen_dt = None
    stale = False
    if gen_dt:
        age_days = (datetime.now(timezone.utc) - gen_dt).days
        stale = age_days > STALE_DAYS
    ct_map: dict[str, list[dict]] = defaultdict(list)
    for m in data.get("matches", []):
        d = m.get("days_to")
        if d is None or d < 0:
            continue
        ct_map[m.get("ticker", "")].append({
            "nct": m.get("nct_id", ""),
            "date": m.get("primary_completion_date", "")[:10],
            "days_to": d,
            "phases": m.get("phase", ""),
            "status": m.get("overall_status", ""),
        })
    # ticker 별 days_to 오름차순
    for tk in ct_map:
        ct_map[tk].sort(key=lambda x: x["days_to"])
    return ct_map, snapshot_date, stale


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    cands_path = _find_candidates_v2(today_str)
    if not cands_path:
        LOG.error("candidates_v2_%s.csv 없음 · biotech_h48v3_candidates 선행 필요", today_str)
        raise SystemExit(50)
    cands = list(csv.DictReader(cands_path.open()))
    LOG.info("candidates v2: %d · %s", len(cands), cands_path)

    snapshot = _find_snapshot()
    if not snapshot:
        LOG.error("ctgov_snapshot.json 없음 · biotech_h69_aact_weekly 선행 필요")
        raise SystemExit(51)
    ct_map, snapshot_date, stale = _build_ct_map(snapshot)
    LOG.info("ctgov_snapshot · date=%s · ticker %d · stale=%s", snapshot_date, len(ct_map), stale)

    adcom_future = load_adcom_future(sha)

    rows_out = []
    dist: Counter = Counter()
    for c in cands:
        tk = (c.get("ticker") or "").strip()

        adcom_hits = adcom_future.get(tk, [])
        adcom_note = ""
        if adcom_hits:
            first = min(adcom_hits, key=lambda x: x["days_to"])
            adcom_note = f"자문위 회의 D-{first['days_to']} ({first['meeting_date']} · {first['committee']})"

        ct_hits = ct_map.get(tk, [])
        ct_note = ""
        if ct_hits:
            ct_first = ct_hits[0]
            ct_note = f"CT.gov (AACT {snapshot_date}) {ct_first['nct']} 완료 예정 D-{ct_first['days_to']} ({ct_first['date']} · {ct_first['phases']})"

        if adcom_hits or ct_hits:
            new_state = "A"
            parts = [x for x in [adcom_note, ct_note] if x]
            note = " || ".join(parts)
        else:
            new_state = c.get("time_state", "C")
            note = c.get("state_note", "")

        # stale 경고 병기 (파이프는 진행)
        if stale and (adcom_hits or ct_hits):
            note = f"⚠ 예정일 자료 {STALE_DAYS}일 초과 · " + note

        dist[new_state] += 1

        row = dict(c)
        row["time_state_v50"] = new_state
        row["state_note_v50"] = note
        row["ctgov_upcoming_count"] = len(ct_hits)
        row["adcom_upcoming_count"] = len(adcom_hits)
        rows_out.append(row)

    out_path = _out_path(today_str)
    fields = list(rows_out[0].keys()) if rows_out else []
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows_out)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "input": len(cands),
        "output": len(rows_out),
        "distribution": dict(dist),
        "ctgov_snapshot_date": snapshot_date,
        "ctgov_snapshot_stale": stale,
        "ctgov_tickers": len(ct_map),
        "note": "A 상태 = AACT snapshot (CT.gov 대체) 미래 primary_completion OR 자문위 회의 미래 · CT.gov API 호출 없음 (서버 IP 차단 우회 없음)",
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
