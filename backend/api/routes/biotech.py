"""Biotech Radar 라우터 (WP69-2b · 2026-09-18 · admin 전용 · 읽기 전용 · 지연 import).

**설계 원칙 (SITE-ANALYSIS.md §2 준수 + WP69-2b 본체 보호)**:
- 기존 응용 무접촉 · biotech 이름공간 격리
- docs/plans/biotech/**/*.md 를 읽어 HTML + 메타 JSON 반환
- 기존 admin 인증 (require_sniper_token) 재사용
- 파일 없음 = 404 · 캐시 60s (in-memory · TTL)
- **markdown 은 핸들러 내부 지연 import** · 부재 시 text/plain 원문 md 반환 + 경고 로그 (본체 무영향)

**경로 (모두 admin 세션 필요)**:
- GET /api/v1/biotech/radar          → 최신 watchlist/radar-v1.X-*.md
- GET /api/v1/biotech/rumor?date=... → rumor-daily/YYYY-MM-DD.md
- GET /api/v1/biotech/rumor/dates    → 사용 가능한 날짜 목록
- GET /api/v1/biotech/status         → STATUS.md
- GET /api/v1/biotech/glossary       → GLOSSARY.md
- GET /api/v1/biotech/final          → PHASE-A-FINAL.md
"""
from __future__ import annotations

import csv
import glob
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.api.auth import require_sniper_token

logger = logging.getLogger("biotech_router")
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
    html: str            # 렌더된 HTML (markdown 부재 시 원문 md 그대로)
    raw_md_size: int     # 원본 크기
    render_mode: str = "html"  # "html" | "plain_md_fallback" · WP69-2b


class RumorDates(BaseModel):
    dates: list[str]
    latest: Optional[str]


