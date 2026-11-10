"""1110-02 · VIP 적자 종목 탭 (계획 2.1) — 토스 보유 조회 1번 + DB.

탭에 넣는 종목 (하루 1회 보유 기록 기준):
 1. 비용 반영 손익 < 0 → reason="loss"
 2. 비용 반영 손익 ≥ 0 이고 흑자 전환 뒤 보유 기록 5행 이내 → reason="turned" (보유 성격과 상관없이 계산)
 3. 설정 종목(VIP_TICKER 의 점 앞 기호) → is_vip_config · 보유가 없으면 reason="config_only"
 4. 보유 기록이 없는 종목(오늘 산 종목)은 넣지 않는다 · 5. 토스 응답에 없는 종목(오늘 판 종목)은 뺀다.
포지션 값은 토스 응답 값 그대로(재계산 없음). 문장은 사실만 쓴다 (규칙 이름 · 명령문 없음).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select

from backend.services import holdings_swing as hs
from backend.services import real_holdings
from backend.services.models import HoldingSnapshot, SwingLongClose

GOAL_HOLD_TEXT = "보유 성격을 정하면 목표 칸이 보입니다"
LIMITS = [
    "탭 포함 여부는 가장 최근 하루 1회 보유 기록 기준이고, 탭의 손익은 지금 토스 값이라 부호가 다를 수 있습니다.",
    "오늘 산 종목은 다음 보유 기록(국내 15:50 · 미국 07:10) 뒤에 탭에 들어갑니다.",
    "흑자 전환 뒤 5거래일은 보유 기록 행 5개 기준이라 기록이 빠진 날만큼 길어집니다.",
]
SOLD_TODAY_LIMIT = "오늘 판 종목은 탭에서 뺐습니다."


def config_tag() -> tuple[Optional[str], str]:
    """설정 종목의 (토스 미국 기호 · 이름). 감시가 꺼져 있으면 (None, "")."""
    from backend.discovery.vip import config as vip_config

    cfg = vip_config.load()
    if not cfg.is_active:
        return None, ""
    return vip_config._derive_tag(cfg.ticker).upper(), cfg.company_name


def _position(row: Optional[real_holdings.HoldingRow]) -> Optional[dict]:
    if row is None:
        return None
    return {"avg_price": row.avg_price, "qty": row.qty, "current_price": row.last_price, "pnl": row.pnl,
            "pnl_pct": row.pnl_pct, "currency": row.currency, "source": "toss"}


def _streak(snaps: list[HoldingSnapshot]) -> list[HoldingSnapshot]:
    out: list[HoldingSnapshot] = []
    for s in snaps:
        out = [] if (s.qty or 0) <= 0 else out + [s]
    return out


async def build_tabs(session, toss_rows: list[real_holdings.HoldingRow], today: date,
                     now: Optional[datetime] = None) -> dict:
    now_utc = now or datetime.now(timezone.utc)
    live = {(r.market, r.symbol.upper()): r for r in toss_rows}
    cards = {(c["market"], c["symbol"].upper()): c for c in await hs.build_cards(session, today, now_utc)}
    tag, cfg_name = config_tag()
    limits = list(LIMITS)
    sold_today = False
    tabs: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for market in ("KR", "US"):
        for h in await hs._held(session, market):
            key = (market, h.symbol.upper())
            is_cfg = tag is not None and market == "US" and key[1] == tag
            row = live.get(key)
            if row is None:
                if not is_cfg:
                    sold_today = True  # 설정 종목이 아닌 보유 종목을 실제로 뺐을 때만 한계 줄을 붙인다
                    continue
            net = hs.net_pnl_pct(h.close, h.avg_price, market) if h.close and h.avg_price and h.avg_price > 0 else None
            reason, turn_date = None, None
            if net is not None and net < 0:
                reason = "loss"
            else:
                snaps = (await session.execute(select(HoldingSnapshot).where(
                    HoldingSnapshot.symbol == h.symbol, HoldingSnapshot.market == market,
                    HoldingSnapshot.kind == "holding").order_by(HoldingSnapshot.trade_date))).scalars().all()
                t = hs.profit_turn(_streak(list(snaps)), market)
                if t:
                    reason, turn_date = "turned", t["turn_date"]
            if row is None:
                reason = "config_only"  # 설정 종목인데 토스에는 없음(오늘 판 종목)
            elif reason is None:
                if not is_cfg:
                    continue
                reason = "config"
            tabs.append(_tab(market, h.symbol, row.name if row and row.name else h.name, reason, turn_date, is_cfg,
                             row, net, cards.get(key)))
            seen.add(key)

    if tag is not None and ("US", tag) not in seen:
        row = live.get(("US", tag))
        tabs.append(_tab("US", tag, (row.name if row and row.name else cfg_name) or tag, None if row is None else "config",
                         None, True, row, None, cards.get(("US", tag))))
        if row is None:
            tabs[-1]["reason"] = "config_only"
        # 보유 기록이 아직 없으면 그림은 긴 일봉 표에서 바로 만든다 (카드는 보유 기록이 있어야 생긴다)
        if tabs[-1]["chart"] is None:
            tabs[-1]["chart"] = await _chart_only(session, "US", tag, now_utc)

    def order(t: dict):
        net = t["_net"] if t["_net"] is not None else 0.0
        return (0 if t["is_vip_config"] else 1, 0 if t["reason"] == "loss" else 1, net)

    tabs.sort(key=order)
    for t in tabs:
        t.pop("_net")
    if sold_today:
        limits.append(SOLD_TODAY_LIMIT)
    return {"tabs": tabs, "limits": limits, "config_symbol": tag}


async def _chart_only(session, market: str, ticker: str, now_utc: datetime) -> Optional[dict]:
    from backend.services.real_holdings import _LOCAL_TZ

    rows = (await session.execute(select(SwingLongClose).where(
        SwingLongClose.market == market, SwingLongClose.ticker == ticker).order_by(SwingLongClose.trade_date))).scalars().all()
    if not rows:
        return None
    ser = ([r.trade_date for r in rows], [r.close for r in rows], rows[0].source)
    return hs.build_chart(market, ser, now_utc.astimezone(_LOCAL_TZ[market]).date())


def _tab(market, symbol, name, reason, turn_date, is_cfg, row, net, card) -> dict:
    goal = card.get("goal") if card else None
    out = {
        "market": market, "symbol": symbol, "name": name, "reason": reason, "turn_date": turn_date,
        "is_vip_config": is_cfg, "position": _position(row), "chart": card.get("chart") if card else None,
        "goal": goal, "goal_hold_reason": None, "horizon": card.get("horizon") if card else None,
        "ma_text": card.get("ma") if card else [], "card_status": card.get("status") if card else None,
        "_net": net,
    }
    if goal is None:
        out["goal_hold_reason"] = GOAL_HOLD_TEXT if (card is None or card.get("horizon") is None) else card.get("hold_reason")
    else:
        out["disclaimer"] = hs.DISCLAIMER
    return out
