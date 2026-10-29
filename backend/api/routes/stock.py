"""종목 한 장 API (1022-10 3단계) · GET /api/v1/stock/{ticker}.

- 저장된 자료 (DB · 로컬 파일) 만 읽는다. 외부 HTTP 0 · 쓰기 0 · SEC 보충·토스 호출 없음.
- 역할은 get_current_role (예외 없음 · 접근 기록 안 씀). 관리자 전용 자료는 비로그인에게 늘 null / locked.
- 출처마다 작은 함수 하나 · 실패하면 그 칸만 빠지고 200.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import desc, func, select

from backend.api.auth import get_current_role
from backend.api.schemas import StockHolding, StockJudgment, StockOverview, StockSignal
from backend.services.broker_links import broker_link, is_kr_code, normalize_symbol
from backend.services.db import get_session

logger = logging.getLogger(__name__)
router = APIRouter()

_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
_LOCKED_SUMMARY = "로그인하면 보입니다"


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
                       summary=f"{_md(r.pick_date)} {r.rank}위 · 점수 {_f(r.composite_score)}")


async def _moonshot(t: str, kr: bool) -> Optional[StockSignal]:
    from backend.services.models import MoonshotPick

    async with get_session() as s:
        r = (await s.execute(select(MoonshotPick).where(MoonshotPick.ticker == t)
                             .order_by(desc(MoonshotPick.pick_date), MoonshotPick.rank).limit(1))).scalar_one_or_none()
    if r is None:
        return None
    return StockSignal(source="moonshot", label="Moonshot 후보", as_of=r.pick_date, link="/lab/moonshot",
                       summary=f"{_md(r.pick_date)} {r.rank}위 · 점수 {_f(r.composite_score)}")


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
    return StockSignal(source="meme", label="밈 워치", as_of=as_of, link="/lab/meme-watch", summary=summary)


async def _biotech(t: str, kr: bool) -> Optional[StockSignal]:
    """레이더 CSV (biotech 라우트와 같은 파일 찾기) · biotech 화면이 관리자 전용이라 여기도 관리자만 (호출 쪽에서 거름)."""
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
                                   summary=f"레이더 {idx}위 · 점수 {_f(float(row.get('score') or 0))} · 시점 {row.get('time_state') or '-'}")
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
                       summary=f"화약고 {label}{extra}")


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
                       summary=f"5단계 중 {r.pass_count}단계 통과 · {cap}")


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
                       link="/principles/screener", summary=f"5원칙 {v}{per}")


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


async def _sniper(t: str, kr: bool) -> Optional[StockSignal]:
    from backend.services.models import SniperSignal

    async with get_session() as s:
        r = (await s.execute(select(SniperSignal).where(SniperSignal.ticker == t)
                             .order_by(desc(SniperSignal.detected_at)).limit(1))).scalar_one_or_none()
    if r is None:
        return None
    state = "청산" if r.exit_price is not None else ("진입" if r.entry_price is not None else "탐지")
    return StockSignal(source="sniper", label="스나이퍼", as_of=_d(r.detected_at), link="/sniper",
                       summary=f"{_md(_d(r.detected_at))} {state} · 체결 흐름 점수 {_f(r.tape_score)}")


async def _safe(fn: Source, t: str, kr: bool) -> Optional[StockSignal]:
    """한 출처가 실패해도 그 줄만 빠진다."""
    try:
        return await fn(t, kr)
    except Exception as e:  # noqa: BLE001 — 칸 하나 때문에 화면 전체가 죽으면 안 됨
        logger.warning("[stock] %s 읽기 실패 (%s): %s", fn.__name__, t, e)
        return None


def _locked(source: str, label: str, link: str) -> StockSignal:
    return StockSignal(source=source, label=label, as_of=None, summary=_LOCKED_SUMMARY, link=link, locked=True)


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
        raise HTTPException(status_code=400, detail="종목 기호 형식이 올바르지 않습니다.", headers=_NO_STORE) from e
    response.headers.update(_NO_STORE)

    admin = role == "admin"
    kr = is_kr_code(t)
    signals: list[StockSignal] = []

    async def add(fn: Source) -> None:
        sig = await _safe(fn, t, kr)
        if sig is not None:
            signals.append(sig)

    if not kr:
        # Crazy · Moonshot 은 관리자 전용 — 비로그인에는 자료 유무와 상관없이 잠금 행만
        if admin:
            await add(_crazy)
            await add(_moonshot)
        else:
            signals.append(_locked("crazy", "Crazy 후보", "/lab/crazy"))
            signals.append(_locked("moonshot", "Moonshot 후보", "/lab/moonshot"))
        await add(_serenity)
    await add(_meme)
    if not kr and admin:  # 바이오 레이더 화면이 관리자 전용
        await add(_biotech)
    await add(_activist)
    if kr:
        for fn in (_powderkeg, _blue_chip, _principles, _sector_leaders, _watchlist, _sniper):
            await add(fn)

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
    )
