"""Watchlist Finalize · Sprint 2 Week 2 T60·T61.

08:30 KST 잡:
  1. next_trade_date 계산 (즉시 오늘 or 다음 영업일)
  2. watchlist_signal 조회 → composite_score 계산
  3. Top N (기본 30) 승격 → watchlist 테이블 write
  4. locked=True 항목은 유지 · 재승격
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, select

from backend.discovery.live_tape.universe import list_universe
from backend.services.db import get_session
from backend.services.models import Watchlist

from .scoring import score_signals
from .store import next_trade_date, signals_for_date

logger = logging.getLogger(__name__)

# Top N 후보 확정 · v1 30 · UI 편집 (Week 3)
DEFAULT_TOP_N = 30


async def finalize_watchlist(
    trade_date: Optional[str] = None,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, Any]:
    """대상 거래일 Watchlist Top N 재생성.

    Args:
        trade_date: YYYY-MM-DD · None 이면 next_trade_date() 사용
        top_n: 상위 N (locked 항목 별도 유지)

    Returns:
        {"trade_date": ..., "signals_read": N, "top_n": M, "locked_kept": K, "written": W}
    """
    if trade_date is None:
        # 08:30 KST 잡 시점 · 오늘 마감 예정일이므로 오늘 날짜
        # KST timezone
        kst = timezone(timedelta(hours=9))
        trade_date = datetime.now(tz=kst).date().isoformat()

    # 시그널 조회 (당일 trade_date 배정된 것 · store.next_trade_date 로직으로 저녁~새벽 감지 결과)
    signals = await signals_for_date(trade_date)
    ticker_scores = score_signals(signals)

    # 유니버스 name 매핑
    universe_names = {u["ticker"]: u["name"] for u in await list_universe(limit=1000)}

    # 기존 locked=True 항목 유지 (사용자 수동 lock)
    async with get_session() as session:
        stmt = select(Watchlist).where(
            Watchlist.trade_date == trade_date, Watchlist.locked == True   # noqa: E712
        )
        locked_rows = (await session.execute(stmt)).scalars().all()
        locked_tickers = {r.ticker for r in locked_rows}
        locked_snapshots = [
            {
                "ticker": r.ticker, "name": r.name, "composite_score": r.composite_score,
                "news_score": r.news_score, "board_score": r.board_score,
                "youtube_score": r.youtube_score, "event_score": r.event_score,
                "prev_day_score": r.prev_day_score,
                "source_breakdown": r.source_breakdown,
                "added_by": r.added_by, "locked": True,
            }
            for r in locked_rows
        ]

        # 기존 non-locked 삭제 → 재승격
        await session.execute(
            delete(Watchlist).where(
                Watchlist.trade_date == trade_date, Watchlist.locked == False   # noqa: E712
            )
        )

        # Top N 승격 (locked 제외 자리만)
        remaining_slots = max(0, top_n - len(locked_tickers))
        auto_picks: list[dict[str, Any]] = []
        for score in ticker_scores:
            if score.ticker in locked_tickers:
                continue
            if len(auto_picks) >= remaining_slots:
                break
            auto_picks.append({
                "ticker": score.ticker,
                "name": universe_names.get(score.ticker),
                "composite_score": score.composite_score,
                "news_score": score.news_score,
                "board_score": score.board_score,
                "youtube_score": score.youtube_score,
                "event_score": score.event_score,
                "prev_day_score": score.prev_day_score,
                "source_breakdown": json.dumps(score.source_breakdown, ensure_ascii=False),
                "added_by": "auto",
                "locked": False,
            })

        # 통합 정렬 · rank 부여
        merged = locked_snapshots + auto_picks
        merged.sort(key=lambda x: -x["composite_score"])
        for rank, item in enumerate(merged, start=1):
            if item.get("locked"):
                # 기존 row 유지 · rank 만 재계산
                stmt = select(Watchlist).where(
                    Watchlist.trade_date == trade_date, Watchlist.ticker == item["ticker"]
                )
                existing = (await session.execute(stmt)).scalar_one_or_none()
                if existing:
                    existing.rank = rank
                    continue
            row = Watchlist(
                trade_date=trade_date,
                ticker=item["ticker"],
                name=item.get("name"),
                rank=rank,
                composite_score=item["composite_score"],
                news_score=item["news_score"],
                board_score=item["board_score"],
                youtube_score=item["youtube_score"],
                event_score=item["event_score"],
                prev_day_score=item["prev_day_score"],
                source_breakdown=item.get("source_breakdown"),
                locked=item.get("locked", False),
                added_by=item.get("added_by", "auto"),
            )
            session.add(row)

    stats = {
        "trade_date": trade_date,
        "signals_read": len(signals),
        "candidates_scored": len(ticker_scores),
        "locked_kept": len(locked_tickers),
        "auto_picked": len(auto_picks),
        "written": len(locked_tickers) + len(auto_picks),
        "top_n": top_n,
    }
    logger.info("[watchlist.finalize] %s", stats)
    return stats


async def list_watchlist(trade_date: Optional[str] = None) -> list[dict[str, Any]]:
    """지정 거래일 Watchlist 조회 · rank 오름차순."""
    if trade_date is None:
        trade_date = next_trade_date()
    async with get_session() as session:
        stmt = (
            select(Watchlist)
            .where(Watchlist.trade_date == trade_date)
            .order_by(Watchlist.rank.asc())
        )
        rows = (await session.execute(stmt)).scalars().all()
    return [_serialize(r) for r in rows]


def _serialize(r: Watchlist) -> dict[str, Any]:
    return {
        "id": r.id,
        "trade_date": r.trade_date,
        "ticker": r.ticker,
        "name": r.name,
        "rank": r.rank,
        "composite_score": r.composite_score,
        "news_score": r.news_score,
        "board_score": r.board_score,
        "youtube_score": r.youtube_score,
        "event_score": r.event_score,
        "prev_day_score": r.prev_day_score,
        "source_breakdown": json.loads(r.source_breakdown) if r.source_breakdown else None,
        "locked": r.locked,
        "added_by": r.added_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }
