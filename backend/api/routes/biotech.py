"""Biotech Radar 라우터 (WP69-1 · 2026-09-14 · admin 전용 · 읽기 전용).

**설계 원칙 (SITE-ANALYSIS.md §2 준수)**:
- 기존 응용 무접촉 · biotech 이름공간 격리
- docs/plans/biotech/**/*.md 를 읽어 HTML + 메타 JSON 반환
- 기존 admin 인증 (require_sniper_token) 재사용
- 파일 없음 = 404 · 캐시 60s (in-memory · TTL)

**경로 (모두 admin 세션 필요)**:
- GET /api/v1/biotech/radar          → 최신 watchlist/radar-v1.X-*.md
- GET /api/v1/biotech/rumor?date=... → rumor-daily/YYYY-MM-DD.md
- GET /api/v1/biotech/rumor/dates    → 사용 가능한 날짜 목록
- GET /api/v1/biotech/status         → STATUS.md
- GET /api/v1/biotech/glossary       → GLOSSARY.md
- GET /api/v1/biotech/final          → PHASE-A-FINAL.md
"""
from __future__ import annotations

import glob
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import markdown as md_lib
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.api.auth import require_sniper_token

router = APIRouter()

# 프로젝트 루트 = backend/api/routes/biotech.py → parents[3]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DOCS = PROJECT_ROOT / "docs" / "plans" / "biotech"

# 캐시 (경로 → (mtime, html, cached_at))
_CACHE: dict[str, tuple[float, str, float]] = {}
CACHE_TTL_SEC = 60.0


class BiotechDoc(BaseModel):
    """md 문서 반환 스키마."""
    path: str            # 상대 경로
    title: str           # 문서 제목 (# 첫 줄)
    generated_utc: str   # 생성 시각 (mtime)
    html: str            # 렌더된 HTML
    raw_md_size: int     # 원본 크기


class RumorDates(BaseModel):
    dates: list[str]
    latest: Optional[str]


def _render(path: Path) -> BiotechDoc:
    """md 파일 → HTML + 메타 · TTL 캐시."""
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"파일 없음: {path.name}")

    key = str(path)
    mtime = path.stat().st_mtime
    now = time.time()
    cached = _CACHE.get(key)
    if cached and cached[0] == mtime and (now - cached[2]) < CACHE_TTL_SEC:
        html = cached[1]
    else:
        md_text = path.read_text()
        html = md_lib.markdown(md_text, extensions=["tables", "fenced_code"])
        _CACHE[key] = (mtime, html, now)

    md_text_for_title = path.read_text()
    title_match = re.search(r"^#\s+(.+)", md_text_for_title, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else path.stem

    return BiotechDoc(
        path=str(path.relative_to(PROJECT_ROOT)),
        title=title,
        generated_utc=datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
        html=html,
        raw_md_size=path.stat().st_size,
    )


@router.get("/radar", response_model=BiotechDoc)
async def get_radar(_admin: str = Depends(require_sniper_token)) -> BiotechDoc:
    """최신 radar 리스트 (watchlist/radar-v1.X-YYYYMMDD.md 중 최신)."""
    matches = sorted(glob.glob(str(DOCS / "watchlist" / "radar-v1.*-*.md")))
    if not matches:
        raise HTTPException(status_code=404, detail="radar 파일 없음")
    return _render(Path(matches[-1]))


@router.get("/rumor/dates", response_model=RumorDates)
async def get_rumor_dates(_admin: str = Depends(require_sniper_token)) -> RumorDates:
    """사용 가능한 rumor 날짜 목록 (최신순)."""
    files = sorted(glob.glob(str(DOCS / "rumor-daily" / "*.md")))
    dates = [Path(f).stem for f in files if re.match(r"\d{4}-\d{2}-\d{2}", Path(f).stem)]
    dates.sort(reverse=True)
    return RumorDates(dates=dates, latest=dates[0] if dates else None)


@router.get("/rumor", response_model=BiotechDoc)
async def get_rumor(
    date: Optional[str] = Query(None, description="YYYY-MM-DD · 미지정 시 최신"),
    _admin: str = Depends(require_sniper_token),
) -> BiotechDoc:
    """rumor daily 리포트 · date 지정 없으면 최신."""
    files = sorted(glob.glob(str(DOCS / "rumor-daily" / "*.md")))
    if not files:
        raise HTTPException(status_code=404, detail="rumor daily 없음")
    dates = [Path(f).stem for f in files if re.match(r"\d{4}-\d{2}-\d{2}", Path(f).stem)]
    dates.sort(reverse=True)
    pick = date or dates[0]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", pick):
        raise HTTPException(status_code=400, detail="date 형식 YYYY-MM-DD")
    target = DOCS / "rumor-daily" / f"{pick}.md"
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"{pick}.md 없음 · /rumor/dates 로 사용 가능한 날짜 확인")
    return _render(target)


@router.get("/status", response_model=BiotechDoc)
async def get_status(_admin: str = Depends(require_sniper_token)) -> BiotechDoc:
    """STATUS.md (상태판 · WP57 자동 갱신)."""
    return _render(DOCS / "STATUS.md")


@router.get("/glossary", response_model=BiotechDoc)
async def get_glossary(_admin: str = Depends(require_sniper_token)) -> BiotechDoc:
    """GLOSSARY.md (용어집)."""
    return _render(DOCS / "GLOSSARY.md")


@router.get("/final", response_model=BiotechDoc)
async def get_final(_admin: str = Depends(require_sniper_token)) -> BiotechDoc:
    """PHASE-A-FINAL.md (Phase A 종결본 · 2026-09-14 동결)."""
    return _render(DOCS / "PHASE-A-FINAL.md")
