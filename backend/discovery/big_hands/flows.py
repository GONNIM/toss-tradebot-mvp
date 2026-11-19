"""㉤ 외국인 · 기관 순매수 · 순매도 저장 (1119-03 ① · 기획서 3-7 · Fable 조건 나).

- 순위 수집이 이미 받은 investor-trading 응답에서 꺼낸다 · 호출을 늘리지 않는다.
- 기존 저장(watchlist_rank_daily)이 커밋된 뒤, 자기 세션에서 쓴다 · 실패하면 경고 로그만 (호출한 쪽이 감싼다).
- `ALL_KINDS` · `KIND_SOURCE` · `rank_status.json` 에 넣지 않는다 · 쓰는 중 바깥 호출 · 알림 없음 (교훈 #20).
- 묶음(외국인 · 기관)마다 rankedAt 이 오늘(KST)인지 따로 본다 · 한 묶음이 아니어도 다른 묶음 저장은 막지 않는다.
- ⑤ 전에는 어디서도 읽지 않는다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete

from backend.services.db import get_session

from .models import InvestorFlowDaily

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))
INVESTORS = {"foreigner": "foreigner", "institution": "institution"}   # 응답 키 → 저장 값
# (저장 값, 응답의 목록 칸, 금액 칸) · 금액 칸 이름은 순매도 쪽이 [추정] — 없으면 금액만 비우고 순위는 저장한다
_SIDES = (("buy", "netBuyRankings", "netBuyAmount"), ("sell", "netSellRankings", "netSellAmount"))


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _parse_ranked_at(raw: Any) -> Optional[datetime]:
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=_KST)


def parse_flow_groups(result: Any, today: str) -> dict[str, dict[str, Any]]:
    """응답 result → {투자자: {"ranked_at": dt, "rows": [(side, ticker, rank, amount)]}} · 오늘(KST) 묶음만.

    rankedAt 이 없거나 오늘이 아닌 묶음은 빠진다 (개인 묶음과 같은 판정 · 묶음마다 따로).
    """
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(result, dict):
        return out
    for key, investor in INVESTORS.items():
        grp = result.get(key)
        if not isinstance(grp, dict):
            continue
        ranked_at = _parse_ranked_at(grp.get("rankedAt"))
        if ranked_at is None or ranked_at.astimezone(_KST).date().isoformat() != today:
            continue
        rows: list[tuple[str, str, int, Optional[float]]] = []
        for side, list_key, amount_key in _SIDES:
            for it in grp.get(list_key) or []:
                if not isinstance(it, dict) or not it.get("symbol") or not it.get("rank"):
                    continue
                rows.append((side, str(it["symbol"]), int(it["rank"]), _to_float(it.get(amount_key))))
        if rows:
            out[investor] = {"ranked_at": ranked_at, "rows": rows}
    return out


async def save_investor_flows(result: Any, today: str) -> dict[str, int]:
    """외국인 · 기관 묶음을 새 표에 쓴다 (묶음마다 세션 하나 · 그날 그 묶음 행을 통째로 교체).

    예외는 올린다 — 호출한 쪽(collect_rank_daily)이 경고 로그만 남기고 기존 흐름을 이어 간다.
    """
    groups = parse_flow_groups(result, today)
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    saved: dict[str, int] = {}
    for investor, grp in groups.items():
        ranked_naive = grp["ranked_at"].astimezone(timezone.utc).replace(tzinfo=None)
        async with get_session() as session:
            await session.execute(delete(InvestorFlowDaily).where(
                InvestorFlowDaily.trade_date == today, InvestorFlowDaily.investor == investor,
            ))
            seen: set[tuple[str, str]] = set()
            for side, ticker, rank, amount in grp["rows"]:
                if (side, ticker) in seen:
                    continue
                seen.add((side, ticker))
                session.add(InvestorFlowDaily(
                    trade_date=today, investor=investor, side=side, ticker=ticker, rank=rank,
                    amount=amount, ranked_at=ranked_naive, captured_at=now,
                ))
        saved[investor] = len(seen)
    return saved
