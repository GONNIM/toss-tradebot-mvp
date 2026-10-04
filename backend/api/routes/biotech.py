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
import json
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
from backend.scripts.biotech_alert_rule import judge as _alert_judge

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
    # WP85 · 순위표 행 시험 요약 (cardText 짧은 판) · 후보 state_note 의 대표 시험 · 표시 전용
    nct_id: str = ""
    phase: str = ""
    event_date: str = ""
    days_to: Optional[int] = None
    trial: dict[str, Any] = {}


class RadarJson(BaseModel):
    generated: str
    source_csv: str
    rows: list[RadarRow]
    inputs_missing: list[str] = []   # WP94 · 레이더 점수 설계 입력 중 서버에 없는 파일 (표시 전용)


def _radar_inputs_missing(path: Path | None) -> list[str]:
    """레이더 CSV 첫 행의 inputs_missing 열 (WP94) · 열이 없던 이전 파일은 빈 목록."""
    if not path or not path.exists():
        return []
    with path.open() as f:
        first = next(csv.DictReader(f), None) or {}
    return [x for x in (first.get("inputs_missing") or "").split("|") if x]


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:   # 로컬 화면 모드 · 런타임 폴더가 저장소 밖일 때
        return str(path)


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


def _mcap_json_has_rows(path: Path) -> bool:
    try:
        return bool(json.loads(path.read_text()).get("rows"))
    except Exception:
        return False


