"""WP69-3g · biotech 파이프 공용 경로 해석기.

조회 순서 (사용자 결정 · WP69-3e-α · 2026-09-20):
    BIOTECH_RUNTIME_DIR (env)  >  docs/plans/biotech/data (커밋 이식)  >  backend/data (로컬)

출력 폴더 원칙:
- 서버 실행 (RUNTIME 설정) 시 · 모든 산출은 RUNTIME 아래 (배포 reset --hard 무영향)
- 로컬 개발 (RUNTIME 미설정) 시 · 기존 backend/data 유지 (하위 호환)

**재발 방지**:
- 이 헬퍼 module 안 `PROJECT_ROOT`, `DATA_DIR`, `DATA_DIR_DOCS` 상수는 정의 목적으로만 사용
- 파이프 스크립트 (biotech_h*.py) 는 이 상수·경로 리터럴을 **직접 하드코딩하지 않음**
- test_biotech_secure_entry 가 이 규칙을 자동 검증
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
DATA_DIR_DOCS = PROJECT_ROOT / "docs" / "plans" / "biotech" / "data"

_rt = os.environ.get("BIOTECH_RUNTIME_DIR", "").strip()
RUNTIME_DIR: Path | None = Path(_rt) if _rt else None


def search_bases() -> list[Path]:
    """조회 순서 리스트 (존재 여부 무관 · 호출자가 exists 검사)."""
    bases: list[Path] = []
    if RUNTIME_DIR is not None:
        bases.append(RUNTIME_DIR)
    bases.append(DATA_DIR_DOCS)
    bases.append(DATA_DIR)
    return bases


def _iter_search(rel: str | None = None) -> list[Path]:
    """조회 대상 폴더 · rel 있으면 각 base 안 서브폴더까지."""
    if rel is None:
        return search_bases()
    return [b / rel for b in search_bases()]


def find(name: str, *, subdir: str | None = None) -> Path | None:
    """이름 완전 일치 조회 · subdir 지정 시 base/subdir/name."""
    for base in search_bases():
        p = (base / subdir / name) if subdir else (base / name)
        if p.exists():
            return p
    return None


def find_glob(pattern: str, *, subdir: str | None = None) -> Path | None:
    """glob 매칭 · 첫 base 안 매치가 있으면 최신 mtime 반환 · 없으면 다음 base."""
    for base in search_bases():
        target = (base / subdir) if subdir else base
        if not target.exists():
            continue
        hits = sorted(target.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if hits:
            return hits[0]
    return None


def out_dir(subdir: str) -> Path:
    """산출 폴더 · 서버 RUNTIME 우선 · 없으면 backend/data/biotech/<subdir>."""
    p = (RUNTIME_DIR / subdir) if RUNTIME_DIR else (DATA_DIR / "biotech" / subdir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def out_flat(name: str) -> Path:
    """flat 산출 파일 (subdir 없음) · 서버 RUNTIME 우선 · 없으면 backend/data 최상위."""
    root = RUNTIME_DIR if RUNTIME_DIR else DATA_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root / name


def today_kst_str(fmt: str = "%Y%m%d") -> str:
    """서버 로컬 KST 기준 오늘 날짜 문자열 (WP69-3h+ · UTC/KST 어긋남 방지)."""
    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime(fmt)


def data_sha_auto(anchor_pattern: str = "h3_targets_v2_*.csv") -> str:
    """anchor 파일에서 sha 추출 · search_bases 순회 · 첫 매치."""
    import re
    for base in search_bases():
        if not base.exists():
            continue
        hits = sorted(base.glob(anchor_pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if hits:
            m = re.search(r"_([a-f0-9]{7,40})\.csv$", hits[0].name)
            if m:
                return m.group(1)
    return ""
