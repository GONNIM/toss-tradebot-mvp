"""종목 한 장 API (1022-10 3단계) · GET /api/v1/stock/{ticker}.

- 저장된 자료 (DB · 로컬 파일) 만 읽는다. 외부 HTTP 0 · 쓰기 0 · SEC 보충·토스 호출 없음.
- 역할은 get_current_role (예외 없음 · 접근 기록 안 씀).
- 1119-01 · 공개 범위: 신호 · 일정 · 계속기업 (자체 · 공개 자료) 은 비로그인에게도 보인다 (잠금 행 없음).
  관리자만: 보유 · 판단 · 국내 스나이퍼의 진입/청산 상태 낱말. 야후 · 네이버 자료는 이 API 가 아예 부르지 않는다
  (화면이 로그인 상태에서만 기존 /api/v1/biotech/quote/{ticker} 를 따로 부른다).
- 예외 (1128-01): GET /api/v1/stock/{code}/quote 는 관리자 전용이고 국내 허용 목록 코드에서만 네이버를 부른다 (services/kr_quotes.py).
  개요 API 는 여전히 바깥 호출 0 이다 (시장 표시 · quote_available 은 저장된 표만 읽음).
- 출처마다 작은 함수 하나 · 실패하면 그 칸만 빠지고 200.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import desc, func, select

from backend.api.auth import get_current_role, require_sniper_token
from backend.api.schemas import (StockCatalyst, StockGoingConcern, StockHolding, StockJudgment, StockOverview,
                                 StockSignal)
from backend.services.broker_links import broker_link, is_kr_code, normalize_symbol
from backend.services.db import get_session

logger = logging.getLogger(__name__)
router = APIRouter()

_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}

# 뜻 설명 (기준이 코드에 있는 것만 · 명령문 · 신호 낱말 금지 · 4절)
_MEME_STAGES = (  # backend/discovery/meme_watch/confluence.py _label_and_emoji 와 같은 표
    ("BLAZING", "1.00 이상"), ("HOT", "0.75 이상"), ("WATCH", "0.50 이상"), ("OBSERVE", "0.25 이상"), ("SLEEP", "0.25 미만"))
_EXPLAIN_RANK = "점수는 0~100 종합 점수이고, 순위는 그날 후보 안의 순서입니다."


def _d(v) -> Optional[str]:
    """날짜·시각 → 'YYYY-MM-DD' (없으면 None)."""
    if v is None:
        return None
    return v.isoformat()[:10] if hasattr(v, "isoformat") else str(v)[:10]


def _f(v, nd: int = 1) -> str:
    return f"{v:.{nd}f}" if v is not None else "-"


def _md(v: Optional[str]) -> str:
    """'2026-10-29' → '10/29' (형식이 다르면 그대로)."""
    return f"{v[5:7]}/{v[8:10]}" if v and len(v) >= 10 and v[4] == "-" else (v or "")


Source = Callable[[str, bool], Awaitable[Optional[StockSignal]]]


# ─── 출처별 한 줄 (각각 StockSignal | None) ──────────────────────────────

async def _crazy(t: str, kr: bool) -> Optional[StockSignal]:
    from backend.services.models import CrazyPick

    async with get_session() as s:
        r = (await s.execute(select(CrazyPick).where(CrazyPick.ticker == t)
                             .order_by(desc(CrazyPick.pick_date), CrazyPick.rank).limit(1))).scalar_one_or_none()
    if r is None:
        return None
    return StockSignal(source="crazy", label="Crazy 후보", as_of=r.pick_date, link="/lab/crazy",
                       summary=f"{_md(r.pick_date)} {r.rank}위 · 점수 {_f(r.composite_score)}", explain=_EXPLAIN_RANK)


async def _moonshot(t: str, kr: bool) -> Optional[StockSignal]:
    from backend.services.models import MoonshotPick

    async with get_session() as s:
        r = (await s.execute(select(MoonshotPick).where(MoonshotPick.ticker == t)
                             .order_by(desc(MoonshotPick.pick_date), MoonshotPick.rank).limit(1))).scalar_one_or_none()
    if r is None:
        return None
    return StockSignal(source="moonshot", label="Moonshot 후보", as_of=r.pick_date, link="/lab/moonshot",
                       summary=f"{_md(r.pick_date)} {r.rank}위 · 점수 {_f(r.composite_score)}", explain=_EXPLAIN_RANK)


async def _serenity(t: str, kr: bool) -> Optional[StockSignal]:
    from backend.services.models import DiscoverySerenityScore, SerenitySignal

    async with get_session() as s:
        sc = (await s.execute(select(DiscoverySerenityScore).where(DiscoverySerenityScore.ticker == t))).scalar_one_or_none()
        sig = (await s.execute(select(SerenitySignal).where(SerenitySignal.ticker == t)
                               .order_by(desc(SerenitySignal.extracted_at)).limit(1))).scalar_one_or_none()
    if sc is None and sig is None:
        return None
    parts: list[str] = []
    if sc is not None:
        parts.append(f"15원칙 점수 {sc.total_score}" + (f" · 등급 {sc.serenity_tier}" if sc.serenity_tier else ""))
        if sc.auto_avoid:
            parts.append("자동 회피 후보")
    if sig is not None:
        parts.append(f"최근 언급 {_md(_d(sig.extracted_at))} {sig.sentiment} (신뢰도 {_f(sig.confidence, 2)})")
    as_of = _d(sig.extracted_at) if sig is not None else _d(sc.updated_at)
    return StockSignal(source="serenity", label="Serenity", as_of=as_of, link=f"/influencer/serenity/{t}",
                       summary=" · ".join(parts))


async def _meme(t: str, kr: bool) -> Optional[StockSignal]:
    from backend.services.models import MemeScoreHistory, MemeUniverse

    market = "KRX" if kr else "US"
    async with get_session() as s:
        u = (await s.execute(select(MemeUniverse).where(MemeUniverse.market == market, MemeUniverse.ticker == t,
                                                        MemeUniverse.is_active.is_(True)))).scalar_one_or_none()
        h = (await s.execute(select(MemeScoreHistory).where(MemeScoreHistory.ticker == t)
                             .order_by(desc(MemeScoreHistory.snapshot_at)).limit(1))).scalar_one_or_none()
    if u is None and h is None:
        return None
    if h is not None:
        summary = f"{_md(_d(h.snapshot_at))} 밈 점수 {_f(h.score)} · 단계 {h.label}"
        as_of = _d(h.snapshot_at)
    else:
        summary, as_of = "밈 추적 대상 · 점수 기록 아직 없음", _d(u.last_updated)
    explain = None
    if h is not None and h.label in {n for n, _ in _MEME_STAGES}:  # 옛 행 낱말이 표에 없으면 설명 생략
        explain = "단계는 밈 점수 구간입니다: " + " · ".join(f"{n} {c}" for n, c in _MEME_STAGES) + "."
    return StockSignal(source="meme", label="밈 워치", as_of=as_of, link="/lab/meme-watch", summary=summary, explain=explain)


async def _biotech(t: str, kr: bool) -> Optional[StockSignal]:
    """레이더 CSV (biotech 라우트와 같은 파일 찾기) · 순위 · 점수 · 시점만 (자체 계산 값 · 1119-01 비로그인에도 공개)."""
    import csv

    from backend.api.routes.biotech import _latest_radar_csv

    path = _latest_radar_csv()
    if not path or not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        for idx, row in enumerate(csv.DictReader(f), 1):
            if (row.get("ticker") or "").strip().upper() == t:
                return StockSignal(source="biotech", label="바이오 레이더", link="/biotech",
                                   as_of=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).date().isoformat(),
                                   summary=f"레이더 {idx}위 · 점수 {_f(float(row.get('score') or 0))} · 시점 {row.get('time_state') or '-'}",
                                   explain="바이오 레이더 점수는 검증 중입니다 · 추정 · 보장 아님.")
    return None


async def _activist(t: str, kr: bool) -> Optional[StockSignal]:
    """activist_state.json 읽기만 (ActivistState.load · 없으면 빈 상태 · SEC 보충 호출 안 함)."""
    from backend.discovery.activist.state import ActivistState

    evs = [e for e in ActivistState.load().events if (e.target_ticker or "").upper() == t]
    if not evs:
        return None
    e = max(evs, key=lambda x: (x.filing_date or "", x.detected_at or 0))
    return StockSignal(source="activist", label="행동주의 공시", as_of=e.filing_date or None, link="/activist-radar",
                       summary=f"{_md(e.filing_date)} {e.filer_name} · {e.form} · {e.intensity_label} (최근 공시 {len(evs)}건)")


async def _powderkeg(t: str, kr: bool) -> Optional[StockSignal]:
    from backend.services.models import PowderKegList

    async with get_session() as s:
        r = (await s.execute(select(PowderKegList).where(PowderKegList.ticker == t)
                             .order_by(desc(PowderKegList.created_at)).limit(1))).scalar_one_or_none()
    if r is None:
        return None
    label = {"passed": "통과", "rejected": "탈락", "cash_suspect": "현금 의심"}.get(r.status, r.status)
    extra = (f" · 순현금/시총 {_f(r.net_cash_ratio, 2)}" if r.net_cash_ratio is not None else "") + \
            (f" · F점수 {r.piotroski_f_score}" if r.piotroski_f_score is not None else "")
    return StockSignal(source="powderkeg", label="화약고", as_of=_d(r.created_at), link="/powderkeg",
                       summary=f"화약고 {label}{extra}",
                       explain="상태는 통과 · 탈락 · 현금 의심 중 하나입니다 (저장된 스크리닝 결과 기준).")


async def _blue_chip(t: str, kr: bool) -> Optional[StockSignal]:
    from backend.services.models import BlueChipCandidate

    async with get_session() as s:
        r = (await s.execute(select(BlueChipCandidate).where(BlueChipCandidate.ticker == t)
                             .order_by(desc(BlueChipCandidate.created_at), desc(BlueChipCandidate.id)).limit(1))).scalar_one_or_none()
    if r is None:
        return None
    # tier 는 1단계 시총 구간 (models.py BlueChipCandidate.tier) · 우량주 등급이 아님 (1029-01)
    cap = {"premium": "시총 10조 이상", "entry": "시총 5조 이상"}.get(r.tier, "시총 5조 미만")
    return StockSignal(source="blue_chip", label="우량주 후보", as_of=_d(r.created_at), link="/rulebook",
                       summary=f"5단계 중 {r.pass_count}단계 통과 · {cap}",
                       explain="통과 수는 5단계 검사 중 통과한 개수이고, 시총 구간은 1단계 기준입니다.")


async def _principles(t: str, kr: bool) -> Optional[StockSignal]:
    from backend.services.models import PrinciplesResult

    async with get_session() as s:
        r = (await s.execute(select(PrinciplesResult).where(PrinciplesResult.ticker == t)
                             .order_by(desc(PrinciplesResult.created_at)).limit(1))).scalar_one_or_none()
    if r is None:
        return None
    v = {"PASS": "통과", "FAIL": "미통과", "INSUFFICIENT_DATA": "자료 부족"}.get(r.verdict, r.verdict)
    per = f" · PER {_f(r.per_ttm)}" if r.per_ttm is not None else ""
    return StockSignal(source="principles", label="5원칙 스크리너", as_of=_d(r.created_at),
                       link="/principles/screener", summary=f"5원칙 {v}{per}",
                       explain="5원칙 검사 결과는 통과 · 미통과 · 자료 부족 중 하나입니다.")


async def _sector_leaders(t: str, kr: bool) -> Optional[StockSignal]:
    """DB 표만 (네이버 전망 호출 안 함)."""
    from backend.services.models import SectorLeader

    async with get_session() as s:
        rows = (await s.execute(select(SectorLeader).where(SectorLeader.ticker == t)
                                .order_by(SectorLeader.rank, SectorLeader.item))).scalars().all()
    if not rows:
        return None
    r = rows[0]
    more = f" 외 {len(rows) - 1}개 품목" if len(rows) > 1 else ""
    return StockSignal(source="sector_leaders", label="품목 수출 대장주", as_of=_d(r.computed_at), link="/sector-leaders",
                       summary=f"{r.item} {r.rank}위 · 상관계수 {_f(r.best_r, 2)} ({r.confidence}){more}")


async def _watchlist(t: str, kr: bool) -> Optional[StockSignal]:
    from backend.services.models import Watchlist

    async with get_session() as s:
        r = (await s.execute(select(Watchlist).where(Watchlist.ticker == t)
                             .order_by(desc(Watchlist.trade_date)).limit(1))).scalar_one_or_none()
    if r is None:
        return None
    return StockSignal(source="watchlist", label="개장 전 관심 목록", as_of=r.trade_date, link="/watchlist",
                       summary=f"{_md(r.trade_date)} {r.rank}위 · 점수 {_f(r.composite_score)}")


async def _sniper(t: str, kr: bool, admin: bool = False) -> Optional[StockSignal]:
    """국내 스나이퍼 · 진입 · 청산 상태는 주문 이력과 이어져 관리자만 (1119-01 Fable 1차 막음 2) · 그 밖에는 날짜 · 점수만."""
    from backend.services.models import SniperSignal

    async with get_session() as s:
        r = (await s.execute(select(SniperSignal).where(SniperSignal.ticker == t)
                             .order_by(desc(SniperSignal.detected_at)).limit(1))).scalar_one_or_none()
    if r is None:
        return None
    if admin:
        state = "청산" if r.exit_price is not None else ("진입" if r.entry_price is not None else "탐지")
    else:
        state = "탐지"
    return StockSignal(source="sniper", label="스나이퍼", as_of=_d(r.detected_at), link="/sniper",
                       summary=f"{_md(_d(r.detected_at))} {state} · 체결 흐름 점수 {_f(r.tape_score)}")


async def _safe(fn: Source, t: str, kr: bool, **kw) -> Optional[StockSignal]:
    """한 출처가 실패해도 그 줄만 빠진다."""
    try:
        return await fn(t, kr, **kw)
    except Exception as e:  # noqa: BLE001 — 칸 하나 때문에 화면 전체가 죽으면 안 됨
        logger.warning("[stock] %s 읽기 실패 (%s): %s", fn.__name__, t, e)
        return None


# ─── 1119-01 새 칸 · 일정 · 계속기업 · 후보 여부 (모두 저장 파일만 · 실패하면 그 칸만 null) ─────────

async def _is_candidate(t: str) -> Optional[bool]:
    """바이오 후보인지 (저장 파일 · 5분 기억). 읽기 실패 · 후보 목록이 비어 판단 못 함 → None (Fable 권고 3)."""
    try:
        from backend.services import biotech_quotes as bq

        n = bq.normalize(t)
        if n is None:
            return False
        cands = await bq.candidate_set()
        if not cands:
            return None
        return n in cands
    except Exception as e:  # noqa: BLE001
        logger.warning("[stock] 후보 여부 읽기 실패 (%s): %s", t, e)
        return None


def _catalysts(t: str) -> Optional[list[StockCatalyst]]:
    """최신 후보 파일 state_note 의 임상 완료 예정일 (결과 발표일이 아님) · 파일 없음 → None · 해석 실패 줄은 뺌."""
    try:
        from backend.api.routes import biotech as R

        notes = R._latest_candidate_notes()
        if not notes:
            return None
        note = notes.get(t, "")
        out: list[StockCatalyst] = []
        for m in R._NOTE_RE.finditer(note or ""):
            try:
                f = R._note_fields(m.group(0))
                if not f:
                    continue
                date.fromisoformat(f["event_date"])  # 날짜가 깨진 줄은 종목 API 쪽에서 뺀다 (공용 _note_fields 는 그대로)
                out.append(StockCatalyst(nct_id=f["nct_id"], phase=f["phase"], event_date=f["event_date"],
                                         days_to=int(f["days_to"]), past=int(f["days_to"]) < 0))
            except Exception as e:  # noqa: BLE001
                logger.warning("[stock] 일정 줄 해석 실패 (%s): %s", t, e)
        if note and not out:
            logger.warning("[stock] 일정 문장 해석 실패 (%s)", t)
        out.sort(key=lambda c: c.event_date)
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("[stock] 일정 읽기 실패 (%s): %s", t, e)
        return None


def _going_concern(t: str) -> Optional[StockGoingConcern]:
    """계속기업 문구 (SEC 공개 자료) · 표시 규칙은 /biotech 의 _going_concern_for 그대로 (Fable 권고 1).

    장부 파일 없음 → None (칸 숨김) · 장부에 이 회사 행 없음 → scope=out · 종목 → CIK 는 레이더 행 값 (없으면 SEC 표 역조회).
    """
    try:
        import csv

        from backend.api.routes import biotech as R

        store = R._going_concern_store()
        if store is None:
            return None
        cik = ""
        path = R._latest_radar_csv()
        if path and path.exists():
            with path.open(encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if (row.get("ticker") or "").strip().upper() == t:
                        cik = (row.get("cik") or "").strip()
                        break
        if not cik:
            cik = next((c for c, tk in R._cik_ticker_map().items() if tk == t), "")
        if not cik:
            return StockGoingConcern(scope="no_cik")   # 회사 번호를 못 찾음 (장부에 없음과 구별)
        try:
            row = store["rows"].get(str(int(cik)).zfill(10))
        except (ValueError, TypeError, KeyError, AttributeError):
            return StockGoingConcern(scope="no_cik")
        if not row:
            return StockGoingConcern(scope="out")      # 장부에 이 회사 행 없음
        gc = R._going_concern_for(store, cik)
        if gc is None:
            return StockGoingConcern(scope="unreadable")  # 행은 있는데 state 가 비었거나 깨짐
        return StockGoingConcern(scope="checked", detail=gc.model_dump())
    except Exception as e:  # noqa: BLE001
        logger.warning("[stock] 계속기업 읽기 실패 (%s): %s", t, e)
        return None


# ─── 이름 · 보유 · 판정 ──────────────────────────────────────────────────

async def _name(t: str, kr: bool) -> Optional[str]:
    try:
        if kr:
            from backend.services.stock_names import lookup_kr_name

            return await lookup_kr_name(t)
        from backend.services.models import MemeUniverse, TickerUniverse

        async with get_session() as s:
            n = (await s.execute(select(TickerUniverse.company_name).where(TickerUniverse.symbol == t))).scalar()
            if not n:
                n = (await s.execute(select(MemeUniverse.name).where(MemeUniverse.market == "US", MemeUniverse.ticker == t))).scalar()
        return n or None
    except Exception as e:  # noqa: BLE001
        logger.warning("[stock] 이름 조회 실패 (%s): %s", t, e)
        return None


async def _holding(t: str) -> Optional[StockHolding]:
    from backend.services.models import HoldingSnapshot

    try:
        async with get_session() as s:
            r = (await s.execute(select(HoldingSnapshot).where(HoldingSnapshot.symbol == t, HoldingSnapshot.kind == "holding")
                                 .order_by(desc(HoldingSnapshot.trade_date), desc(HoldingSnapshot.id)).limit(1))).scalar_one_or_none()
        if r is None:
            return None
        return StockHolding(qty=r.qty, avg_price=r.avg_price, currency=r.currency, as_of=_d(r.trade_date),
                            sold=(r.qty or 0) <= 0)
    except Exception as e:  # noqa: BLE001
        logger.warning("[stock] 보유 조회 실패 (%s): %s", t, e)
        return None


async def _judgments(t: str) -> list[StockJudgment]:
    from backend.services.models import UserJudgment

    try:
        async with get_session() as s:
            # 저장 때 대소문자가 섞였을 수 있어 양쪽을 대문자로 맞춰 비교 · 기간 제한 없음
            rows = (await s.execute(select(UserJudgment).where(func.upper(UserJudgment.ticker) == t)
                                    .order_by(desc(UserJudgment.ts), desc(UserJudgment.id)).limit(10))).scalars().all()
        return [StockJudgment(id=r.id, ts=r.ts.isoformat() if r.ts else None, page_source=r.page_source,
                              strategy=r.strategy, thesis_md=r.thesis_md, entry_price=r.entry_price,
                              invalidation_price=r.invalidation_price, target_price=r.target_price,
                              horizon_days=r.horizon_days, qty=r.qty, result_at_horizon=r.result_at_horizon)
                for r in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning("[stock] 판정 조회 실패 (%s): %s", t, e)
        return []


async def _broker(t: str) -> dict:
    from backend.services.models import TossStockCode

    row = None
    try:
        async with get_session() as s:
            row = (await s.execute(select(TossStockCode).where(TossStockCode.symbol == t))).scalar_one_or_none()
    except Exception as e:  # noqa: BLE001
        logger.warning("[stock] 토스 코드 조회 실패 (%s): %s", t, e)
    return broker_link(t, row)


# ─── 라우트 ──────────────────────────────────────────────────────────────

@router.get("/{ticker}", response_model=StockOverview)
async def get_stock(ticker: str, response: Response, role: str = Depends(get_current_role)) -> StockOverview:
    try:
        t = normalize_symbol(ticker)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="종목 코드 형식이 아닙니다.", headers=_NO_STORE) from e
    response.headers.update(_NO_STORE)

    admin = role == "admin"
    kr = is_kr_code(t)
    signals: list[StockSignal] = []

    async def add(fn: Source) -> None:
        sig = await _safe(fn, t, kr)
        if sig is not None:
            signals.append(sig)

    if not kr:
        # 1119-01 · 잠금 행 없음 — 자체 계산 신호는 비로그인에게도 보인다 (「자세히」 링크는 화면이 관리자에게만 보임)
        await add(_crazy)
        await add(_moonshot)
        await add(_serenity)
    await add(_meme)
    if not kr:
        await add(_biotech)
    await add(_activist)
    if kr:
        for fn in (_powderkeg, _blue_chip, _principles, _sector_leaders, _watchlist):
            await add(fn)
        sig = await _safe(_sniper, t, kr, admin=admin)
        if sig is not None:
            signals.append(sig)

    candidate = None if kr else await _is_candidate(t)
    market_label = None
    if kr:
        # 1128-01 · 저장된 표만 읽음 (바깥 호출 0 · Fable 막음 ㄱ) · 허용 목록에 있으면 가격 칸을 열 수 있음 (관리자 여부는 /quote 가 막음)
        from backend.services.kr_quotes import lookup_allowed

        try:
            hit = await lookup_allowed(t)
        except Exception as e:  # noqa: BLE001
            logger.warning("[stock] 국내 허용 목록 조회 실패 (%s): %s", t, e)
            hit = None
        candidate = hit is not None
        market_label = hit["market"] if hit and hit.get("market") in ("KOSPI", "KOSDAQ") else None
    cands_ok = candidate is True and not kr
    # 1128-01 ㉣ · 미국 비후보 (후보 여부를 읽었고 후보가 아닐 때만) · 저장 표 허용 목록만 읽음 (야후 호출 0 · Fable 막음 ㄹ ⑤)
    us_quote = False
    if not kr and candidate is False:
        from backend.services import us_quotes

        try:
            us_quote = await us_quotes.lookup_allowed(t, public=not admin) is not None  # 비관리자는 보유 · 판단 표 제외
        except Exception as e:  # noqa: BLE001
            logger.warning("[stock] 미국 허용 목록 조회 실패 (%s): %s", t, e)

    return StockOverview(
        ticker=t,
        market="KR" if kr else "US",
        name=await _name(t, kr),
        is_admin=admin,
        fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        broker_link=await _broker(t),
        holding=await _holding(t) if admin else None,
        judgments=await _judgments(t) if admin else None,
        signals=signals,
        catalysts=_catalysts(t) if cands_ok else None,
        going_concern=_going_concern(t) if cands_ok else None,
        quote_available=candidate,
        market_label=market_label,
        us_quote_available=us_quote,
    )


@router.get("/{ticker}/quote")
async def get_kr_quote(ticker: str, response: Response, _admin: str = Depends(require_sniper_token)) -> dict:
    """1128-01 · 종목 가격 · 의견 칸 (관리자 전용). 인증이 먼저라 비로그인 요청은 바깥을 부르지 않는다.

    국내 6자리 코드: 저장 목록(krx_stock_meta · DART 상장 행)에 없으면 404 · 네이버 (services/kr_quotes.py).
    미국 기호 (㉣): 바이오 후보는 404 (그쪽 길 /biotech/quote 를 쓴다) · 저장 허용 목록 밖은 404 · 야후는 하루 1번 · 50종목 (services/us_quotes.py).
    """
    from backend.services import kr_quotes

    response.headers.update(_NO_STORE)
    if not is_kr_code((ticker or "").strip().upper()):
        return await _us_quote(ticker)
    info = await kr_quotes.lookup_allowed(ticker)
    if info is None:
        raise HTTPException(status_code=404, detail="목록에 없는 국내 종목입니다.", headers=_NO_STORE)
    return await kr_quotes.quote_view(ticker, info=info)


async def _us_quote(ticker: str) -> dict:
    from backend.services import biotech_quotes as bq
    from backend.services import us_quotes

    t = us_quotes.normalize(ticker)
    if t is None:
        raise HTTPException(status_code=404, detail="종목 코드 형식이 아닙니다.", headers=_NO_STORE)
    cands = await bq.candidate_set()
    if not cands:   # 후보 목록을 못 읽으면 후보인지 몰라 새로 받지 않는다 (같은 기호를 두 길로 받는 일 방지 · 권고 ㅁ)
        raise HTTPException(status_code=404, detail="후보 목록을 읽지 못해 지금은 열 수 없습니다.", headers=_NO_STORE)
    if bq.normalize(t) in cands:
        raise HTTPException(status_code=404, detail="바이오 후보 종목은 바이오 화면의 가격 칸을 씁니다.", headers=_NO_STORE)
    if await us_quotes.lookup_allowed(t) is None:
        raise HTTPException(status_code=404, detail="이 사이트 저장 목록에 없는 미국 종목입니다.", headers=_NO_STORE)
    return await us_quotes.quote_view(t)