def _render(path: Path) -> BiotechDoc:
    """md 파일 → HTML + 메타 · TTL 캐시.

    WP69-2b: markdown 지연 import · ImportError 시 원문 md 반환 (본체 무영향).
    """
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"파일 없음: {path.name}")

    key = str(path)
    mtime = path.stat().st_mtime
    now = time.time()
    md_text = path.read_text()
    render_mode = "html"

    cached = _CACHE.get(key)
    if cached and cached[0] == mtime and (now - cached[2]) < CACHE_TTL_SEC:
        html = cached[1]
    else:
        try:
            import markdown as md_lib  # 지연 import · WP69-2b 본체 보호
            html = md_lib.markdown(md_text, extensions=["tables", "fenced_code"])
        except Exception as exc:  # ImportError · 기타
            logger.warning("biotech render fallback (markdown unavailable): %s · path=%s", exc, path.name)
            html = f"<pre>{md_text}</pre>"
            render_mode = "plain_md_fallback"
        _CACHE[key] = (mtime, html, now)

    title_match = re.search(r"^#\s+(.+)", md_text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else path.stem

    return BiotechDoc(
        path=str(path.relative_to(PROJECT_ROOT)),
        title=title,
        generated_utc=datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
        html=html,
        raw_md_size=path.stat().st_size,
        render_mode=render_mode,
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


# WP71-2 · JSON 라우터 (레이더·소문 표 데이터 · md 렌더 대체)

class RadarRow(BaseModel):
    """레이더 CSV 한 행 · WP71-2 · 표 렌더용."""
    rank: int
    ticker: str
    name: str
    mcap_bucket: str
    score: float
    state: str            # A/B/C
    news_window: str      # why_easy 요약 (예정일 표기)
    factors: dict[str, float]   # expert · crowd · near · unnoticed · risk
    tag_bonus: float


class RadarJson(BaseModel):
    generated: str
    source_csv: str
    rows: list[RadarRow]


DATA_DIR = PROJECT_ROOT / "backend" / "data"


def _latest_radar_csv() -> Path | None:
    matches = sorted((DATA_DIR / "biotech" / "candidates").glob("radar_v1_3_*.csv"))
    return matches[-1] if matches else None


@router.get("/radar.json", response_model=RadarJson)
async def get_radar_json(_admin: str = Depends(require_sniper_token)) -> RadarJson:
    """레이더 JSON (표 렌더용 · WP71-2)."""
    path = _latest_radar_csv()
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="radar CSV 없음")
    rows: list[RadarRow] = []
    with path.open() as f:
        for idx, r in enumerate(csv.DictReader(f), 1):
            def _f(k: str, d: float = 0.0) -> float:
                try:
                    return float(r.get(k) or d)
                except Exception:
                    return d
            rows.append(RadarRow(
                rank=idx,
                ticker=r.get("ticker", ""),
                name=(r.get("name") or "")[:60],
                mcap_bucket=r.get("mcap", ""),
                score=_f("score"),
                state=r.get("time_state", "C"),
                news_window=(r.get("why_easy") or "")[:100],
                factors={
                    "expert": _f("expert"),
                    "crowd": _f("crowd"),
                    "near": _f("near"),
                    "unnoticed": _f("unnoticed"),
                    "risk": _f("risk"),
                },
                tag_bonus=_f("tag_bonus"),
            ))
    return RadarJson(
        generated=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        source_csv=str(path.relative_to(PROJECT_ROOT)),
        rows=rows[:30],  # 상위 30
    )


class RumorRow(BaseModel):
    """소문 확인 표 한 행 · 표 1~4 통합 · WP71-2."""
    table: str            # "표1" · "표2" · "표3" · "표4"
    ticker: str
    name: str
    mcap_bucket: str
    days_hint: str        # D-N or D+N or 매수일
    detail: str           # 짧은 근거 문장
    st_24h: Optional[int] = None
    baseline_n: Optional[int] = None


class RumorJson(BaseModel):
    date: str             # YYYY-MM-DD
    generated: str
    rows: list[RumorRow]


@router.get("/rumor.json", response_model=RumorJson)
async def get_rumor_json(
    date: Optional[str] = Query(None, description="YYYY-MM-DD · 미지정 시 최신"),
    _admin: str = Depends(require_sniper_token),
) -> RumorJson:
    """소문 확인 표 (표 1~4 통합 JSON · WP71-2)."""
    files = sorted((DATA_DIR / "biotech" / "candidates").glob("biotech_candidates_v3_*.csv"))
    if not files:
        raise HTTPException(status_code=404, detail="candidates CSV 없음")
    if date and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(status_code=400, detail="date 형식 YYYY-MM-DD")
    # 오늘 없으면 최신
    today_str = (date or datetime.now(timezone.utc).strftime("%Y-%m-%d")).replace("-", "")
    cand_path = DATA_DIR / "biotech" / "candidates" / f"biotech_candidates_v3_{today_str}.csv"
    if not cand_path.exists():
        cand_path = files[-1]
        # 파일명에서 날짜 역추출
        m = re.search(r"_(\d{8})\.csv$", cand_path.name)
        today_str = m.group(1) if m else datetime.now(timezone.utc).strftime("%Y%m%d")
    date_dash = f"{today_str[:4]}-{today_str[4:6]}-{today_str[6:]}"

    confirm_path = DATA_DIR / "biotech" / "community_daily" / f"community_confirm_{today_str}.csv"
    confirm_map: dict[str, dict[str, Any]] = {}
    if confirm_path.exists():
        with confirm_path.open() as f:
            for r in csv.DictReader(f):
                confirm_map[r.get("ticker", "")] = r

    # candidates
    cands = list(csv.DictReader(cand_path.open()))

    def _days(state_note: str) -> str:
        m = re.search(r"D-(\d+)", state_note or "")
        if m:
            return f"D-{m.group(1)}"
        m = re.search(r"발표 후 (\d+)일", state_note or "")
        return f"D+{m.group(1)}" if m else "—"

    def _to_int(v: Any) -> Optional[int]:
        try:
            return int(v)
        except Exception:
            return None

    rows: list[RumorRow] = []
    # 표1: A 상태 · 조용/초기 · 예정일 가까운 순
    a_quiet: list[dict[str, Any]] = []
    for c in cands:
        state = c.get("time_state_v50") or c.get("time_state", "C")
        if state != "A":
            continue
        conf = confirm_map.get(c.get("ticker", ""), {})
        stage = conf.get("stage", "quiet")
        if stage not in ("quiet", "collecting"):
            continue
        note = c.get("state_note_v50") or c.get("state_note", "")
        m = re.search(r"D-(\d+)", note)
        d = int(m.group(1)) if m else 999
        a_quiet.append((d, c))
    a_quiet.sort(key=lambda x: x[0])
    for _, c in a_quiet[:15]:
        note = c.get("state_note_v50") or c.get("state_note", "")
        rows.append(RumorRow(
            table="표1",
            ticker=c.get("ticker", ""),
            name=(c.get("name") or "")[:40],
            mcap_bucket=c.get("mcap_bucket", ""),
            days_hint=_days(note),
            detail=note[:80],
        ))

    # 표2: B 상태 · 뉴스 통과
    b_all = [c for c in cands if (c.get("time_state_v50") or c.get("time_state", "C")) == "B"]
    for c in b_all[:10]:
        note = c.get("state_note_v50") or c.get("state_note", "")
        rows.append(RumorRow(
            table="표2",
            ticker=c.get("ticker", ""),
            name=(c.get("name") or "")[:40],
            mcap_bucket=c.get("mcap_bucket", ""),
            days_hint=_days(note),
            detail=note[:80],
        ))

    # 표3: st_24h > 0 (baseline 미확보 포함 · 원값)
    with_st = []
    for c in cands:
        conf = confirm_map.get(c.get("ticker", ""), {})
        st = _to_int(conf.get("st_24h") or 0) or 0
        if st > 0:
            with_st.append((st, c, conf))
    with_st.sort(key=lambda x: -x[0])
    for st, c, conf in with_st[:15]:
        rows.append(RumorRow(
            table="표3",
            ticker=c.get("ticker", ""),
            name=(c.get("name") or "")[:40],
            mcap_bucket=c.get("mcap_bucket", ""),
            days_hint=conf.get("stage", "?"),
            detail=f"baseline {conf.get('st_baseline_n', '0')}/7일",
            st_24h=st,
            baseline_n=_to_int(conf.get("st_baseline_n") or 0),
        ))

    # 표4: F4 최근 20 거래일 (h65 CSV)
    f4_csvs = sorted(DATA_DIR.glob("h65_form4_daily_table_*.csv"))
    if f4_csvs:
        with f4_csvs[-1].open() as f:
            for r in csv.DictReader(f):
                rows.append(RumorRow(
                    table="표4",
                    ticker=r.get("issuer_cik", "")[-6:],
                    name=(r.get("issuer_name") or "")[:40],
                    mcap_bucket="—",
                    days_hint=f"D+{r.get('elapsed_days', '?')}",
                    detail=f"{r.get('filer_type', '?')} · {r.get('shares', '0')}주",
                ))

    return RumorJson(
        date=date_dash,
        generated=datetime.now(timezone.utc).isoformat(),
        rows=rows,
    )
