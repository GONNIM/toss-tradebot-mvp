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
from datetime import datetime, timedelta, timezone
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
    mcap_asof: str = ""   # WP74 · 시총 배지 기준 종가일 (빈 값 = 배지 미표시)
    score: float
    state: str            # A/B/C
    news_window: str      # why_easy 요약 (예정일 표기)
    factors: dict[str, float]   # expert · crowd · near · unnoticed · risk
    tag_bonus: float


class RadarJson(BaseModel):
    generated: str
    source_csv: str
    rows: list[RadarRow]


import os

DATA_DIR = PROJECT_ROOT / "backend" / "data"
# WP72-3 · 산출 CSV git 추적 폴더 (소용량 · 서버 rows>0 확보)
DATA_DIR_DOCS = PROJECT_ROOT / "docs" / "plans" / "biotech" / "data"
# WP69-3b · 서버 파이프 런타임 폴더 (git 추적 밖 · 배포 reset --hard 영향 없음)
# 환경변수 BIOTECH_RUNTIME_DIR 미설정 시 None → 기존 동작 (docs → backend/data)
_rt = os.environ.get("BIOTECH_RUNTIME_DIR", "").strip()
DATA_DIR_RUNTIME: Path | None = Path(_rt) if _rt else None


def _search_dirs(subrel: str) -> list[Path]:
    """WP69-3b · 조회 순서 결정.

    순서: BIOTECH_RUNTIME_DIR > docs/plans/biotech/data > backend/data/biotech/<subrel>
    subrel 은 backend/data 하위 상대 경로 (예: "candidates", "community_daily").
    RUNTIME/DOCS 는 flat 구조 (전 산출 CSV 한 폴더) · backend/data 만 subrel 사용.
    """
    dirs: list[Path] = []
    if DATA_DIR_RUNTIME is not None:
        dirs.append(DATA_DIR_RUNTIME / subrel)  # 서버는 subrel 하위 유지 · 예: var/biotech/candidates
        dirs.append(DATA_DIR_RUNTIME)            # flat fallback (h65 form4 처럼 subrel 없이 저장 시)
    dirs.append(DATA_DIR_DOCS)
    dirs.append(DATA_DIR / "biotech" / subrel)
    return dirs


def _latest(*patterns: tuple[Path, str]) -> Path | None:
    """폴더 여러 곳에서 패턴 매치 · 최신 mtime 반환."""
    hits: list[Path] = []
    for base, pat in patterns:
        if base.exists():
            hits.extend(base.glob(pat))
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


# ── WP74 · 시총 배지 (표시 계층 전용) ─────────────────────────────
# 후보 선정·점수는 candidates CSV 의 mcap_bucket 을 그대로 쓴다 (5B 초과 제외 필터 무변경).
# 화면 배지만 기존 소스 (h3_mcap 발행주식수 × h3_prices_merged 최신 종가) 로 계산해 덧붙인다.
MCAP_SHARES_MAX_AGE_DAYS = 365   # 발행주식수 공시가 12개월 넘으면 배지 없음 (증자로 크게 달라질 수 있음)
MCAP_PRICE_MAX_AGE_DAYS = 60     # 종가가 60일 넘으면 배지 없음 (예: 2021년 종가만 남은 종목)
_MCAP_CACHE: dict[str, Any] = {"mtime": None, "rows": {}}


def _mcap_bucket_label(mcap: float) -> str:
    if mcap < 50e6:
        return "50M 미만"
    if mcap < 300e6:
        return "50M-300M"
    if mcap < 1e9:
        return "300M-1B"
    if mcap < 5e9:
        return "1B-5B"
    return "5B+"


def _mcap_display(ticker: str, csv_bucket: str = "") -> tuple[str, str]:
    """(배지 문구, 기준 종가일) · 계산 불가면 ("", "") → 화면에서 배지 미표시.

    candidates CSV 에 실제 구간이 있으면 (로컬 등) 그 값을 우선 사용한다.
    """
    if csv_bucket and csv_bucket not in ("unknown", "—"):
        return csv_bucket, ""
    hits: list[Path] = []
    for base in [DATA_DIR_DOCS, DATA_DIR / "biotech"]:
        if base.exists():
            hits.extend(base.glob("mcap_display_inputs_*.csv"))
    if not hits:
        return "", ""
    src = max(hits, key=lambda p: p.stat().st_mtime)
    key = (str(src), src.stat().st_mtime)
    if _MCAP_CACHE["mtime"] != key:
        with src.open() as f:
            _MCAP_CACHE["rows"] = {r["ticker"]: r for r in csv.DictReader(f)}
        _MCAP_CACHE["mtime"] = key
    r = _MCAP_CACHE["rows"].get(ticker)
    if not r:
        return "", ""
    today = datetime.now(timezone(timedelta(hours=9))).date()
    try:
        sh_age = (today - datetime.strptime(r["shares_asof"], "%Y-%m-%d").date()).days
        px_date = datetime.strptime(r["close_date"], "%Y-%m-%d").date()
        mcap = float(r["shares"]) * float(r["close"])
    except (ValueError, KeyError):
        return "", ""
    if sh_age > MCAP_SHARES_MAX_AGE_DAYS or (today - px_date).days > MCAP_PRICE_MAX_AGE_DAYS or mcap <= 0:
        return "", ""
    return _mcap_bucket_label(mcap), px_date.isoformat()


