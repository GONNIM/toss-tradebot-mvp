"""신호 장부 · 사건 묶음과 유형 성립 날짜 (1119-03 ① · 기획서 3-3 · 3-4 · Fable 조건 마).

순수 함수 + 성적 한 줄 저장(upsert). 공시 수집은 ② — 여기서는 바깥 호출이 없다.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Optional, Sequence

from sqlalchemy import select

from backend.services.db import get_session

from .models import SignalOutcome
from .scoring import EVENT_WINDOW_TRADING_DAYS


def group_events(
    signals: Sequence[tuple[str, date]], trading_days: Sequence[date],
    window: int = EVENT_WINDOW_TRADING_DAYS,
) -> list[dict[str, Any]]:
    """(코드, 신호 날짜) 목록 → 사건 목록. 같은 종목에서 첫 신호 날짜부터 window 거래일 안 신호는 한 사건.

    창은 첫 신호 날짜에 고정한다 — 뒤 신호가 와도 늘어나지 않는다. 창 밖 신호는 새 사건의 첫 신호.
    """
    days = sorted(trading_days)
    pos = {d: i for i, d in enumerate(days)}

    def idx(d: date) -> float:
        if d in pos:
            return float(pos[d])
        return sum(1 for x in days if x <= d) - 0.5      # 비거래일은 앞 거래일 뒤 반 칸

    events: list[dict[str, Any]] = []
    open_by_code: dict[str, dict[str, Any]] = {}
    for code, d in sorted(signals, key=lambda s: (s[0], s[1])):
        ev = open_by_code.get(code)
        if ev is not None and idx(d) - idx(ev["first_signal_date"]) <= window:
            ev["signals"].append(d)
            continue
        ev = {"code": code, "first_signal_date": d, "signals": [d]}
        open_by_code[code] = ev
        events.append(ev)
    return events


def kr_i2_establish_date(buys: Sequence[tuple[str, date]], window_days: int = 30) -> Optional[date]:
    """KR-I2 성립 날짜 = 서로 다른 2명 이상이 window_days 안에 접수한 공시의 둘째 사람 접수일.

    buys = (사람, 접수일). 진입 전까지 접수된 건만 넘겨야 한다 (미래 정보 금지).
    성립은 한 번 — 가장 이른 성립 날짜 하나를 돌려준다. 같은 성립의 뒤 매수(셋째 등)는 새 성립이 아니다
    (새 표본 규칙은 rules-v1).
    """
    seq = sorted(buys, key=lambda b: b[1])
    for i, (who, d) in enumerate(seq):
        for who2, d2 in seq[:i]:
            if who2 != who and timedelta(0) <= d - d2 <= timedelta(days=window_days):
                return d
    return None


async def upsert_outcome(
    *, market: str, code: str, signal_type: str, horizon_days: int, entry_date: date,
    event_id: Optional[int] = None, entry_price: Optional[float] = None, exit_price: Optional[float] = None,
    return_pct: Optional[float] = None, index_return_pct: Optional[float] = None,
    excess_pct: Optional[float] = None, cost_pct: Optional[float] = None, status: str = "ok",
) -> bool:
    """성적 한 줄 저장 · (시장 · 코드 · 유형 · 진입 날짜 · 기간)이 같으면 새로 쓰지 않는다 (같은 성립은 한 줄).

    새로 썼으면 True, 이미 있어 건너뛰었으면 False.
    """
    async with get_session() as session:
        found = (await session.execute(select(SignalOutcome.id).where(
            SignalOutcome.market == market, SignalOutcome.code == code,
            SignalOutcome.signal_type == signal_type, SignalOutcome.entry_date == entry_date,
            SignalOutcome.horizon_days == horizon_days,
        ))).first()
        if found is not None:
            return False
        session.add(SignalOutcome(
            event_id=event_id, market=market, code=code, signal_type=signal_type,
            horizon_days=horizon_days, entry_date=entry_date, entry_price=entry_price,
            exit_price=exit_price, return_pct=return_pct, index_return_pct=index_return_pct,
            excess_pct=excess_pct, cost_pct=cost_pct, status=status,
        ))
    return True


def dumps_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
