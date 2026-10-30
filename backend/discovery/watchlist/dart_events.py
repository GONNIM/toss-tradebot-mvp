"""DART 공시 → Watchlist 이벤트 신호 · 1030-04.

밈 감시(discovery/meme_watch/catalyst_signal.py)가 매시 MemeCatalystEvent(source="dart") 로 저장한 공시를
읽기만 한다 — DART 를 새로 호출하지 않는다 (호출 수 불변).

허용 목록 (제목에 있으면 source="dart_disclosure" · intensity 1.0 · 점수의 이벤트 칸 1.0):
  단일판매·공급계약 · 임상 · 품목허가 · 최대주주 변경 · 자기주식 취득 · 무상증자
    → 수주·임상·허가·지배구조·주주환원 = 주가에 직접 닿는 재료로 사용자가 정한 목록 (10/30 결정 4).
제외 목록 (제목에 있으면 source="dart_caution" · intensity 0 · 점수 0 · 화면 「주의 공시」):
  유상증자 · 전환사채 · 신주인수권부사채 · 감자 · 횡령 · 배임 · 감사의견
    → 주주가치 훼손·신뢰 문제 공시. 이 종목이 다른 이유로 목록에 올라와도 화면이 경고를 보여 준다.
둘 다 걸리면 제외(주의)가 이긴다. [기재정정]·[첨부정정] 공시는 새 재료가 아니라 허용 쪽에서는 건너뛴다.

공시 제목의 가운뎃점(ㆍ · ･)·공백·괄호는 비교 전에 없앤다 (「단일판매ㆍ공급계약체결」 = 「단일판매 공급계약」).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select

from backend.services.db import get_session
from backend.services.models import MemeCatalystEvent

from .store import next_trade_date, upsert_signal

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))

ALLOW_KEYWORDS = ("단일판매공급계약", "임상", "품목허가", "최대주주변경", "자기주식취득", "무상증자")
CAUTION_KEYWORDS = ("유상증자", "전환사채", "신주인수권부사채", "감자", "횡령", "배임", "감사의견")

# 어제·오늘 공시만 (밈 감시가 매시 적재 · 08:20 과 20:40 두 번 읽으므로 하루 겹침이면 충분)
_LOOKBACK_DAYS = 1

_NOISE = re.compile(r"[\s·ㆍ･・,.\[\]()「」]")
_CORRECTION = ("기재정정", "첨부정정", "첨부추가")


def _norm(text: str) -> str:
    return _NOISE.sub("", text or "")


def classify(title: str) -> Optional[str]:
    """공시 제목 → "dart_caution" | "dart_disclosure" | None (관심 밖)."""
    n = _norm(title)
    if any(k in n for k in CAUTION_KEYWORDS):
        return "dart_caution"
    if any(k in n for k in ALLOW_KEYWORDS):
        if any(c in n for c in _CORRECTION):
            return None
        return "dart_disclosure"
    return None


async def collect_dart_events(now: Optional[datetime] = None) -> dict[str, Any]:
    """저장된 DART 공시를 읽어 watchlist_signal 로 · 08:20·20:40 KST 잡."""
    now = now or datetime.now(tz=timezone.utc)
    since = (now.astimezone(_KST).date() - timedelta(days=_LOOKBACK_DAYS))
    since_dt = datetime(since.year, since.month, since.day)   # occurred_at 은 날짜(자정) · naive
    async with get_session() as session:
        rows = (await session.execute(
            select(MemeCatalystEvent)
            .where(MemeCatalystEvent.source == "dart", MemeCatalystEvent.occurred_at >= since_dt)
        )).scalars().all()

    sig_date = next_trade_date(now)
    stats = {"read": len(rows), "disclosure": 0, "caution": 0, "skipped_existing": 0}
    for r in rows:
        source = classify(r.event_label or "")
        if source is None or not r.ticker:
            continue
        row_id = await upsert_signal(
            ticker=r.ticker,
            source=source,
            # 같은 종목의 공시 둘이 한 번에 들어와도 저장 계층의 5분 중복 규칙에 안 걸리게 공시마다 type 을 다르게 둔다
            signal_type=f"disc_{r.event_id}"[:30],
            intensity=1.0 if source == "dart_disclosure" else 0.0,
            payload={
                "title": (r.event_label or "")[:200], "event_id": r.event_id,
                "rcept_no": r.event_id, "occurred": r.occurred_at.date().isoformat() if r.occurred_at else None,
                "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r.event_id}",
            },
            trade_date=sig_date,
            detected_at=now,
            dedup_url=r.event_id,
        )
        if row_id is None:
            stats["skipped_existing"] += 1
        else:
            stats["disclosure" if source == "dart_disclosure" else "caution"] += 1
    logger.info("[dart_events] %s", stats)
    return stats