def _latest_radar_csv() -> Path | None:
    """radar CSV 최신 · WP69-3b · RUNTIME > docs > backend/data."""
    patterns: list[tuple[Path, str]] = []
    for d in _search_dirs("candidates"):
        patterns.append((d, "radar_v1_3_*.csv"))
    return _latest(*patterns)


@router.get("/radar.json", response_model=RadarJson)
async def get_radar_json(_admin: str = Depends(require_sniper_token)) -> RadarJson:
    """레이더 JSON (표 렌더용 · WP71-2).

    서버 파이프 (WP69-3) 배포 전에는 CSV 파일 미존재 → 200 · rows=[] fallback.
    프론트 BiotechTable 이 "표시할 행이 없습니다" 빈 상태 렌더.
    """
    path = _latest_radar_csv()
    if not path or not path.exists():
        return RadarJson(
            generated=datetime.now(timezone.utc).isoformat(),
            source_csv="(파일 없음 · 서버 파이프 대기 · WP69-3)",
            rows=[],
        )
    rows: list[RadarRow] = []
    with path.open() as f:
        for idx, r in enumerate(csv.DictReader(f), 1):
            def _f(k: str, d: float = 0.0) -> float:
                try:
                    return float(r.get(k) or d)
                except Exception:
                    return d
            mb, masof = _mcap_display(r.get("ticker", ""), r.get("mcap", ""))
            rows.append(RadarRow(
                rank=idx,
                ticker=r.get("ticker", ""),
                name=(r.get("name") or "")[:60],
                mcap_bucket=mb,
                mcap_asof=masof,
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
    mcap_asof: str = ""   # WP74 · 시총 배지 기준 종가일 (빈 값 = 배지 미표시)
    # WP74 2단계 · 카드 문장용 구조화 필드 (원문 state_note 에서 추출 · 없으면 빈 값)
    nct_id: str = ""      # ClinicalTrials.gov 임상 번호
    phase: str = ""       # PHASE3 · PHASE1/PHASE2 등 원문 표기
    event_date: str = ""  # 임상 완료 예정일 (primary completion · 결과 발표일 아님)
    days_to: Optional[int] = None


_NOTE_RE = re.compile(r"(NCT\d{8}).*?D-(\d+)\s*\((\d{4}-\d{2}-\d{2})\s*·\s*([A-Z0-9_/]*)")


def _note_fields(note: str) -> dict[str, Any]:
    """state_note 원문 → 카드 문장용 필드 (형식 불일치 시 빈 dict · 화면은 원문 표시)."""
    m = _NOTE_RE.search(note or "")
    if not m:
        return {}
    return {"nct_id": m.group(1), "days_to": int(m.group(2)), "event_date": m.group(3), "phase": m.group(4)}


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
    if date and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(status_code=400, detail="date 형식 YYYY-MM-DD")
    # WP69-3b · RUNTIME > docs > backend/data · 관측 Day 2 hotfix (mtime 최신 우선)
    cand_dirs = _search_dirs("candidates")
    cand_files: list[Path] = []
    for d in cand_dirs:
        if d.exists():
            cand_files.extend(d.glob("biotech_candidates_v3_*.csv"))
    # 관측 Day 2 fix: mtime 최신 순 정렬 (base 순서·이름 순 대신)
    cand_files.sort(key=lambda p: p.stat().st_mtime)
    if not cand_files:
        return RumorJson(
            date=(date or datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            generated=datetime.now(timezone.utc).isoformat(),
            rows=[],
        )
    today_str = (date or datetime.now(timezone.utc).strftime("%Y-%m-%d")).replace("-", "")
    # date 매치 찾기 (조회 순서대로)
    cand_path: Path | None = None
    for base in cand_dirs:
        p = base / f"biotech_candidates_v3_{today_str}.csv"
        if p.exists():
            cand_path = p
            break
    if cand_path is None:
        cand_path = cand_files[-1]
        m = re.search(r"_(\d{8})\.csv$", cand_path.name)
        today_str = m.group(1) if m else datetime.now(timezone.utc).strftime("%Y%m%d")
    date_dash = f"{today_str[:4]}-{today_str[4:6]}-{today_str[6:]}"

    # confirm 도 조회 순서 준수
    confirm_map: dict[str, dict[str, Any]] = {}
    for base in _search_dirs("community_daily"):
        p = base / f"community_confirm_{today_str}.csv"
        if p.exists():
            with p.open() as f:
                for r in csv.DictReader(f):
                    confirm_map[r.get("ticker", "")] = r
            break

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
            **_note_fields(note),
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

    # 표4: F4 최근 20 거래일 (h65 CSV · WP69-3b · RUNTIME > docs > backend/data)
    f4_pick: Path | None = None
    f4_search = [DATA_DIR_DOCS, DATA_DIR]
    if DATA_DIR_RUNTIME is not None:
        f4_search = [DATA_DIR_RUNTIME] + f4_search
    for base in f4_search:
        if base.exists():
            files = sorted(base.glob("h65_form4_daily_table_*.csv"))
            if files:
                f4_pick = files[-1]
                break
    if f4_pick:
        with f4_pick.open() as f:
            for r in csv.DictReader(f):
                rows.append(RumorRow(
                    table="표4",
                    ticker=r.get("issuer_cik", "")[-6:],
                    name=(r.get("issuer_name") or "")[:40],
                    mcap_bucket="—",
                    days_hint=f"D+{r.get('elapsed_days', '?')}",
                    detail=f"{r.get('filer_type', '?')} · {r.get('shares', '0')}주",
                ))

    for row in rows:
        if row.table in ("표1", "표2", "표3"):
            row.mcap_bucket, row.mcap_asof = _mcap_display(row.ticker, row.mcap_bucket)
        elif row.mcap_bucket in ("unknown", "—"):
            row.mcap_bucket = ""

    return RumorJson(
        date=date_dash,
        generated=datetime.now(timezone.utc).isoformat(),
        rows=rows,
    )


class BiotechKpi(BaseModel):
    """KPI 4칸 · WP72-2 · 상단 요약."""
    generated: str
    candidates_total: int      # 총 후보 (모든 상태)
    news_a_ready: int           # A 상태 (뉴스 예정)
    insider_buy_20d: int        # 임원·대주주 매수 최근 20 거래일
    alerts: int                 # 급등 경보 (rose 섹션 · 향후 신호 채널) · 현재 0


@router.get("/kpi.json", response_model=BiotechKpi)
async def get_kpi(_admin: str = Depends(require_sniper_token)) -> BiotechKpi:
    """KPI 4칸 · 총후보·뉴스예정A·임원매수20d·급등경보."""
    # candidates_total · news_a_ready · WP69-3b · RUNTIME > docs > backend/data
    cand_pick: Path | None = None
    for base in _search_dirs("candidates"):
        if base.exists():
            files = sorted(base.glob("biotech_candidates_v3_*.csv"))
            if files:
                cand_pick = files[-1]
                break
    candidates_total = 0
    news_a_ready = 0
    if cand_pick:
        with cand_pick.open() as f:
            for r in csv.DictReader(f):
                candidates_total += 1
                state = r.get("time_state_v50") or r.get("time_state", "C")
                if state == "A":
                    news_a_ready += 1

    # insider_buy_20d (h65_form4_daily_table)
    f4_pick: Path | None = None
    f4_search = [DATA_DIR_DOCS, DATA_DIR]
    if DATA_DIR_RUNTIME is not None:
        f4_search = [DATA_DIR_RUNTIME] + f4_search
    for base in f4_search:
        if base.exists():
            files = sorted(base.glob("h65_form4_daily_table_*.csv"))
            if files:
                f4_pick = files[-1]
                break
    insider_buy_20d = 0
    if f4_pick:
        with f4_pick.open() as f:
            insider_buy_20d = sum(1 for _ in csv.DictReader(f))

    # 급등 경보 (WP69-3d 재정의 · h_radar_params v1.5 alerts_definition):
    #   apewisdom baseline_mult ≥ 5 OR reddit_rss_matches ≥ 3 인 티커 수
    alerts = 0
    confirm_pick: Path | None = None
    for base in _search_dirs("community_daily"):
        if base.exists():
            files = sorted(base.glob("community_confirm_*.csv"))
            if files:
                confirm_pick = files[-1]
                break
    if confirm_pick:
        with confirm_pick.open() as f:
            for r in csv.DictReader(f):
                mult_raw = r.get("st_baseline_mult", "")
                rss_raw = r.get("reddit_rss_matches", "0")
                try:
                    rss = int(rss_raw)
                except (ValueError, TypeError):
                    rss = 0
                try:
                    mult = float(mult_raw) if mult_raw and mult_raw != "collecting" else 0.0
                except (ValueError, TypeError):
                    mult = 0.0
                if mult >= 5.0 or rss >= 3:
                    alerts += 1

    return BiotechKpi(
        generated=datetime.now(timezone.utc).isoformat(),
        candidates_total=candidates_total,
        news_a_ready=news_a_ready,
        insider_buy_20d=insider_buy_20d,
        alerts=alerts,
    )