def _mcap_display(ticker: str, csv_bucket: str = "") -> tuple[str, str]:
    """(배지 문구, 기준 종가일) · 계산 불가면 ("", "") → 화면에서 배지 미표시.

    candidates CSV 에 실제 구간이 있으면 (로컬 등) 그 값을 우선 사용한다.
    """
    if csv_bucket and csv_bucket not in ("unknown", "—"):
        return csv_bucket, ""
    # WP75 · 매일 산정 파일 (RUNTIME/mcap_display.json) 우선 · 없으면 WP74 기존 입력 (h3 소스 요약 CSV)
    runtime_json = (DATA_DIR_RUNTIME if DATA_DIR_RUNTIME else DATA_DIR / "biotech") / "mcap_display.json"
    # 2026-10-02 · 플래그 첫날에는 주식수 (월요일 주간 단계) 가 없어 행 0 개 파일이 생김 → 빈 파일이면 예전 입력으로 대신 표시
    if runtime_json.exists() and _mcap_json_has_rows(runtime_json):
        src = runtime_json
    else:
        hits: list[Path] = []
        for base in [DATA_DIR_DOCS, DATA_DIR / "biotech"]:
            if base.exists():
                hits.extend(base.glob("mcap_display_inputs_*.csv"))
        if not hits:
            return "", ""
        src = max(hits, key=lambda p: p.stat().st_mtime)
    key = (str(src), src.stat().st_mtime)
    if _MCAP_CACHE["mtime"] != key:
        if src.suffix == ".json":
            _MCAP_CACHE["rows"] = {tk: {k: str(v) for k, v in row.items()}
                                   for tk, row in (json.loads(src.read_text()).get("rows") or {}).items()}
        else:
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
        patterns.append((d, "radar_v1_3_????????.csv"))   # WP93 · 재계산 파일 (_scorev2 등) 제외
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
    # WP85 · 대표 시험 (candidates v3 state_note · AACT 1차 완료 예정일) · 표시 전용
    notes = _latest_candidate_notes()
    for row in rows[:30]:
        f = _note_fields(notes.get(row.ticker, ""))
        if f:
            row.nct_id, row.phase, row.event_date, row.days_to = f["nct_id"], f["phase"], f["event_date"], f["days_to"]
            row.trial = _trial_display(row.nct_id)
    return RadarJson(
        generated=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        source_csv=_rel(path),
        rows=rows[:30],  # 상위 30
        inputs_missing=_radar_inputs_missing(path),
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
    stage: str = ""       # WP74 4단계 · 언급 단계 (quiet · collecting · 기타) · 표시용
    mult: str = ""        # WP85 · 평소 대비 배수 원값 (confirm st_baseline_mult · 'collecting' 또는 숫자) · 표시용
    baseline_mean: Optional[float] = None   # WP86 · 기준선 하루 평균 (평소 하루 N건 표시용)
    cik: str = ""         # WP85 · 표4 발행사 CIK (펼침 영역 전용)
    form4: dict[str, Any] = {}   # WP87 · 표4 거래 원자료 (신고자 · 주식 수 · 신고서 가격 · 신고일 · 거래일)
    trial: dict[str, Any] = {}      # WP76 · AACT 시험 상세 (원문 필드 + 사전 대응) · 없으면 빈 dict
    theme_rank: dict[str, Any] = {}  # WP76 · H6 봉인 순위 (읽기만) · 소속 없으면 빈 dict


_NOTE_RE = re.compile(r"(NCT\d{8}).*?D-(\d+)\s*\((\d{4}-\d{2}-\d{2})\s*·\s*([A-Z0-9_/]*)")


# ── WP76 · 카드 상세 (표시 전용 · 지어내는 문장 없음) ──────────────────────
_FILE_CACHE: dict[str, tuple[float, Any]] = {}
THEME_KO = {  # H6 테마 사전 v1 이름 (H6-design §2 고정)
    "obesity_glp1": "비만·GLP-1", "hair_loss": "탈모", "longevity_rejuvenation": "장수·회춘",
    "meal_replacement_metabolic": "식사대용·대사", "hibernation_hypothermia": "동면·저체온", "cognitive_memory": "신경·기억",
}


def _cached(path: Path | None, loader) -> Any:
    if path is None or not path.exists():
        return None
    key, mt = str(path), path.stat().st_mtime
    hit = _FILE_CACHE.get(key)
    if hit and hit[0] == mt:
        return hit[1]
    val = loader(path)
    _FILE_CACHE[key] = (mt, val)
    return val


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open() as f:
        return list(csv.DictReader(f))


def _snapshot_by_nct() -> dict[str, dict[str, Any]]:
    cands = ([DATA_DIR_RUNTIME / "ctgov_snapshot.json"] if DATA_DIR_RUNTIME else []) + [DATA_DIR_DOCS / "ctgov_snapshot.json"]
    path = next((p for p in cands if p.exists()), None)
    data = _cached(path, lambda p: json.loads(p.read_text()))
    return {m.get("nct_id", ""): m for m in (data or {}).get("matches", [])}


def _dict_map(name: str, key: str) -> dict[str, dict[str, str]]:
    rows = _cached(DATA_DIR_DOCS / name, _csv_rows) or []
    return {r[key].strip().lower(): r for r in rows if r.get(key)}


def _ko(term: str) -> str:
    """ko_terms.csv 완전 일치만 · 없으면 빈 값 (화면은 영어 원문 유지 · 임의 번역 금지)."""
    return (_dict_map("ko_terms.csv", "en").get((term or "").strip().lower()) or {}).get("ko", "")


IGNORE_CATEGORY = "무시"  # WP82 · 사전 내부 값 · 시험 분류에서 건너뜀 · 화면 표시 금지


def _trial_display(nct: str) -> dict[str, Any]:
    m = _snapshot_by_nct().get(nct)
    if not m:
        return {}
    cats = _dict_map("condition_categories.csv", "term")
    category, cat_src = "", ""
    terms = m.get("mesh_terms", []) + m.get("conditions", [])   # 선택 순서: MeSH 용어 → 질환명 원문 · 첫 사전 일치
    for t in terms:
        hit = cats.get((t or "").strip().lower())
        if hit:
            if hit.get("category") == IGNORE_CATEGORY:   # WP82 · '무시' 용어는 건너뛰고 다음 용어를 본다
                continue
            category, cat_src = hit.get("category", ""), t
            break
    conds = m.get("conditions", [])
    category_auto = False
    if not category:
        # WP81 · 수동 사전에 없을 때만 자동 분류 (auto_categories.json · 주간 잡 산출 · NLM 호출 없음)
        auto = _auto_categories()
        for t in m.get("mesh_terms", []) + conds:
            if (cats.get((t or "").strip().lower()) or {}).get("category") == IGNORE_CATEGORY:   # WP97-2 · '무시' 용어는 자동 분류에도 안 씀
                continue
            hit = auto.get(t)
            if hit and hit.get("category") == IGNORE_CATEGORY:   # WP99 · 자동 분류의 '무시' (얕은 트리 일반어) 도 화면에 쓰지 않음
                continue
            if hit:
                category, cat_src, category_auto = hit.get("category", ""), t, True
                break
    if not category and terms:
        # 원문 = 첫 질환명 (없으면 첫 MeSH 용어) · '무시' 용어뿐이어도 원문 글자만 쓰고 '무시' 는 표시하지 않음
        # WP97-2 · 원문도 '무시' 가 아닌 첫 용어 (모두 '무시' 면 예전처럼 첫 용어)
        usable = [t for t in (conds or terms) if (cats.get((t or "").strip().lower()) or {}).get("category") != IGNORE_CATEGORY]
        first = usable[0] if usable else (conds[0] if conds else terms[0])
        category, cat_src = f"기타 ({first})", first
    ivs = [{"name": i.get("name", ""), "type": i.get("type", ""), "type_ko": _ko(i.get("type", "")), "name_ko": _ko(i.get("name", ""))}
           for i in m.get("interventions", [])]
    placebo = any("placebo" in (i.get("name") or "").lower() for i in m.get("interventions", []))
    outs = [{**o, "measure_ko": _ko(o.get("measure", ""))} for o in m.get("primary_outcomes", [])]
    return {
        "nct_id": nct, "brief_title": m.get("brief_title", ""), "official_title": m.get("official_title", ""),
        "category": category, "category_source": cat_src, "category_auto": category_auto,
        # WP97-3 · ignored = 사전 분류 '무시' (일반어) · 화면 "대상 질환" 줄에서 뺌 (biotech-display conditionsLine)
        "conditions": [{"en": c, "ko": _ko(c),
                        "ignored": (cats.get((c or "").strip().lower()) or {}).get("category") == IGNORE_CATEGORY} for c in conds],
        "interventions": ivs, "placebo": placebo,
        "enrollment": m.get("enrollment", ""), "enrollment_type": m.get("enrollment_type", ""),
        "study_type": m.get("study_type", ""),
        "allocation": m.get("allocation", ""), "allocation_ko": _ko(m.get("allocation", "")),
        "masking": m.get("masking", ""), "masking_ko": _ko(m.get("masking", "")),
        "primary_outcomes": outs, "overall_status": m.get("overall_status", ""),
    }


def _auto_categories() -> dict[str, dict[str, Any]]:
    """RUNTIME/auto_categories.json (WP81 자동 분류) · 없으면 빈 dict."""
    base = DATA_DIR_RUNTIME if DATA_DIR_RUNTIME else (DATA_DIR / "biotech")
    data = _cached(base / "auto_categories.json", lambda p: json.loads(p.read_text())) or {}
    return data.get("terms", {})


def _latest_candidate_notes() -> dict[str, str]:
    """ticker → state_note (최신 candidates v3 · RUNTIME > docs > backend/data)."""
    files: list[Path] = []
    for d in _search_dirs("candidates"):
        if d.exists():
            files.extend(d.glob("biotech_candidates_v3_*.csv"))
    if not files:
        return {}
    rows = _cached(max(files, key=lambda p: p.stat().st_mtime), _csv_rows) or []
    return {r.get("ticker", ""): (r.get("state_note_v50") or r.get("state_note") or "") for r in rows}


def _cik_ticker_map() -> dict[str, str]:
    """SEC company_tickers · 런타임 (주간 갱신 · WP86) 우선 · 없으면 docs/plans/biotech/data 이식본 · CIK 10자리 → 티커."""
    cands = ([DATA_DIR_RUNTIME / "sec_company_tickers.json"] if DATA_DIR_RUNTIME else []) + \
        [DATA_DIR_DOCS / "sec_company_tickers.json", DATA_DIR / "sec_company_tickers.json"]
    p = next((c for c in cands if c.exists()), cands[-1])
    data = _cached(p, lambda q: json.loads(q.read_text())) or {}
    out: dict[str, str] = {}
    for e in data.values():
        out.setdefault(str(e.get("cik_str", "")).zfill(10), str(e.get("ticker", "")).upper())
    return out


def _theme_rank(ticker: str) -> dict[str, Any]:
    """H6 소속 v2 × 봉인 순위 최신 분기 · 여러 테마면 최고 순위 (H6-design §3) · 읽기만."""
    memb_p = DATA_DIR_DOCS.parent / "verification" / "H6" / "c3-20260928" / "h6_membership_v2_2026-09-28.csv"
    rank_hits = sorted(DATA_DIR_DOCS.glob("h6_rank_growth_*.csv"))
    memb = _cached(memb_p, _csv_rows) or []
    ranks = _cached(rank_hits[-1], _csv_rows) if rank_hits else []
    themes = {r["theme"] for r in memb if r.get("ticker") == ticker and r.get("theme") in THEME_KO}
    if not themes or not ranks:
        return {}
    latest = max((int(r["year"]), int(r["quarter"])) for r in ranks)
    cur = {r["theme"]: int(r["rank"]) for r in ranks if (int(r["year"]), int(r["quarter"])) == latest}
    best = min((t for t in themes if t in cur), key=lambda t: cur[t], default=None)
    if best is None:
        return {}
    return {"theme": best, "theme_ko": THEME_KO[best], "rank": cur[best], "of": len(cur), "quarter": f"{latest[0]}Q{latest[1]}"}


def _today_kst() -> "date":
    return datetime.now(timezone(timedelta(hours=9))).date()


def _note_fields(note: str) -> dict[str, Any]:
    """state_note 원문 → 카드 문장용 필드 (형식 불일치 시 빈 dict · 화면은 원문 표시).

    WP87 · days_to 는 API 응답 시각의 KST 날짜 기준으로 다시 계산한다 (노트의 D-n 은 주간 AACT 잡 날짜 기준이라
    최대 7일 어긋남 · 예: 9/30 화면에 9/30 종료가 D-2 로 보이던 문제) · 음수 = 이미 지남 (화면 D+n)
    """
    m = _NOTE_RE.search(note or "")
    if not m:
        return {}
    try:
        days = (datetime.strptime(m.group(3), "%Y-%m-%d").date() - _today_kst()).days
    except ValueError:
        days = int(m.group(2))
    return {"nct_id": m.group(1), "days_to": days, "event_date": m.group(3), "phase": m.group(4)}


class RumorJson(BaseModel):
    date: str             # YYYY-MM-DD
    generated: str
    rows: list[RumorRow]
    reddit_status: dict[str, Any] = {}   # WP98-2 · 레딧 수집 상태 (4곳 중 몇 곳) · 표시 전용


def _latest_reddit_status() -> dict[str, Any]:
    """confirm 단계가 남긴 reddit_status_<날짜>.json 최신 1개 · 없으면 빈 dict."""
    hits: list[Path] = []
    for base in _search_dirs("community_daily"):
        if base.exists():
            hits.extend(base.glob("reddit_status_*.json"))
    if not hits:
        return {}
    p = max(hits, key=lambda x: x.name)
    try:
        return {**json.loads(p.read_text()), "date": p.stem.rsplit("_", 1)[-1]}
    except Exception:
        return {}


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

    def _to_float(v: Any) -> Optional[float]:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

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
    # WP74 4단계 · "A" = 뉴스 예정 (A 상태) 전체 · 예정일 가까운 순 · KPI 클릭 펼침용 (표1 규칙 무변경)
    a_all: list[tuple[int, dict[str, Any]]] = []
    for c in cands:
        if (c.get("time_state_v50") or c.get("time_state", "C")) != "A":
            continue
        note = c.get("state_note_v50") or c.get("state_note", "")
        m = re.search(r"D-(\d+)", note)
        a_all.append((int(m.group(1)) if m else 999, c))
    a_all.sort(key=lambda x: x[0])
    for _, c in a_all:
        note = c.get("state_note_v50") or c.get("state_note", "")
        conf = confirm_map.get(c.get("ticker", ""), {})
        rows.append(RumorRow(
            table="A",
            ticker=c.get("ticker", ""),
            name=(c.get("name") or "")[:40],
            mcap_bucket=c.get("mcap_bucket", ""),
            days_hint=_days(note),
            detail=note[:80],
            stage=conf.get("stage", ""),
            baseline_n=_to_int(conf.get("st_baseline_n") or 0),
            **_note_fields(note),
        ))
    for _, c in a_quiet[:15]:
        note = c.get("state_note_v50") or c.get("state_note", "")
        rows.append(RumorRow(
            table="표1",
            ticker=c.get("ticker", ""),
            name=(c.get("name") or "")[:40],
            mcap_bucket=c.get("mcap_bucket", ""),
            days_hint=_days(note),
            detail=note[:80],
            stage=confirm_map.get(c.get("ticker", ""), {}).get("stage", ""),
            baseline_n=_to_int(confirm_map.get(c.get("ticker", ""), {}).get("st_baseline_n") or 0),
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
            detail=f"baseline {conf.get('st_baseline_n', '0')}/7일",   # 하위 호환 원문 · 화면은 lib mentionSentence 사용
            st_24h=st,
            baseline_n=_to_int(conf.get("st_baseline_n") or 0),
            stage=conf.get("stage", ""),
            mult=str(conf.get("st_baseline_mult") or ""),
            baseline_mean=_to_float(conf.get("st_baseline_mean")),
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
        cik2tk = _cik_ticker_map()
        with f4_pick.open() as f:
            for r in csv.DictReader(f):
                cik10 = (r.get("issuer_cik") or "").zfill(10)
                rows.append(RumorRow(
                    table="표4",
                    # WP85 · 이전: 발행사 CIK 끝 6자리 (예 "088082") 를 티커 자리에 넣던 결함 · 이제 h65 issuer_ticker > SEC 명부 · 없으면 빈 값 (화면 "비상장 추정" · WP89)
                    ticker=(r.get("issuer_ticker") or cik2tk.get(cik10, "")),
                    cik=cik10,
                    form4={
                        "filer_cik": r.get("filer_cik", ""), "filer_name": r.get("filer_name", ""),
                        "filer_type": r.get("filer_type", ""), "shares": _to_float(r.get("shares")),
                        "price": _to_float(r.get("price_per_share")), "filing_date": r.get("filing_date", ""),
                        "tx_date": r.get("tx_date", ""), "elapsed_days": _to_int(r.get("elapsed_days")),
                    },
                    name=(r.get("issuer_name") or "")[:40],
                    mcap_bucket="—",
                    days_hint=f"D+{r.get('elapsed_days', '?')}",
                    detail=f"{r.get('filer_type', '?')} · {r.get('shares', '0')}주",
                ))

    for row in rows:
        if row.table in ("A", "표1"):
            row.trial = _trial_display(row.nct_id) if row.nct_id else {}
            row.theme_rank = _theme_rank(row.ticker)
        if row.table in ("A", "표1", "표2", "표3"):
            row.mcap_bucket, row.mcap_asof = _mcap_display(row.ticker, row.mcap_bucket)
        elif row.mcap_bucket in ("unknown", "—"):
            row.mcap_bucket = ""

    return RumorJson(
        date=date_dash,
        generated=datetime.now(timezone.utc).isoformat(),
        rows=rows,
        reddit_status=_latest_reddit_status(),
    )


class BiotechKpi(BaseModel):
    """KPI 4칸 · WP72-2 · 상단 요약."""
    generated: str
    candidates_total: int      # 총 후보 (모든 상태)
    news_a_ready: int           # A 상태 (뉴스 예정)
    insider_buy_20d: int        # 임원·대주주 매수 최근 20 거래일
    alerts: int                 # 급등 경보 (rose 섹션 · 향후 신호 채널) · 현재 0
    alert_tickers: list[str] = []  # WP74 4단계 · 경보 종목 (표시용 · 판정 무변경)
    alerts_collecting: int = 0  # WP78 · 기준선 7일 미만이라 경보 판정에서 뺀 종목 수
    reddit_baseline_days: int = 0  # WP100 · 레딧 24시간 매치 기준선 기록 일수 (최대값 · 7 미만이면 레딧 조건 수집 중)
    alert_briefs: list[dict[str, Any]] = []  # WP77 · 급등 브리핑 패널 + 자동 요약 (수집 자료 · 판정 무변경)
    inputs_missing: list[str] = []  # WP94 · 레이더 점수 입력 부족 (radar CSV 기록 · 표시 전용)


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
            # WP89 · 행 수가 아니라 신고 묶음 수 (신고자 · 발행사 · 신고일) · 화면 카드 수와 같은 기준
            insider_buy_20d = len({(r.get("filer_cik", ""), (r.get("issuer_cik") or "").zfill(10), r.get("filing_date", ""))
                                   for r in csv.DictReader(f)})

    # 급등 경보 (WP69-3d 재정의 · h_radar_params v1.5 alerts_definition):
    #   apewisdom baseline_mult ≥ 5 OR reddit_rss_matches ≥ 3 인 티커 수
    alerts = 0
    alerts_collecting = 0
    reddit_days = 0
    alert_tickers: list[str] = []
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
                # WP78 · 공용 규칙 (backend/scripts/biotech_alert_rule.py) · 기준선 7일 미만 = 수집 중 (판정 제외)
                reddit_days = max(reddit_days, int(float(r.get("reddit_baseline_n") or 0)))
                ok, why = _alert_judge(r)
                if why == "collecting":
                    alerts_collecting += 1
                if ok:
                    alerts += 1
                    alert_tickers.append(r.get("ticker", ""))

    return BiotechKpi(
        generated=datetime.now(timezone.utc).isoformat(),
        candidates_total=candidates_total,
        news_a_ready=news_a_ready,
        insider_buy_20d=insider_buy_20d,
        alerts=alerts,
        alert_tickers=alert_tickers,
        alerts_collecting=alerts_collecting,
        reddit_baseline_days=reddit_days,
        alert_briefs=_latest_alert_briefs(),
        inputs_missing=_radar_inputs_missing(_latest_radar_csv()),
    )


def _latest_alert_briefs() -> list[dict[str, Any]]:
    """briefs/alert_brief_<날짜>.json 최신 · RUNTIME > backend/data/biotech."""
    dirs = ([DATA_DIR_RUNTIME / "briefs"] if DATA_DIR_RUNTIME else []) + [DATA_DIR / "biotech" / "briefs"]
    for d in dirs:
        hits = sorted(d.glob("alert_brief_*.json")) if d.exists() else []
        if hits:
            data = _cached(hits[-1], lambda p: json.loads(p.read_text())) or {}
            return [{**b, "brief_date": data.get("date", "")} for b in data.get("briefs", [])]
    return []
