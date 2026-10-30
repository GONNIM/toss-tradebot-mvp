"""Watchlist API 라우트 · Sprint 2 Week 2 T62·T63.

조회 (인증 없음):
    GET /watchlist           — trade_date 별 · rank 순 Top N
    GET /watchlist/signals   — 원본 signal (source 별) · 디버그·breakdown 조회
    GET /watchlist/dates     — 최근 Watchlist 존재 거래일 리스트
    GET /watchlist/sources   — 칸별 수집 상태 (키 유무 참/거짓 · 마지막 신호·저장 시각 · 1030-02·04)
    GET /watchlist          — items[].evidence · score_version (칸별 근거 · 1030-04)

편집·실행 (X-API-Token · SNIPER_LIVE_ENABLED 미요구):
    POST   /watchlist/finalize     — 수동 finalize 트리거 (즉시 재계산)
    POST   /watchlist/manual       — 수동 add · locked=True
    PATCH  /watchlist/{id}/lock    — lock 토글
    DELETE /watchlist/{id}         — 삭제
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import distinct, func, select

from backend.api.auth import require_sniper_token
from backend.discovery.live_tape.universe import list_universe
from backend.discovery.watchlist.finalize import (
    DEFAULT_TOP_N,
    finalize_watchlist,
    list_watchlist,
)
from backend.discovery.watchlist import (
    assembly, collecting, gov_press, news_rss, scoring, source_groups,
)
from backend.discovery.watchlist.metrics import Trade, compute_metrics, evaluate_dod
from backend.discovery.watchlist.store import next_trade_date, recent_signals, signals_for_date
from backend.services.db import get_session
from backend.services.models import SniperSignal, Watchlist, WatchlistSignal

logger = logging.getLogger(__name__)
router = APIRouter()


# ═══════════════════════════════════════════════════════════════
# 조회 (인증 없음)
# ═══════════════════════════════════════════════════════════════
@router.get("")
async def get_watchlist(
    trade_date: Optional[str] = Query(None, description="YYYY-MM-DD · 기본: next_trade_date"),
) -> dict[str, Any]:
    """지정 거래일 Watchlist · rank 오름차순."""
    td = trade_date or next_trade_date()
    items = await list_watchlist(td)
    return {
        "trade_date": td,
        "size": len(items),
        "items": items,
    }


@router.get("/signals")
async def get_signals(
    trade_date: Optional[str] = Query(None),
    hours: int = Query(0, ge=0, le=72, description="0이면 trade_date 사용 · 아니면 최근 N시간"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    """원본 signal 조회 (breakdown 감사·튜닝)."""
    if hours > 0:
        items = await recent_signals(hours=hours, limit=limit)
    else:
        td = trade_date or next_trade_date()
        items = await signals_for_date(td)
    return {"count": len(items), "items": items[:limit]}


@router.get("/report")
async def get_report(days: int = Query(30, ge=1, le=180)) -> dict[str, Any]:
    """Sprint 2 DoD 리포트 · 실 매매 이력 → 메트릭 → pass/fail 판정.

    실 forward test 진행 상황 감시용. 5거래일 완주 후 total_pass 확인.
    """
    since = datetime.now(tz=timezone.utc) - timedelta(days=days)
    trades: list[Trade] = []
    async with get_session() as session:
        # SniperSignal 이 execute_watchlist / sniper 공유이므로 둘 다 포함
        stmt = (
            select(SniperSignal)
            .where(SniperSignal.detected_at >= since)
            .where(SniperSignal.entry_price.is_not(None))
            .where(SniperSignal.exit_price.is_not(None))
            .order_by(SniperSignal.detected_at.asc())
        )
        rows = (await session.execute(stmt)).scalars().all()
    for r in rows:
        if r.entry_price is None or r.exit_price is None:
            continue
        trades.append(Trade(
            ticker=r.ticker,
            entry_price=float(r.entry_price),
            exit_price=float(r.exit_price),
            entry_time=r.detected_at,
            exit_time=None,
            reason=r.reason,
        ))

    metrics = compute_metrics(trades)
    dod = evaluate_dod(metrics)

    return {
        "since": since.isoformat(),
        "window_days": days,
        "closed_trades": len(trades),
        "metrics": dod.metrics,
        "checks": [
            {"name": c.name, "target": c.target, "actual": c.actual, "passed": c.passed}
            for c in dod.checks
        ],
        "total_pass": dod.total_pass,
    }


@router.get("/dates")
async def get_dates(limit: int = Query(30, ge=1, le=100)) -> list[str]:
    """Watchlist 존재 거래일 리스트 (최근 → 과거)."""
    async with get_session() as session:
        stmt = (
            select(distinct(Watchlist.trade_date))
            .order_by(Watchlist.trade_date.desc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
    return [r for r in rows if r]


# 점수 계산과 같은 출처 분류 (source_groups) · 화면 키는 board 를 유지한다 (옛 종토방 컬럼 = 개인 관심 · 화면 호환)
_KEY_OF_CATEGORY = {"news": "news", "interest": "board", "youtube": "youtube", "event": "event", "prev_day": "prev_day"}


def _category(source: str) -> Optional[str]:
    cat = source_groups.category_of(source)
    return _KEY_OF_CATEGORY.get(cat) if cat else None


def _rank_state_note(kinds: list[str], status: dict[str, Any]) -> tuple[str, Optional[str]]:
    """순위 칸의 상태 문구 · (note, 마지막 저장 시각 iso).

    20:30 저장 상태(rank_status.json)와 장중 누적을 합쳐 「저장함 / 집계 없음 / 아직 안 돌았음」을 말한다.
    """
    daily = (status.get("daily") or {})
    states = [(daily.get("kinds") or {}).get(k, {}) for k in kinds]
    saved = [s for s in states if s.get("state") == "saved"]
    if not daily:
        return "아직 저장 전 · 매일 20:30 에 저장", None
    last = daily.get("run_at")
    if saved:
        missing = [k for k, s in zip(kinds, states) if s.get("state") != "saved"]
        note = f"{daily.get('date', '')} 저장"
        if missing:
            note += " · 일부 종류는 집계 없음"
        return note, last
    rt = status.get("realtime") or {}
    if rt.get("date") == daily.get("date") and rt.get("changed"):
        return f"{daily.get('date', '')} 집계 없음 · 장중 순위로 대신함", last
    return f"{daily.get('date', '')} 집계 없음", last


@router.get("/sources")
async def get_sources() -> dict[str, Any]:
    """칸별 수집 상태 · 수집하지 않는 칸은 화면에 0 대신 「수집 안 함」 (1030-02·1030-04).

    키·주소 값은 내보내지 않고 설정 여부(참/거짓)만 내보낸다.
    수집 여부는 점수 계산(finalize)과 같은 collecting.collecting_categories() 한 곳에서 판정한다.
    """
    from backend.discovery.watchlist import rank_signals

    col = collecting.collecting_categories()
    asm_key = assembly._api_key() is not None
    dart_key = collecting.dart_configured()
    gov = gov_press.configured_sources()
    event_notes = []
    if not dart_key:
        event_notes.append("DART 키 없음")
    if not asm_key:
        event_notes.append("국회 의안 키 없음")
    if not gov:
        event_notes.append("보도자료 주소 없음")

    since = datetime.now(tz=timezone.utc) - timedelta(days=7)
    async with get_session() as session:
        rows = (await session.execute(
            select(WatchlistSignal.source, func.max(WatchlistSignal.detected_at))
            .where(WatchlistSignal.detected_at >= since)
            .group_by(WatchlistSignal.source)
        )).all()
    last: dict[str, Optional[datetime]] = {k: None for k in ("news", "board", "youtube", "event", "prev_day")}
    for source, at in rows:
        key = _category(source or "")
        if key and at is not None and (last[key] is None or at > last[key]):
            last[key] = at

    def _iso(v: Optional[datetime]) -> Optional[str]:
        if v is None:
            return None
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()

    status = rank_signals.read_status()
    interest_note, interest_saved = _rank_state_note(
        [rank_signals.KIND_INDIVIDUAL, "toss_amount", "toss_volume"], status)
    prev_note, prev_saved = _rank_state_note(["market_amount", "market_volume"], status)
    toss_note = "" if col["interest"] else "토스 키 없음"

    sources = [
        {"key": "news", "label": "뉴스", "collecting": col["news"],
         "note": f"언론 RSS {len(news_rss.RSS_SOURCES)}곳 · 같은 언론의 피드는 한 곳으로 셈"},
        {"key": "board", "label": "개인 관심", "collecting": col["interest"],
         "note": toss_note or f"토스 순위(개인 순매수·토스증권 체결) 100위 새 진입 · {interest_note}",
         "last_saved_at": interest_saved},
        {"key": "youtube", "label": "유튜브", "collecting": col["youtube"],
         "note": "" if col["youtube"] else "키 없음"},
        {"key": "event", "label": "이벤트", "collecting": col["event"], "note": " · ".join(event_notes)},
        {"key": "prev_day", "label": "전일", "collecting": col["prev_day"],
         "note": toss_note or f"시장 거래대금·거래량 100위 새 진입 · {prev_note}",
         "last_saved_at": prev_saved},
    ]
    for s_ in sources:
        s_["last_signal_at"] = _iso(last[s_["key"]])
    return {"sources": sources, "score_version": scoring.SCORE_VERSION}


# ═══════════════════════════════════════════════════════════════
# 편집·실행 (X-API-Token)
# ═══════════════════════════════════════════════════════════════
@router.post("/finalize", dependencies=[Depends(require_sniper_token)])
async def trigger_finalize(
    trade_date: Optional[str] = Body(None, embed=True),
    top_n: int = Body(DEFAULT_TOP_N, embed=True),
) -> dict[str, Any]:
    """수동 finalize 트리거 · 08:30 KST 잡과 동일."""
    if top_n < 1 or top_n > 100:
        raise HTTPException(status_code=400, detail="top_n must be 1..100")
    stats = await finalize_watchlist(trade_date=trade_date, top_n=top_n)
    return stats


@router.post("/manual", dependencies=[Depends(require_sniper_token)])
async def add_manual(
    ticker: str = Body(..., embed=True),
    trade_date: Optional[str] = Body(None, embed=True),
    name: Optional[str] = Body(None, embed=True),
) -> dict[str, Any]:
    """사용자 수동 add · locked=True."""
    td = trade_date or next_trade_date()
    ticker = ticker.strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker required")

    resolved_name = name
    if resolved_name is None:
        from backend.discovery.watchlist.matcher import get_matcher
        matcher = get_matcher()
        await matcher.ensure_loaded()
        for e in matcher.entries():
            if e.ticker == ticker:
                resolved_name = e.name
                break
        if resolved_name is None:
            for u in await list_universe(limit=1000):
                if u["ticker"] == ticker:
                    resolved_name = u.get("name")
                    break

    async with get_session() as session:
        stmt = select(Watchlist).where(
            Watchlist.trade_date == td, Watchlist.ticker == ticker,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            # 이미 있으면 locked 만 True 로 승격
            existing.locked = True
            existing.added_by = "user"
            row_id = existing.id
        else:
            # 새 lock 추가 · rank 는 finalize 재실행 시 재부여 · 임시 99
            row = Watchlist(
                trade_date=td, ticker=ticker, name=resolved_name,
                rank=99, composite_score=0.0,
                news_score=0.0, board_score=0.0, youtube_score=0.0,
                event_score=0.0, prev_day_score=0.0,
                source_breakdown=None, locked=True, added_by="user",
            )
            session.add(row)
            await session.flush()
            row_id = row.id

    logger.info("[watchlist] manual add · %s @ %s · id=%d", ticker, td, row_id)
    return {"id": row_id, "ticker": ticker, "trade_date": td, "locked": True}


@router.patch("/{item_id}/lock", dependencies=[Depends(require_sniper_token)])
async def toggle_lock(
    item_id: int,
    locked: bool = Body(..., embed=True),
) -> dict[str, Any]:
    """lock 상태 토글."""
    async with get_session() as session:
        stmt = select(Watchlist).where(Watchlist.id == item_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"not found · id={item_id}")
        row.locked = bool(locked)
        if locked:
            row.added_by = "user"
    return {"id": item_id, "locked": bool(locked)}


@router.delete("/{item_id}", dependencies=[Depends(require_sniper_token)])
async def delete_item(item_id: int) -> dict[str, Any]:
    """Watchlist 항목 삭제. locked 여부 무관."""
    async with get_session() as session:
        stmt = select(Watchlist).where(Watchlist.id == item_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"not found · id={item_id}")
        await session.delete(row)
    return {"deleted": True, "id": item_id}
